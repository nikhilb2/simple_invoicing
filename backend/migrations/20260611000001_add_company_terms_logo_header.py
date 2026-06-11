"""
Add company terms & conditions, logo upload, and additional header info support.
Creates company_terms table and adds columns to company_profiles.
"""

from sqlalchemy import text


def up(conn) -> None:
    # Terms & Conditions table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS company_terms (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            serial_number INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    # Logo and additional header info on company_profiles
    conn.execute(text("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS logo_data TEXT"))
    conn.execute(text("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS logo_mime_type VARCHAR(50)"))
    conn.execute(text("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS additional_company_info TEXT"))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS company_terms"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS logo_data"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS logo_mime_type"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS additional_company_info"))
