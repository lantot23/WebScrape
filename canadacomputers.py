import requests
from parsel import Selector
import psycopg2
from psycopg2.extras import execute_values
import time, random
from dotenv import load_dotenv
import os


load_dotenv()

BASE_URL = "https://www.canadacomputers.com/en/clearance"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.canadacomputers.com/en/clearance",
}

session = requests.Session()
session.headers.update(HEADERS)


# Helpers

def parse_price(value: str) -> float:
    """Convert price string to float. Return 0 if null or invalid."""
    if not value:
        return 0.0
    try:
        return float(value.replace("$", "").replace(",", "").strip())
    except ValueError:
        return 0.0

def parse_rating(value: str) -> float:
    """Convert rating string to float. Return 0 if null or invalid."""
    if not value:
        return 0.0
    try:
        return float(value.strip())
    except ValueError:
        return 0.0
    
def parse_reviews(value: str) -> int:
    """Convert reviews string to int. Return 0 if null or invalid."""
    if not value:
        return 0
    try:
        return int(value.strip())
    except ValueError:
        return 0

def parse_stock(value: str) -> bool:
    """Convert stock indicator to boolean. 
    Example: '1' -> True, '' or None -> False
    """
    return str(value).strip() == "1"

# Save to DB
def save_to_db(products):
    
    """
        Schema for table
        
        CREATE TABLE IF NOT EXISTS canadacomputers (
            id SERIAL PRIMARY KEY,
            url VARCHAR(2000),
            title VARCHAR(255),
            brand VARCHAR(255),
            model VARCHAR(255),
            current_price NUMERIC(10,2),
            regular_price NUMERIC(10,2),
            percentage_discount NUMERIC(10,2),
            rating NUMERIC(3,2),
            reviews INTEGER,
            in_stock_online BOOLEAN,
            in_stock_retail BOOLEAN,
            image_url VARCHAR(2000)
        );

    """
    
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
    cur = conn.cursor()

    insert_query = """
        INSERT INTO canadacomputers (
            url, title, brand, model, current_price,
            regular_price, percentage_discount, rating, reviews,
            in_stock_online, in_stock_retail, image_url
        ) VALUES %s
    """

    values = []
    for p in products:
        # discount %
        discount = None
        try:
            if p["regular_price"] and p["current_price"]:
                r = p["regular_price"]
                c = p["current_price"]
                if r > 0:
                    discount = round(((r - c) / r) * 100, 2)
        except:
            pass

        values.append((
            p["url"],
            p["title"],
            None,   # brand placeholder
            None,   # model placeholder
            p["current_price"],
            p["regular_price"],
            discount,
            p["rating"],
            p["reviews"],
            p["in_stock_online"],
            p["in_stock_retail"],
            p["image"]
        ))

    if values:
        execute_values(cur, insert_query, values)
        conn.commit()

    cur.close()
    conn.close()

# Page Scraper
def scrape_page(page: int):
    url = f"{BASE_URL}?page={page}&ajaxtrue=1&onlyproducts=1"
    resp = session.get(url)
    html = resp.text.strip()
    if not html or "js-product" not in html:
        return []

    sel = Selector(html)
    products = []
    for prod in sel.css("div.js-product"):
        data = {
            "id": prod.css("article::attr(data-id-product)").get(),
            "title": prod.css("h2.product-title a::text").get(),
            "url": prod.css("h2.product-title a::attr(href)").get(),
            "image": prod.css("img::attr(data-full-size-image-url)").get(),
            "current_price": parse_price(prod.css("div.product-description::attr(data-final_price)").get()),
            "regular_price": parse_price(prod.css("div.product-description::attr(data-regular_price)").get()),
            "rating": parse_rating(prod.css(".review-icon::attr(data-score)").get()),
            "reviews": parse_reviews(prod.css(".star-number::text").re_first(r"\d+")),
            "in_stock_online": parse_stock(prod.css(".available-tag::attr(data-stock_availability_online)").get()),
            "in_stock_retail": parse_stock(prod.css(".available-tag::attr(data-stock_availability_retail)").get()),
        }
        products.append(data)
    return products

def scrape_all():
    page = 1
    while True:
        products = scrape_page(page)
        if not products:
            print(f"Done. No more products after page {page}")
            break
        save_to_db(products)
        print(f"Saved page {page} with {len(products)} products")
        time.sleep(random.uniform(1, 3)) # Just a little respect to the site since we're bombarding it with request ✌️, or we can remove this line 😅
        page += 1

def scrape_range(start, end):
    for page in range(start, end + 1):
        products = scrape_page(page)
        if not products:
            print(f"No products found on page {page}, stopping.")
            break
        save_to_db(products)
        print(f"Saved page {page} with {len(products)} products")
        time.sleep(random.uniform(1, 3)) # Just a little respect to the site since we're bombarding it with request ✌️, or we can remove this line 😅
    

if __name__ == "__main__":
    choice = input("Choose an option:\n[1] Scrape ALL pages\n[2] Scrape page or range (e.g. 1-4)\n> ").strip()
    if choice == "1":
        print("Scraping all pages")
        scrape_all()
    elif choice == "2":
        page_input = input("Enter page or range (e.g. 1 or 1-4): ").strip()
        if "-" in page_input:
            start, end = map(int, page_input.split("-"))
            scrape_range(start, end)
        else:
            page = int(page_input)
            scrape_range(page, page)  # single page
    else:
        print("Invalid choice. Exiting.")

