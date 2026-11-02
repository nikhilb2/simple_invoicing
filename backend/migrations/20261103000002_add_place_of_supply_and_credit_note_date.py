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
    conn.execute(text("""
        UPDATE credit_notes
        SET credit_note_date = date_trunc('day', created_at + INTERVAL '5 hours 30 minutes')
        WHERE credit_note_date IS NULL
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
