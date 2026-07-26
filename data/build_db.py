"""
Load Olist CSVs into SQLite with clean table names and indexes.
Download the dataset from https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
Unzip CSVs into data/raw/, then run this script.
"""

import sqlite3
import pandas as pd
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw"
DB_PATH = Path(__file__).parent / "warehouse.db"

# map long Olist CSV names to shorter table names
TABLE_MAP = {
    "olist_customers_dataset": "customers",
    "olist_orders_dataset": "orders",
    "olist_order_items_dataset": "order_items",
    "olist_order_payments_dataset": "order_payments",
    "olist_order_reviews_dataset": "order_reviews",
    "olist_products_dataset": "products",
    "olist_sellers_dataset": "sellers",
    "product_category_name_translation": "category_translation",
    "olist_geolocation_dataset": "geolocation",
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id)",
    "CREATE INDEX IF NOT EXISTS idx_order_items_seller ON order_items(seller_id)",
    "CREATE INDEX IF NOT EXISTS idx_order_payments_order ON order_payments(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_order_reviews_order ON order_reviews(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_products_category ON products(product_category_name)",
    "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status)",
]


def build():
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(str(DB_PATH))

    for csv_path in sorted(RAW_DIR.glob("*.csv")):
        table_name = TABLE_MAP.get(csv_path.stem, csv_path.stem)
        df = pd.read_csv(csv_path)
        df.to_sql(table_name, con, if_exists="replace", index=False)
        print(f"  {csv_path.name} -> {table_name} ({len(df):,} rows)")

    for idx in INDEXES:
        con.execute(idx)
    con.commit()
    con.close()
    print(f"\nDone. Database at {DB_PATH}")


if __name__ == "__main__":
    if not RAW_DIR.exists() or not list(RAW_DIR.glob("*.csv")):
        print("No CSVs found in data/raw/. Download from Kaggle first.")
    else:
        build()
