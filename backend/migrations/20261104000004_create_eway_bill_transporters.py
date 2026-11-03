"""
Create eway_bill_transporters table for saved transporter profiles
used in E-Way Bill JSON generation.

The table is company-scoped, so it is listed in src/db/rls.py. Applying the
policy here rather than leaving it to the next boot means the table never exists
on a shared-hosting database without one, however the migration was run. The
grants come from ALTER DEFAULT PRIVILEGES (see 20261030000030), and the boot
check refuses to start if they are missing.
"""

from sqlalchemy import text

from src.core.config import settings
from src.db.rls import ensure_row_level_security


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS eway_bill_transporters (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
            transporter_name VARCHAR(255) NOT NULL,
            transporter_gstin VARCHAR(15),
            transport_mode VARCHAR(20) NOT NULL DEFAULT '1',
            vehicle_type VARCHAR(10) NOT NULL DEFAULT 'R',
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_eway_bill_transporters_company
        ON eway_bill_transporters(company_id)
    """))

    if settings.is_shared_hosting:
        ensure_row_level_security(conn)


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS eway_bill_transporters"))
