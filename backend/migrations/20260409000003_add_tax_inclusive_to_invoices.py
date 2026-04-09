"""
Add tax_inclusive flag to invoices.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices ADD COLUMN IF NOT EXISTS tax_inclusive BOOLEAN DEFAULT FALSE;
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS tax_inclusive"))
