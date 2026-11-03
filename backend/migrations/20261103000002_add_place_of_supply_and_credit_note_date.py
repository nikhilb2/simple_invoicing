"""
Add invoices.place_of_supply and credit_notes.credit_note_date.

The state of a sale decided nothing but the buyer's GSTIN, so a sale to an
unregistered buyer in another state was booked as CGST/SGST at the seller's own
state and filed that way in GSTR-1. place_of_supply stays NULL on existing rows:
their tax is already charged, and NULL keeps reading them the way they were
written.

A credit note had only created_at, a UTC timestamp, so it could not be backdated
and one issued just after midnight IST was filed on the previous day. The
backfill gives each note its issue date in IST.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS place_of_supply VARCHAR(2)
    """))
    conn.execute(text("""
        ALTER TABLE credit_notes
        ADD COLUMN IF NOT EXISTS credit_note_date TIMESTAMP
    """))
    # created_at is TIMESTAMPTZ NOT NULL where the migrations built the table, and
    # a nullable naive UTC TIMESTAMP where the models did. Pin it to an instant
    # first, so the day doesn't depend on the session's time zone.
    created_at_type = conn.execute(text("""
        SELECT data_type FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'credit_notes' AND column_name = 'created_at'
    """)).scalar()
    created_at = "created_at" if created_at_type == "timestamp with time zone" else "created_at AT TIME ZONE 'UTC'"
    conn.execute(text(f"""
        UPDATE credit_notes
        SET credit_note_date = date_trunc('day', COALESCE({created_at}, now()) AT TIME ZONE 'Asia/Kolkata')
        WHERE credit_note_date IS NULL
    """))
    # The previous image inserts without this column, so a rolling deploy or a
    # rollback must still be able to write a note.
    conn.execute(text("""
        ALTER TABLE credit_notes
        ALTER COLUMN credit_note_date SET DEFAULT date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata')
    """))
    conn.execute(text("""
        ALTER TABLE credit_notes
        ALTER COLUMN credit_note_date SET NOT NULL
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_credit_notes_credit_note_date
        ON credit_notes (credit_note_date)
    """))


def down(conn) -> None:
    conn.execute(text("""
        DROP INDEX IF EXISTS ix_credit_notes_credit_note_date
    """))
    conn.execute(text("""
        ALTER TABLE credit_notes
        DROP COLUMN IF EXISTS credit_note_date
    """))
    conn.execute(text("""
        ALTER TABLE invoices
        DROP COLUMN IF EXISTS place_of_supply
    """))
