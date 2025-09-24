from DrissionPage import ChromiumPage
import time
import re
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from parsel import Selector
import os
from urllib.parse import urlparse
import psycopg2

load_dotenv()


def scrape_by_page(pages):
    scraped_data = []
    for page_num in pages:
        print(f"Scraping page {page_num}")
        url = f"https://www.shoppersdrugmart.ca/shop/categories/offers/c/FS-Offers?nav=%2Fshop%2Fcategories%2Foffers&q=trending&showInStock=true&page={page_num}&sort=top-rated&promotions=PC%2BOptimum%2BOffer&promotions=Sale&promotions=Clearance"
        page_data = scrape_page(url)
        scraped_data.extend(page_data)
    return scraped_data


def save_product(product: dict):
    """
    Save a single scraped product into PostgreSQL.
    """
    # Connect to database
    DATABASE_URL = os.getenv("DATABASE_URL")
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
    else:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT", 5432),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
        )

    # Normalize img_urls
    img_urls = product.get("img_urls")
    if isinstance(img_urls, str):  # By Page
        img_urls = [img_urls]

    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shoppersdrugmart (
                    type, title, brand, rating, review,
                    price, old_price, promotion_type, promo_ends,
                    url, scraped_at, img_urls
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                product.get("type"),
                product.get("title"),
                product.get("brand"),
                product.get("rating"),
                product.get("review"),
                product.get("price"),
                product.get("old_price"),
                product.get("promotion_type"),
                product.get("promo_ends"),
                product.get("url"),
                product.get("scraped_at") or datetime.now(timezone.utc).isoformat(),
                img_urls
            ))
    conn.close()
    """
    table Schema for the table
        CREATE TABLE shoppersdrugmart (
            id SERIAL PRIMARY KEY,
            type VARCHAR(20),       
            title VARCHAR(255),
            brand VARCHAR(255),
            rating VARCHAR(10),
            review VARCHAR(50),
            price VARCHAR(20),
            old_price VARCHAR(20),
            promotion_type VARCHAR(50),
            promo_ends TIMESTAMP WITH TIME ZONE,
            url TEXT,
            scraped_at TIMESTAMPTZ,
            img_urls TEXT[]                  -- array of image URLs
        );
    """

# Helpers
def parse_promo_date(raw_text):
    """Convert 'Offer ends Month DD at H:Mam GMT+8' to get the actual date"""
    if not raw_text:
        return None
    try:
        cleaned = raw_text.replace("Offer ends", "").strip()
        # Try parsing with timezone first
        try:
            dt = datetime.strptime(cleaned, "%b %d at %I:%M%p GMT%z")
        except ValueError:
            # Fallback: if no timezone, just parse without GMT part
            dt = datetime.strptime(cleaned, "%b %d at %I:%M%p")
        return dt.isoformat()
    except Exception as e:
        print(f"⚠️ Could not parse promo date '{raw_text}': {e}")
        return raw_text

def extract_price(text: str) -> str | None:
    if not text:
        return None
    text = text.strip()
    match = re.search(r"\$\d+(?:\.\d{1,2})?", text)
    return match.group(0) if match else None

# Scraping by URLs'
def scrape_url_page(tab):
    """Scrape a single product URL page from its tab"""
    tab.wait(10)

    sel = Selector(text=tab.html)

    brand = sel.css("p.plp__brandName__8MSID::text").get()
    title = sel.css("h1.plp__pageHeading__zUcEq::text").get()
    rating = sel.css("div.pr-snippet-rating-decimal::text").get()
    review = sel.css("a.pr-snippet-review-count::text").get()

    # price container element
    price_container = tab.ele('css:p[data-testid="price-container"]')

    price = None
    old_price = None

    if price_container:
        # check for strike-through old price
        old_price_el = price_container.ele('css:span.plp__priceStrikeThrough__2MAlQ')
        old_price = old_price_el.text if old_price_el else None

        # current price is the text outside the strike-through span
        # remove inner span text if exists
        price_text = price_container.text
        if old_price:
            price = price_text.replace(old_price, "").strip()
        else:
            price = price_text.strip()

        # fallback: if price missing but old_price exists
        if not price and old_price:
            price = old_price
        
        price = extract_price(price)
        old_price = extract_price(old_price)
        
    img_urls = []
    carousel_imgs = tab.eles('css:ul.plp__list__1QwAH li img.plp__image__WzRYO')
    for img in carousel_imgs:
        src = img.attr('src')
        if src:
            img_urls.append(src)

    promo_type = sel.css("div.plp__offerContainer__2pipm > h3::text").get()
    promo_raw_date = sel.css("div.plp__offerContainer__2pipm > p > span.plp__date__1U7ai::text").get()
    promo_ends = parse_promo_date(promo_raw_date)

    item = {
        "type": "By URL",
        "title": title.strip() if title else None,
        "brand": brand.strip() if brand else None,
        "rating": rating.strip() if rating else None,
        "review": review.strip() if review else None,
        "price": price.strip() if price else None,
        "old_price": old_price.strip() if old_price else None,
        "promotion_type": promo_type.strip() if promo_type else None,
        "promo_ends": promo_ends,
        "url": tab.url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "img_urls": img_urls
    }

    return item

