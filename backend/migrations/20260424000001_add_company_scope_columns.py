"""Add nullable company ownership columns to company-scoped tables."""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS active_company_id INTEGER
                REFERENCES company_profiles(id)
    """))

    conn.execute(text("""
        ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_company_id ON invoices(company_id)"))

    conn.execute(text("""
        ALTER TABLE company_accounts
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_company_accounts_company_id ON company_accounts(company_id)"))

    conn.execute(text("""
        ALTER TABLE buyers
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_buyers_company_id ON buyers(company_id)"))

    conn.execute(text("""
        ALTER TABLE products
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_products_company_id ON products(company_id)"))

    conn.execute(text("""
        ALTER TABLE inventory
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_inventory_company_id ON inventory(company_id)"))

    conn.execute(text("""
        ALTER TABLE payments
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_company_id ON payments(company_id)"))

    conn.execute(text("""
        ALTER TABLE credit_notes
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_credit_notes_company_id ON credit_notes(company_id)"))

    conn.execute(text("""
        ALTER TABLE credit_note_items
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_credit_note_items_company_id ON credit_note_items(company_id)"))

    conn.execute(text("""
        ALTER TABLE invoice_series
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoice_series_company_id ON invoice_series(company_id)"))

    conn.execute(text("""
        ALTER TABLE financial_years
            ADD COLUMN IF NOT EXISTS company_id INTEGER
                REFERENCES company_profiles(id)
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_financial_years_company_id ON financial_years(company_id)"))

    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_active_company_id ON users(active_company_id)"))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ix_users_active_company_id"))
    conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS active_company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_financial_years_company_id"))
    conn.execute(text("ALTER TABLE financial_years DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_invoice_series_company_id"))
    conn.execute(text("ALTER TABLE invoice_series DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_credit_note_items_company_id"))
    conn.execute(text("ALTER TABLE credit_note_items DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_credit_notes_company_id"))
    conn.execute(text("ALTER TABLE credit_notes DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_payments_company_id"))
    conn.execute(text("ALTER TABLE payments DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_inventory_company_id"))
    conn.execute(text("ALTER TABLE inventory DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_products_company_id"))
    conn.execute(text("ALTER TABLE products DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_buyers_company_id"))
    conn.execute(text("ALTER TABLE buyers DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_company_accounts_company_id"))
    conn.execute(text("ALTER TABLE company_accounts DROP COLUMN IF EXISTS company_id"))

    conn.execute(text("DROP INDEX IF EXISTS ix_invoices_company_id"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS company_id"))