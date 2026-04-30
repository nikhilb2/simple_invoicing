"""
Make invoice item quantity decimal-capable.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoice_items
        ALTER COLUMN quantity TYPE NUMERIC(12, 3)
        USING quantity::numeric;
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoice_items
        ALTER COLUMN quantity TYPE INTEGER
        USING ROUND(quantity)::integer;
    """))
