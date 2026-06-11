"""Add discount_type and discount_value fields to invoices and invoice_items tables."""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS discount_type VARCHAR(20)"))
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS discount_value NUMERIC(10,2)"))
    conn.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS discount_type VARCHAR(20)"))
    conn.execute(text("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS discount_value NUMERIC(10,2)"))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS discount_type"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS discount_value"))
    conn.execute(text("ALTER TABLE invoice_items DROP COLUMN IF EXISTS discount_type"))
    conn.execute(text("ALTER TABLE invoice_items DROP COLUMN IF EXISTS discount_value"))
