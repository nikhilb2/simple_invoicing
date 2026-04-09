"""
Add supplier_invoice_number column to invoices.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices ADD COLUMN IF NOT EXISTS supplier_invoice_number VARCHAR;
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS supplier_invoice_number"))
