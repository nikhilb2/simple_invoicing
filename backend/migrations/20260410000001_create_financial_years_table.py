"""
Create financial_years table and seed default FY 2025-26.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS financial_years (
            id         SERIAL PRIMARY KEY,
            label      VARCHAR NOT NULL,
            start_date DATE NOT NULL,
            end_date   DATE NOT NULL,
            is_active  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # Seed default FY 2025-26 if table is empty
    conn.execute(text("""
        INSERT INTO financial_years (label, start_date, end_date, is_active)
        SELECT '2025-26', '2025-04-01', '2026-03-31', TRUE
        WHERE NOT EXISTS (SELECT 1 FROM financial_years)
    """))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS financial_years"))
