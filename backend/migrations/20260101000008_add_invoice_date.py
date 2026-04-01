"""
Add invoice_date column to invoices table for backdated invoice creation.
Defaults to created_at for existing rows and NOW() for new rows.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS invoice_date TIMESTAMPTZ"
    ))
    # Back-fill existing rows so invoice_date = created_at
    conn.execute(text(
        "UPDATE invoices SET invoice_date = created_at WHERE invoice_date IS NULL"
    ))
    # Make the column NOT NULL with a default for future inserts
    conn.execute(text(
        "ALTER TABLE invoices ALTER COLUMN invoice_date SET NOT NULL"
    ))
    conn.execute(text(
        "ALTER TABLE invoices ALTER COLUMN invoice_date SET DEFAULT NOW()"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_invoices_invoice_date ON invoices (invoice_date)"
    ))
