import time
import logging
from datetime import datetime
from dotenv import load_dotenv
import os
import json
import re
from CloudflareBypasser import CloudflareBypasser
from DrissionPage import ChromiumPage, ChromiumOptions
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values

load_dotenv()

# Helpers
def extract_model(text):
    matches = re.findall(r'\(([^()]+)\)', text)  # only matches non-nested parentheses
    if matches:
        return matches[-1].strip()  # take the last one
    return "N/A"

def clean_numeric(val, percent=False):
    if not val or val == "N/A":
        return None
    val = val.replace("$", "").replace(",", "").strip()
    if percent:
        val = val.replace("%", "")
    try:
        return float(val)
    except ValueError:
        return None

def parse_date(val):
    if not val or val == "N/A":
        return None
    try:
        return datetime.strptime(val, "%b %d, %Y")
    except Exception:
        return None
    
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

# Save to POSTGRES DB
def save_to_visions(json_data):
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

    rows = []
    for item in json_data:
        rows.append((
            item.get("url"),
            item.get("title"),
            item.get("brand"),
            None if item.get("model") == "N/A" else item.get("model"),
            clean_numeric(item.get("current_price")),
            clean_numeric(item.get("regular_price")),
            clean_numeric(item.get("percentage_discount"), percent=True),
            clean_numeric(item.get("dollar_discount")),
            clean_numeric(item.get("eco_fee")),
            clean_numeric(item.get("num_reviews")),
            clean_numeric(item.get("avg_rating")),
            item.get("main_category"),
            parse_date(item.get("sale_ends")),
        ))

    # Insert or update on conflict (upsert)
    execute_values(cur, """
        INSERT INTO visions (
            url, title, brand, model,
            current_price, regular_price, percentage_discount, dollar_discount,
            eco_fee, num_reviews, avg_rating,
            main_category, sale_ends
        ) VALUES %s
        """, rows)


    conn.commit()
    cur.close()
    conn.close()

    logging.info(f"Saved {len(rows)} products to Postgres.")


def get_chromium_options(browser_path: str, arguments: list) -> ChromiumOptions:
    """
    Configures and returns Chromium options with better WebSocket handling.
    """
    options = ChromiumOptions().auto_port()
    options.set_paths(browser_path=browser_path)
    
    # Add essential arguments for better stability
    essential_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-sync",
        "--disable-translate",
        "--disable-features=VizDisplayCompositor",
        "--disable-setuid-sandbox",
        "--disable-web-security",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-breakpad",
        "--disable-client-side-phishing-detection",
        "--disable-crash-reporter",
        "--disable-ipc-flooding-protection",
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--remote-debugging-port=9222",
        "--remote-debugging-address=0.0.0.0",
        "--use-gl=swiftshader",
        "--single-process",
        "--no-zygote",
        "--no-first-run",
        "--metrics-recording-only",
        "--password-store=basic",
        "--use-mock-keychain",
        "--no-default-browser-check",
        "--window-size=1920,1080",
        "--user-data-dir=/tmp/chrome-user-data",
        "--disable-blink-features=AutomationControlled",
        "--enable-automation"
    ]
    
    for arg in essential_args + arguments:
        options.set_argument(arg)
    
    # Remove duplicate arguments
    options._arguments = list(set(options._arguments))
    
    return options

