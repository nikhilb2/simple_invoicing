"""
Allow payments without ledger linkage for account-only cash/bank entries.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE payments
        ALTER COLUMN buyer_id DROP NOT NULL
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE payments
        ALTER COLUMN buyer_id SET NOT NULL
    """))
