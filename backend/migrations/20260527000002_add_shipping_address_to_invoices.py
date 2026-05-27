"""
Add shipping_address and shipping_address_label snapshot columns to invoices.
These are populated at invoice creation time and are independent of any changes
to the saved ledger_addresses records.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS shipping_address       TEXT DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS shipping_address_label VARCHAR(255) DEFAULT NULL;
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices
        DROP COLUMN IF EXISTS shipping_address,
        DROP COLUMN IF EXISTS shipping_address_label;
    """))
