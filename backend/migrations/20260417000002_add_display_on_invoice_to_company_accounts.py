"""
Add display_on_invoice flag to company_accounts.

Bank accounts can be toggled for invoice PDF visibility.
Cash accounts are always hidden on invoice PDFs.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_accounts
        ADD COLUMN IF NOT EXISTS display_on_invoice BOOLEAN NOT NULL DEFAULT TRUE
    """))

    # Ensure cash accounts are not rendered in invoice payment details.
    conn.execute(text("""
        UPDATE company_accounts
        SET display_on_invoice = FALSE
        WHERE account_type = 'cash'
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_accounts
        DROP COLUMN IF EXISTS display_on_invoice
    """))
