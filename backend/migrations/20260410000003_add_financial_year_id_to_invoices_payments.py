"""
Add financial_year_id FK to invoices and payments tables.
Existing rows remain NULL (backward compatible).
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS financial_year_id INTEGER
                REFERENCES financial_years(id)
    """))

    conn.execute(text("""
        ALTER TABLE payments
            ADD COLUMN IF NOT EXISTS financial_year_id INTEGER
                REFERENCES financial_years(id)
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS financial_year_id"))
    conn.execute(text("ALTER TABLE payments DROP COLUMN IF EXISTS financial_year_id"))
