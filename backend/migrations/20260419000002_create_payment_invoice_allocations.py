"""Create payment_invoice_allocations table for invoice-level receipt/payment allocations."""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS payment_invoice_allocations (
            id SERIAL PRIMARY KEY,
            payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            allocated_amount NUMERIC(10, 2) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(payment_id, invoice_id)
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_payment_invoice_allocations_payment_id
        ON payment_invoice_allocations(payment_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_payment_invoice_allocations_invoice_id
        ON payment_invoice_allocations(invoice_id)
    """))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ix_payment_invoice_allocations_invoice_id"))
    conn.execute(text("DROP INDEX IF EXISTS ix_payment_invoice_allocations_payment_id"))
    conn.execute(text("DROP TABLE IF EXISTS payment_invoice_allocations"))