"""Scope buyer GST uniqueness to company.

Drops legacy global unique index on buyers.gst and replaces it with
company-scoped unique index.
"""

from sqlalchemy import text


def up(conn) -> None:
    # Remove old global uniqueness on GST, if present.
    conn.execute(text("DROP INDEX IF EXISTS ix_buyers_gst"))
    conn.execute(text("ALTER TABLE buyers DROP CONSTRAINT IF EXISTS buyers_gst_key"))

    # Ensure company-scoped uniqueness for non-null GST values.
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_buyers_company_id_gst
        ON buyers(company_id, gst)
        WHERE gst IS NOT NULL
    """))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ux_buyers_company_id_gst"))

    # Restore legacy global uniqueness behavior.
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_buyers_gst ON buyers(gst)"))
