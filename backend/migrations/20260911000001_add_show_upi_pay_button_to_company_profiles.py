"""
Add show_upi_pay_button flag to company_profiles.

Off by default. The share page always offers a UPI QR; this adds a tappable
"Pay by UPI" button beside it. An unsigned upi:// hand-off to a personal address
draws a risk warning in Paytm, so the button is only worth showing when the
company's UPI ID is a registered merchant address -- and only the owner knows
which kind of address they entered.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        ADD COLUMN IF NOT EXISTS show_upi_pay_button BOOLEAN NOT NULL DEFAULT FALSE
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        DROP COLUMN IF EXISTS show_upi_pay_button
    """))
