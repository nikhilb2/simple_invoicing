"""Tell an outward credit note from one received from a supplier.

Under s.34 CGST the supplier issues the credit note; the recipient files
nothing and simply reverses the input tax it claimed. So a note raised against
a purchase invoice is the supplier's document recorded on our side, and the
number and date that reconcile it against GSTR-2B are theirs, not ours.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE credit_notes
            ADD COLUMN IF NOT EXISTS direction VARCHAR(10) NOT NULL DEFAULT 'outward'
    """))
    # app_main runs create_all() before the migration runner, so on a fresh
    # database the column already exists without the server default above and
    # the ADD COLUMN is a no-op. Nothing issued so far was ever inward.
    conn.execute(text("UPDATE credit_notes SET direction = 'outward' WHERE direction IS NULL"))

    conn.execute(text("""
        ALTER TABLE credit_notes
            ADD COLUMN IF NOT EXISTS supplier_credit_note_number VARCHAR(64)
    """))
    conn.execute(text("""
        ALTER TABLE credit_notes
            ADD COLUMN IF NOT EXISTS supplier_credit_note_date DATE
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_credit_notes_direction ON credit_notes(direction)"
    ))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ix_credit_notes_direction"))
    conn.execute(text("ALTER TABLE credit_notes DROP COLUMN IF EXISTS supplier_credit_note_date"))
    conn.execute(text("ALTER TABLE credit_notes DROP COLUMN IF EXISTS supplier_credit_note_number"))
    conn.execute(text("ALTER TABLE credit_notes DROP COLUMN IF EXISTS direction"))
