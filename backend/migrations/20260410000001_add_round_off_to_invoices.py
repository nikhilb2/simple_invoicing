"""
Add round-off fields to invoices.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS apply_round_off BOOLEAN NOT NULL DEFAULT FALSE;
    """))
    conn.execute(text("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS round_off_amount NUMERIC(5,2) NOT NULL DEFAULT 0;
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS round_off_amount"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS apply_round_off"))
