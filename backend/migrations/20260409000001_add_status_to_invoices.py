"""
Add status column to invoices (active | cancelled).
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'active';
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
    """))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS idx_invoices_status"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS status"))
