"""
Create invoice_series table with default seeds, add series_id FK to invoices,
and add series_id + payment_number to payments.
"""

from sqlalchemy import text


def up(conn) -> None:
    # Create invoice_series table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS invoice_series (
            id           SERIAL PRIMARY KEY,
            voucher_type VARCHAR NOT NULL,
            prefix       VARCHAR NOT NULL,
            include_year BOOLEAN DEFAULT TRUE,
            year_format  VARCHAR DEFAULT 'YYYY',
            separator    VARCHAR DEFAULT '-',
            next_sequence INTEGER DEFAULT 1,
            pad_digits   INTEGER DEFAULT 3,
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    # Seed defaults (skip if already present)
    conn.execute(text("""
        INSERT INTO invoice_series (voucher_type, prefix)
        SELECT voucher_type, prefix FROM (VALUES
            ('sales',    'INV'),
            ('purchase', 'PINV'),
            ('payment',  'PAY')
        ) AS seeds(voucher_type, prefix)
        WHERE NOT EXISTS (
            SELECT 1 FROM invoice_series WHERE voucher_type = seeds.voucher_type
        )
    """))

    # Add series_id FK to invoices
    conn.execute(text("""
        ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS series_id INTEGER REFERENCES invoice_series(id)
    """))

    # Add series_id + payment_number to payments
    conn.execute(text("""
        ALTER TABLE payments
            ADD COLUMN IF NOT EXISTS series_id INTEGER REFERENCES invoice_series(id)
    """))
    conn.execute(text("""
        ALTER TABLE payments
            ADD COLUMN IF NOT EXISTS payment_number VARCHAR
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE payments DROP COLUMN IF EXISTS payment_number"))
    conn.execute(text("ALTER TABLE payments DROP COLUMN IF EXISTS series_id"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS series_id"))
    conn.execute(text("DROP TABLE IF EXISTS invoice_series"))
