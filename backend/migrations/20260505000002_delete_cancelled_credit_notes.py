"""
Delete legacy cancelled credit notes.

This data cleanup migration removes soft-deleted credit notes that were marked
as status='cancelled' before the hard-delete cancellation behavior was adopted.

Because `credit_note_items` and `credit_note_invoice_refs` reference
`credit_notes` with ON DELETE CASCADE, dependent rows are removed automatically.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("DELETE FROM credit_notes WHERE status = 'cancelled'"))


def down(conn) -> None:
    # Irreversible data migration: deleted rows cannot be reconstructed.
    pass
