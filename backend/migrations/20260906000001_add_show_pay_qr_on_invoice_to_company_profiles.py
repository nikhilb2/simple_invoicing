"""
Add show_pay_qr_on_invoice flag to company_profiles.

Off by default, and deliberately so: turning it on makes every invoice PDF carry a
QR of that invoice's public share URL, which means printing an invoice starts
minting a publicly reachable link. That is a consent decision, not a default.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        ADD COLUMN IF NOT EXISTS show_pay_qr_on_invoice BOOLEAN NOT NULL DEFAULT FALSE
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        DROP COLUMN IF EXISTS show_pay_qr_on_invoice
    """))
