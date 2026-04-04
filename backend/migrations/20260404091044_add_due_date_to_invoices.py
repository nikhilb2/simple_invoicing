"""
add_due_date_to_invoices
"""

from sqlalchemy import text


def up(conn) -> None:
    """Apply migration."""
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS due_date TIMESTAMPTZ"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_due_date ON invoices (due_date)"))


def down(conn) -> None:
    """Reverse migration."""
    conn.execute(text("DROP INDEX IF EXISTS ix_invoices_due_date"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS due_date"))