def extract_product_data(product, category):
    """
    Extract product information from a product element.
    """
    try:
        # Extract URL
        product_link = product.find('a', class_='product-item-link')
        url = product_link.get('href') if product_link else "N/A"
        
        # Extract title
        title = product_link.get_text(strip=True) if product_link else "N/A"
        
        # Extract brand (assuming it's the first word in the title)
        brand = title.split(' ')[0] if title != "N/A" else "N/A"
        
        # Extract model (from the product ID in the data attributes)
        product_info = product.find('div', class_='product-item-info')
        model = extract_model(title)
        
        # Extract prices
        special_price_span = product.find('span', class_='special-price')
        if special_price_span:
            price_span = special_price_span.find('span', class_='price-wrapper')
            current_price = price_span.get_text(strip=True) if price_span else "N/A"
        else:
            current_price = "N/A"
        
        old_price_span = product.find('span', class_='old-price')
        if old_price_span:
            price_wrapper = old_price_span.find('span', class_='price-wrapper')
            regular_price = price_wrapper.get_text(strip=True) if price_wrapper else "N/A"
        else:
            # If no old price, use final price
            final_price_span = product.find('span', class_='price-wrapper')
            regular_price = final_price_span.get_text(strip=True) if final_price_span else "N/A"
        
        # Extract discounts
        tier_price = product.find('span', class_='vision-tier-price')
        if tier_price:
            dollar_discount_text = tier_price.get_text(strip=True)
            dollar_discount_match = re.search(r'Save\$(.+)', dollar_discount_text)
            dollar_discount = dollar_discount_match.group(1) if dollar_discount_match else "N/A"
        else:
            dollar_discount = "N/A"
        
        # Calculate percentage discount if both prices are available
        if current_price != "N/A" and regular_price != "N/A":
            try:
                current_num = float(re.sub(r'[^\d.]', '', current_price))
                regular_num = float(re.sub(r'[^\d.]', '', regular_price))
                percentage_discount = f"{((regular_num - current_num) / regular_num * 100):.1f}%"
            except:
                percentage_discount = "N/A"
        else:
            percentage_discount = "N/A"
        
        # Extract eco fee (not always present)
        eco_fee = "N/A"  # This site doesn't seem to display eco fees
        
        # Extract reviews and rating
        reviews_element = product.find('div', class_='pr-category-snippet__total')
        num_reviews = reviews_element.get_text(strip=True).replace('Reviews', '').strip() if reviews_element else "0"
        
        rating_element = product.find('div', class_='pr-snippet-rating-decimal')
        avg_rating = rating_element.get_text(strip=True) if rating_element else "N/A"
        
        # Extract sale end date
        sale_ends_element = product.find('div', class_='rw-grid-date')
        sale_ends = sale_ends_element.get_text(strip=True).replace('Sale Ends: ', '') if sale_ends_element else "N/A"
        
        return {
            'url': url,
            'title': title,
            'brand': brand,
            'model': model,
            'current_price': current_price,
            'regular_price': regular_price,
            'percentage_discount': percentage_discount,
            'dollar_discount': dollar_discount,
            'eco_fee': eco_fee,
            'num_reviews': num_reviews,
            'avg_rating': avg_rating,
            'main_category': category,
            'sale_ends': sale_ends
        }
        
    except Exception as e:
        logging.error(f"Error extracting product data: {e}")
        return None

def print_product_info(product):
    """
    Print product information to console.
    """
    print("\n" + "="*80)
    print(f"Title: {product['title']}")
    print(f"Brand: {product['brand']}")
    print(f"Model: {product['model']}")
    print(f"Category: {product['main_category']}")
    print(f"Current Price: {product['current_price']}")
    print(f"Regular Price: {product['regular_price']}")
    print(f"Discount: {product['dollar_discount']} ({product['percentage_discount']})")
    print(f"Rating: {product['avg_rating']} ({product['num_reviews']} reviews)")
    print(f"Sale Ends: {product['sale_ends']}")
    print(f"URL: {product['url']}")
    print("="*80)

def scroll_to_load_all_products(driver):
    """
    Scroll to load all products (handle lazy loading).
    """
    last_height = driver.run_js("return document.body.scrollHeight")
    scroll_attempts = 0
    max_scroll_attempts = 6
    products_count = 0

    while scroll_attempts < max_scroll_attempts:
        # Scroll down
        driver.run_js("window.scrollTo(0, document.body.scrollHeight);")

        # Try to click "Load More" button if present
        clicked = False
        try:
            load_more_button = driver.ele("xpath://button[contains(., 'Load more')]", timeout=5)
            if load_more_button:
                logging.info(f"Found Load More button selector")
                # Scroll into view
                load_more_button.scroll.to_center()
                    
                try:
                    load_more_button.click()
                    clicked = True
                except Exception as e:
                    #logging.warning(f"Normal click failed ({e}), using JS click")
                    load_more_button.click.by_js()

                    # Wait for new content or spinner to disappear
                driver.wait.ele_not_found("css:svg.amscroll-loading-icon.-amscroll-animate", timeout=10)

                scroll_attempts = 0
                break
        except Exception as inner_e:
            logging.debug(f"Selector button failed: {inner_e}")
        
        # Wait for new content
        time.sleep(2 if not clicked else 4)  # fallback wait
        new_height = driver.run_js("return document.body.scrollHeight")

        if new_height == last_height:
            scroll_attempts += 1
            logging.info(f"No new content. Attempt {scroll_attempts}/{max_scroll_attempts}")
        else:
            scroll_attempts = 0
            logging.info(f"New content loaded. Scroll height: {new_height}")
        last_height = new_height

        # Count products
        current_products = driver.eles("css:li.item.product.product-item")
        if len(current_products) > products_count:
            products_count = len(current_products)
            logging.info(f"Currently loaded {products_count} products")
   
def scroll_through_all_items(driver):
    """
    Alternative method: Scroll through each product item individually
    """
    # Get all product elements
    product_elements = driver.eles('tag:li@class:item product product-item')
    
    for i, product_element in enumerate(product_elements):
        try:
            # Scroll to each product element to ensure it's loaded
            driver.run_js('arguments[0].scrollIntoView({behavior: "smooth", block: "center"});', product_element)
            time.sleep(0.5)  # Brief pause for content to load
                 
        except Exception as e:
            logging.debug(f"Error scrolling to product {i}: {e}")

