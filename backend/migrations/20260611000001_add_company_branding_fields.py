"""Add terms_and_conditions, logo_path, and additional_company_info to company_profiles.

Adds:
  - terms_and_conditions (JSONB) — user-defined T&C as ordered list
  - logo_path (VARCHAR(512)) — path to uploaded company logo
  - additional_company_info (TEXT) — multi-line header text for PDFs
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS terms_and_conditions JSONB DEFAULT '[]'::jsonb"))
    conn.execute(text("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS logo_path VARCHAR(512)"))
    conn.execute(text("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS additional_company_info TEXT"))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS terms_and_conditions"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS logo_path"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS additional_company_info"))
