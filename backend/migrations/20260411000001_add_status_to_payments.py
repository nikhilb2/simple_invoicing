"""
Add status column to payments (active | cancelled) for soft delete support.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE payments ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'active';
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
    """))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS idx_payments_status"))
    conn.execute(text("ALTER TABLE payments DROP COLUMN IF EXISTS status"))
