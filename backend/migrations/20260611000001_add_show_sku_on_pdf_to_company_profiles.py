"""
add_show_sku_on_pdf_to_company_profiles
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        ADD COLUMN IF NOT EXISTS show_sku_on_pdf BOOLEAN NOT NULL DEFAULT FALSE
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        DROP COLUMN IF EXISTS show_sku_on_pdf
    """))
