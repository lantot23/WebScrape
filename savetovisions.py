import os
import re
import psycopg2
from psycopg2.extras import execute_values
import logging
from datetime import datetime, timezone
import json

# Helpers
def extract_model(text: str) -> str:
    """Extracts the last model name in parentheses."""
    matches = re.findall(r'\(([^()]+)\)', text)
    return matches[-1].strip() if matches else "N/A"

def clean_numeric(val: str, percent: bool = False):
    """Convert string to float, stripping $, %, commas."""
    if not val or val == "N/A":
        return None
    val = val.replace("$", "").replace(",", "").strip()
    if percent:
        val = val.replace("%", "")
    try:
        return float(val)
    except ValueError:
        return None

def parse_date(val: str):
    """Parse date string like 'Jan 01, 2024' into datetime."""
    if not val or val == "N/A":
        return None
    try:
        return datetime.strptime(val, "%b %d, %Y")
    except ValueError:
        return None
    
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

def save_to_visions(json_data: list[dict]):
    """Save parsed product JSON data into the visions table."""
    try:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            conn = psycopg2.connect(database_url)
        else:
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST"),
                port=os.getenv("DB_PORT", 5432),
                dbname=os.getenv("DB_NAME"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASS"),
            )

        now = datetime.now(timezone.utc) # UTC timestamp / make sure created_at column is TIMESTAMPTZ
        with conn, conn.cursor() as cur:
            rows = [
                (
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
                    item.get("upc"),
                    now  # created_at timestamp
                )
                for item in json_data
            ]

            execute_values(
                cur,
                """
                INSERT INTO visions (
                    url, title, brand, model,
                    current_price, regular_price, percentage_discount, dollar_discount,
                    eco_fee, num_reviews, avg_rating,
                    main_category, sale_ends, upc, created_at
                ) VALUES %s
                """,
                rows,
            )

        logging.info("Saved %d products to Postgres.", len(rows))

    except Exception as e:
        logging.error("Failed to save data to visions: %s", e)
        raise


def main():
    """Entry point: load JSON file and save to visions table."""
    json_file = "visions_clearance_products.json"  # 👈 replace with your filename
    if not os.path.exists(json_file):
        logging.error("JSON file not found: %s", json_file)
        return

    with open(json_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            logging.error("Failed to parse JSON: %s", e)
            return

    if not isinstance(data, list):
        logging.error("JSON root must be a list of products.")
        return

    save_to_visions(data)


if __name__ == "__main__":
    main()