# Get text(.txt) files then loop through it then calls scrape_url_page to scrape per tab
def scrape_urls_from_file(filename):
    """Read URLs from file, auto-detect root URL, then scrape each URL in new tabs"""
    if not os.path.exists(filename):
        print(f"File not found: {filename}")
        return []

    with open(filename, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    if not urls:
        print("No URLs found in file.")
        return []

    # Auto-detect root URL from the first URL
    parsed = urlparse(urls[0])
    root_url = f"{parsed.scheme}://{parsed.netloc}"

    page = ChromiumPage()
    scraped_results = []

    try:
        # open root page first
        print(f"Opening root page: {root_url}")
        page.get(root_url)
        page.wait(10)

        for i, url in enumerate(urls, 1):
            print(f"\nOpening product URL {i}/{len(urls)}: {url}")
            tab = page.new_tab(url)
            page.activate_tab(tab)

            try:
                item = scrape_url_page(tab)
                scraped_results.append(item)
                print(f"Scraped: {item['title']} at {url}")
                save_product(item)
            except Exception as e:
                print(f"Error scraping {url}: {e}")
            finally:
                tab.close()

    finally:
        page.quit()

    print(f"\nFinished scraping {len(urls)} URLs from {filename}")
    return scraped_results

# Scraping by page[1-2, 5, 5-7]
def scrape_page(url: str):
    page = ChromiumPage()
    try:
        page.get(url)

        product_grid = page.wait(10).ele('xpath://div[@data-testid="product-grid"]')
        if not product_grid:
            print("Product grid not found")
            return []

        html = product_grid.html
        sel = Selector(text=html)

        scraped_data = []
        products = sel.css('div.chakra-linkbox')

        price_re = re.compile(r'\$\s*\d{1,3}(?:[,\d{3}]*)?(?:\.\d{1,2})?')  # matches $10.99, $1,234.56
        # Helper
        def extract_price_from_textnodes(text_nodes):
            """Given a list of text nodes (e.g. ['sale', ' $10.99']), return the $ amount or None."""
            if not text_nodes:
                return None
            combined = " ".join(t.strip() for t in text_nodes if t and t.strip())
            m = price_re.search(combined)
            if m:
                # normalize spacing and commas kept for readability, you can strip commas if you want numeric
                return m.group().replace(" ", "")
            # fallback: maybe price without $ (e.g. '10.99')
            m2 = re.search(r'\d+\.\d{2}', combined)
            if m2:
                return m2.group()
            return None

        for i, product in enumerate(products):
            try:
                title = product.css('[data-testid="product-title"]::text').get()
                brand = product.css('[data-testid="product-brand"]::text').get()
                img_url = product.css('[data-testid="product-image"] img::attr(src)').get()
                product_link = product.css('a.chakra-linkbox__overlay::attr(href)').get()

                # get text nodes for price and was-price (span + following text nodes)
                price_text_nodes = product.css('p[data-testid="price"]::text').getall()
                if not price_text_nodes:
                    # alternate container fallback
                    price_text_nodes = product.css('[data-testid="price-product-tile"] p[data-testid="price"]::text').getall()

                was_text_nodes = product.css('p[data-testid="was-price"]::text').getall()
                if not was_text_nodes:
                    was_text_nodes = product.css('[data-testid="price-product-tile"] p[data-testid="was-price"]::text').getall()

                price = extract_price_from_textnodes(price_text_nodes)
                old_price = extract_price_from_textnodes(was_text_nodes)

                # If price is missing but old_price exists, use old_price as price
                if not price and old_price:
                    price = old_price

                # collect promotion badges (can be multiple)
                promos = product.css('[data-testid="product-deal-badge"]::text').getall()
                pco = product.css('[data-testid="product-pco-badge"]::text').getall()
                badges = [p.strip() for p in (promos + pco) if p and p.strip()]
                promotion_type = ", ".join(badges) if badges else None

                item = {
                    "type": "By Page",
                    "title": title,
                    "brand": brand,
                    "rating": None,
                    "review": None,
                    "price": price,
                    "old_price": old_price,
                    "promotion_type": promotion_type,
                    "promo_ends": None,
                    "url": product_link,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "img_urls": img_url,
                }
                save_product(item)
                scraped_data.append(item)
                print(f"Scraped product {i+1}: {title}")

            except Exception as e:
                print(f"Error scraping product {i+1}: {e}")
                continue

        print(f"Successfully scraped {len(scraped_data)} products from {url}")
        return scraped_data

    finally:
        page.quit()

def main():
    print("Choose an option:")
    print("[1] Scrape by page (e.g., 1-3, 5, 5-10)")
    print("[2] Search by URL")

    choice = input("Enter your choice: ")
    scraped_data = []
    if choice == "1":
        pages_input = input("Enter pages to scrape (e.g., 1-3, 5, 5-10): ")
        pages = parse_page_input(pages_input)
        scraped_data = scrape_by_page(pages)
    
    elif choice == "2":
        filename = input("Enter text file with URLs: ").strip()
        scraped_data = scrape_urls_from_file(filename)

    # Save scraped data to a JSON file
    with open("scraped_products.json", "w", encoding="utf-8") as f:
        json.dump(scraped_data, f, ensure_ascii=False, indent=2)
    
    print(f"Successfully scraped {len(scraped_data)} products")

def parse_page_input(input_str):
    pages = []
    for part in input_str.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    return pages

if __name__ == "__main__":
    main()
