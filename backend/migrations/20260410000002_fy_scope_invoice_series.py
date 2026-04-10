"""
Extend invoice_series with financial_year_id FK.
- Add financial_year_id INTEGER NULLABLE FK -> financial_years.id
- Drop old UNIQUE(voucher_type) constraint
- Add UNIQUE(voucher_type, financial_year_id) constraint
- Backfill existing rows to the default active FY (2025-26)
"""

from sqlalchemy import text


def up(conn) -> None:
    # Add financial_year_id column
    conn.execute(text("""
        ALTER TABLE invoice_series
            ADD COLUMN IF NOT EXISTS financial_year_id INTEGER
                REFERENCES financial_years(id)
    """))

    # Drop old unique constraint on voucher_type alone
    conn.execute(text("""
        ALTER TABLE invoice_series
            DROP CONSTRAINT IF EXISTS invoice_series_voucher_type_key
    """))

    # Add new unique constraint on (voucher_type, financial_year_id)
    conn.execute(text("""
        ALTER TABLE invoice_series
            ADD CONSTRAINT IF NOT EXISTS uq_invoice_series_voucher_fy
                UNIQUE (voucher_type, financial_year_id)
    """))

    # Backfill existing 3 rows to the active FY
    conn.execute(text("""
        UPDATE invoice_series
           SET financial_year_id = (
               SELECT id FROM financial_years WHERE is_active = TRUE LIMIT 1
           )
         WHERE financial_year_id IS NULL
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoice_series
            DROP CONSTRAINT IF EXISTS uq_invoice_series_voucher_fy
    """))
    conn.execute(text("""
        ALTER TABLE invoice_series
            DROP COLUMN IF EXISTS financial_year_id
    """))
    # Re-add the original unique constraint
    conn.execute(text("""
        ALTER TABLE invoice_series
            ADD CONSTRAINT invoice_series_voucher_type_key
                UNIQUE (voucher_type)
    """))
