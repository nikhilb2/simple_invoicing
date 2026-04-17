"""
Create company_accounts table and link optional account_id on payments.

Existing payments remain unallocated (NULL account_id).
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS company_accounts (
            id SERIAL PRIMARY KEY,
            account_type VARCHAR(16) NOT NULL DEFAULT 'bank',
            display_name VARCHAR(120) NOT NULL,
            bank_name VARCHAR,
            branch_name VARCHAR,
            account_name VARCHAR,
            account_number VARCHAR,
            ifsc_code VARCHAR,
            opening_balance NUMERIC(12, 2) NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_company_accounts_display_name
        ON company_accounts(display_name)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_company_accounts_is_active
        ON company_accounts(is_active)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_company_accounts_account_type
        ON company_accounts(account_type)
    """))

    conn.execute(text("""
        ALTER TABLE payments
        ADD COLUMN IF NOT EXISTS account_id INTEGER
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_payments_account_id
        ON payments(account_id)
    """))
    conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_payments_account_id'
            ) THEN
                ALTER TABLE payments
                ADD CONSTRAINT fk_payments_account_id
                FOREIGN KEY (account_id)
                REFERENCES company_accounts(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE payments
        DROP CONSTRAINT IF EXISTS fk_payments_account_id
    """))
    conn.execute(text("DROP INDEX IF EXISTS idx_payments_account_id"))
    conn.execute(text("""
        ALTER TABLE payments
        DROP COLUMN IF EXISTS account_id
    """))

    conn.execute(text("DROP INDEX IF EXISTS idx_company_accounts_account_type"))
    conn.execute(text("DROP INDEX IF EXISTS idx_company_accounts_is_active"))
    conn.execute(text("DROP INDEX IF EXISTS idx_company_accounts_display_name"))
    conn.execute(text("DROP TABLE IF EXISTS company_accounts"))
