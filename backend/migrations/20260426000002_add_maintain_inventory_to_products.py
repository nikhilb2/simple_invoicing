"""
Add maintain_inventory flag to products.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS maintain_inventory BOOLEAN NOT NULL DEFAULT TRUE;
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE products DROP COLUMN IF EXISTS maintain_inventory"))
