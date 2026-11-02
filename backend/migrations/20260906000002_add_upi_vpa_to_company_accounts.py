"""
Add upi_vpa to company_accounts.

The UPI ID money should be collected into, stored next to the account's IFSC because
it identifies the same account. Visibility is governed by the existing
display_on_invoice flag, so this needs no toggle of its own -- a blank value is the
off switch. Cash accounts never carry one.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_accounts
        ADD COLUMN IF NOT EXISTS upi_vpa VARCHAR(64)
    """))

    conn.execute(text("""
        UPDATE company_accounts
        SET upi_vpa = NULL
        WHERE account_type = 'cash'
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_accounts
        DROP COLUMN IF EXISTS upi_vpa
    """))
