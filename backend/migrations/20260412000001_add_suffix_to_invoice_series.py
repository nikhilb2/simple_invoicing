"""
Add suffix support to invoice_series.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE invoice_series
            ADD COLUMN IF NOT EXISTS suffix VARCHAR NOT NULL DEFAULT ''
    """))

    conn.execute(text("""
        UPDATE invoice_series
           SET suffix = ''
         WHERE suffix IS NULL
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoice_series DROP COLUMN IF EXISTS suffix"))