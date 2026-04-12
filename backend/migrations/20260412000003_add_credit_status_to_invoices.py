"""
Add credit_status column to invoices table.

Values: not_credited | partially_credited | fully_credited
Default: not_credited

Status is computed per invoice by summing line_total of all active
credit_note_items where cn_item.invoice_id = invoice.id.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS credit_status VARCHAR NOT NULL DEFAULT 'not_credited'
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS credit_status"))
