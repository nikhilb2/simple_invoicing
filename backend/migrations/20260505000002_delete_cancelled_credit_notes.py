"""
Delete legacy cancelled credit notes.

This data cleanup migration removes soft-deleted credit notes that were marked
as status='cancelled' before the hard-delete cancellation behavior was adopted.

Some environments may have non-cascading foreign keys, so dependent rows are
removed explicitly before deleting from `credit_notes`.
"""

from sqlalchemy import text


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = :table"),
        {"table": table},
    ).fetchone()
    return row is not None


def up(conn) -> None:
    if not _table_exists(conn, "credit_notes"):
        return

    if _table_exists(conn, "credit_note_invoice_refs"):
        conn.execute(text("""
            DELETE FROM credit_note_invoice_refs
            WHERE credit_note_id IN (
                SELECT id FROM credit_notes WHERE status = 'cancelled'
            )
        """))

    if _table_exists(conn, "credit_note_items"):
        conn.execute(text("""
            DELETE FROM credit_note_items
            WHERE credit_note_id IN (
                SELECT id FROM credit_notes WHERE status = 'cancelled'
            )
        """))

    conn.execute(text("DELETE FROM credit_notes WHERE status = 'cancelled'"))


def down(conn) -> None:
    # Irreversible data migration: deleted rows cannot be reconstructed.
    pass
