"""Add purchase_price and reorder_level to products table."""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(10, 2) NOT NULL DEFAULT 0;
    """))

    conn.execute(text("""
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS reorder_level NUMERIC(10, 2) NOT NULL DEFAULT 0;
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE products DROP COLUMN IF EXISTS reorder_level"))
    conn.execute(text("ALTER TABLE products DROP COLUMN IF EXISTS purchase_price"))
