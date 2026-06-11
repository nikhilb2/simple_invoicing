"""
Add company logo, additional info, and terms fields to invoices for PDF rendering.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS company_logo_data TEXT"))
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS company_logo_mime_type VARCHAR(50)"))
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS company_additional_info TEXT"))
    conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS company_terms_text TEXT"))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS company_logo_data"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS company_logo_mime_type"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS company_additional_info"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS company_terms_text"))