def scrape_category(driver, category_id, category_name):
    """
    Scrape all products from a specific category.
    """
    logging.info(f"Scraping category: {category_name}")
    
    # Navigate to the category URL
    category_url = f"https://www.visions.ca/deals/clearance?cat={category_id}&visions_item_status=239699#clearancedeals"
    driver.get(category_url)
    time.sleep(5)  # Wait for page to load
    
    # Method 1: Scroll to load all content
    scroll_to_load_all_products(driver)
    
    # Method 2: Scroll through each item individually
    scroll_through_all_items(driver)
    
    # Use JavaScript to get ALL product elements
    products_js = """
    return Array.from(document.querySelectorAll('li.item.product.product-item')).map(product => {
        return product.outerHTML;
    });
    """
    
    product_htmls = driver.run_js(products_js)
    logging.info(f"Found {len(product_htmls)} product elements using JavaScript")
    
    products = []
    for i, product_html in enumerate(product_htmls):
        try:
            soup = BeautifulSoup(product_html, 'html.parser')
            product_data = extract_product_data(soup, category_name)
            if product_data:
                products.append(product_data)
                if i < 1:  # Print product for verification
                    print_product_info(product_data)
        except Exception as e:
            logging.error(f"Error processing product {i}: {e}")
    
    logging.info(f"Successfully extracted {len(products)} products from {category_name}")
    return products

def main():
    isHeadless = os.getenv('HEADLESS', 'false').lower() == 'true'
    
    if isHeadless:
        from pyvirtualdisplay import Display
        display = Display(visible=0, size=(1920, 1080))  # visible=0 for true headless
        display.start()
        #pass

    browser_path = os.getenv('CHROME_PATH', "/usr/bin/google-chrome")
    
    print("Launching Chrome from:", browser_path)
    # Arguments for headless mode (added headless-specific args)
    arguments = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--force-color-profile=srgb",
        "--metrics-recording-only",
        "--password-store=basic",
        "--use-mock-keychain",
        "--export-tagged-pdf",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--deny-permission-prompts",
        "--accept-lang=en-US",
        "--window-size=1920,1080",
    ]
    
    # Add headless argument if running headless
    if isHeadless:
        arguments.append("--headless=new")

    options = get_chromium_options(browser_path, arguments)

    # Initialize the browser
    driver = ChromiumPage(addr_or_opts=options)
    
    # Define categories to scrape
    main_categories = {
        36: "Television",
        40: "Home Audio", 
        16: "Laptops",
        6: "Personal Audio",
        15: "Cameras and Drones",
        17: "Smart Lighting",
        488: "A/C and Cooling",
        5: "Car Tech",
        13: "Wearables",
        46: "Car Accessories",
        18: "Major Appliances",
        19: "Small Appliances"
    }
    exclude_categories = {
        36: "Television",
        18: "Major Appliances"
    }
    
    categories = {k: v for k, v in main_categories.items() if k not in exclude_categories}

    all_products = []
    
    try:
        logging.info('Starting Visions.ca scraper')
        
        # First, navigate to the main page to bypass Cloudflare if needed
        logging.info('Navigating to the main page.')
        logging.info(os.getenv("VISIONSITE"))
        driver.get(os.getenv("VISIONSITE"))
        time.sleep(3)

        # Try to bypass Cloudflare if it's detected
        try:
            logging.info('Attempting Cloudflare bypass.')
            cf_bypasser = CloudflareBypasser(driver)
            cf_bypasser.bypass()
            logging.info("Cloudflare bypass completed!")
        except Exception as e:
            logging.warning(f"Cloudflare bypass may have failed: {e}")
        
        logging.info("Current Page: %s", driver.title)
        
        # Scrape each category
        for category_id, category_name in categories.items():
            try:
                category_products = scrape_category(driver, category_id, category_name)
                all_products.extend(category_products)
                logging.info(f"Completed scraping {category_name}. Total products so far: {len(all_products)}")
            except Exception as e:
                logging.error(f"Error scraping category {category_name}: {e}")
        
        # Save all products to JSON file
        #with open('visionsclearance.json', 'w', encoding='utf-8') as f:
            #json.dump(all_products, f, indent=2, ensure_ascii=False)
        #logging.info("Data saved to visionsclearance.json")
        save_to_visions(all_products)
        logging.info(f"Scraping completed! Found {len(all_products)} products.")
        
        
        
    except Exception as e:
        logging.error("An error occurred: %s", str(e))
    finally:
        logging.info('Closing the browser.')
        driver.quit()
        if isHeadless:
            display.stop()

if __name__ == '__main__':
    main()