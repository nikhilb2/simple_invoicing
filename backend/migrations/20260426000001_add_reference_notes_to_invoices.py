"""
Add reference_notes field to invoices.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoices ADD COLUMN IF NOT EXISTS reference_notes VARCHAR(255);
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS reference_notes"))
