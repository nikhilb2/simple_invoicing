"""
Create ledger_addresses table for storing multiple named shipping/delivery
addresses per ledger (buyer), scoped to a company.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS ledger_addresses (
            id          SERIAL PRIMARY KEY,
            ledger_id   INTEGER NOT NULL REFERENCES buyers(id) ON DELETE CASCADE,
            company_id  INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            label       VARCHAR(255) NOT NULL,
            address     TEXT NOT NULL,
            is_default  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ledger_addresses_ledger_id
        ON ledger_addresses(ledger_id);
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_ledger_addresses_company_id
        ON ledger_addresses(company_id);
    """))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS ledger_addresses;"))
