"""
Schema introspection with sample values.
The sample values are the single biggest accuracy lever in this project.
"""

import sqlite3
from typing import Optional


# Hand-written FK relationships for Olist.
# SQLite won't have these declared so we spell them out for the model.
FOREIGN_KEYS = """
FOREIGN KEY RELATIONSHIPS:
  orders.customer_id           -> customers.customer_id
  order_items.order_id         -> orders.order_id
  order_items.product_id       -> products.product_id
  order_items.seller_id        -> sellers.seller_id
  order_payments.order_id      -> orders.order_id
  order_reviews.order_id       -> orders.order_id
  products.product_category_name -> category_translation.product_category_name
  customers.customer_zip_code_prefix -> geolocation.geolocation_zip_code_prefix
  sellers.seller_zip_code_prefix     -> geolocation.geolocation_zip_code_prefix

IMPORTANT NOTES:
  - Each order can have MULTIPLE rows in order_items (one per product).
  - Each order can have MULTIPLE rows in order_payments (split payments).
  - order_items.price is per-item. Total order value = SUM(price) across order_items.
  - All timestamps are TEXT in 'YYYY-MM-DD HH:MM:SS' format. Use substr() or strftime().
  - review_score is integer 1-5.
  - order_status values: 'delivered', 'shipped', 'canceled', 'unavailable', etc.
  - customer_unique_id = real person. customer_id = per-order (one person can have multiple).
"""


def describe_schema(con: sqlite3.Connection, tables: Optional[list[str]] = None, sample_count: int = 3) -> str:
    """Build a schema description string with sample values per column."""
    all_tables = [
        row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    if tables:
        all_tables = [t for t in all_tables if t in tables]

    blocks = []
    for table in all_tables:
        cols = con.execute(f"PRAGMA table_info({table})").fetchall()
        row_count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        lines = []
        for col in cols:
            col_name, col_type = col[1], col[2] or "TEXT"
            not_null = "NOT NULL" if col[3] else ""
            try:
                samples_raw = con.execute(
                    f"SELECT DISTINCT [{col_name}] FROM [{table}] "
                    f"WHERE [{col_name}] IS NOT NULL LIMIT {sample_count}"
                ).fetchall()
                samples = ", ".join(repr(str(v[0])[:40]) for v in samples_raw)
            except Exception:
                samples = "?"
            lines.append(f"    {col_name} ({col_type}) {not_null}  e.g. {samples}")

        blocks.append(f"TABLE {table}  ({row_count:,} rows)\n" + "\n".join(lines))

    return "\n\n".join(blocks) + "\n\n" + FOREIGN_KEYS
