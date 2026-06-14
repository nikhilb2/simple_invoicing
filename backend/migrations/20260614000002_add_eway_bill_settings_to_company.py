"""Add E-Way Bill configurable settings to company_profiles.

- eway_enabled: Enable/disable E-Way Bill module
- eway_local_threshold: Intra-state E-Way threshold amount
- eway_interstate_threshold: Inter-state E-Way threshold amount
- eway_always_show_button: Always show button regardless of threshold
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        ADD COLUMN IF NOT EXISTS eway_enabled BOOLEAN NOT NULL DEFAULT TRUE;
    """))
    conn.execute(text("""
        ALTER TABLE company_profiles
        ADD COLUMN IF NOT EXISTS eway_local_threshold DOUBLE PRECISION NOT NULL DEFAULT 100000;
    """))
    conn.execute(text("""
        ALTER TABLE company_profiles
        ADD COLUMN IF NOT EXISTS eway_interstate_threshold DOUBLE PRECISION NOT NULL DEFAULT 50000;
    """))
    conn.execute(text("""
        ALTER TABLE company_profiles
        ADD COLUMN IF NOT EXISTS eway_always_show_button BOOLEAN NOT NULL DEFAULT TRUE;
    """))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS eway_always_show_button;"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS eway_interstate_threshold;"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS eway_local_threshold;"))
    conn.execute(text("ALTER TABLE company_profiles DROP COLUMN IF EXISTS eway_enabled;"))
