"""
Create payments table for tracking receipt/payment vouchers against ledgers.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            buyer_id INTEGER NOT NULL REFERENCES buyers(id),
            voucher_type VARCHAR NOT NULL,
            amount NUMERIC(10, 2) NOT NULL,
            date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            mode VARCHAR,
            reference VARCHAR,
            notes VARCHAR,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_buyer_id ON payments (buyer_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_date ON payments (date)"))
