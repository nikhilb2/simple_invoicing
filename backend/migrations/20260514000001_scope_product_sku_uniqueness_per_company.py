"""Scope product SKU uniqueness to company.

Drops the legacy global unique index on products.sku and replaces it with
a company-scoped composite unique index, allowing the same SKU to exist
across different companies.
"""

from sqlalchemy import text


def up(conn) -> None:
    # Remove old global uniqueness on SKU.
    conn.execute(text("DROP INDEX IF EXISTS ix_products_sku"))
    conn.execute(text("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_sku_key"))

    # Ensure company-scoped uniqueness for SKUs.
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_products_company_id_sku
        ON products(company_id, sku)
    """))


def down(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ux_products_company_id_sku"))

    # Restore legacy global uniqueness behaviour.
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_products_sku ON products(sku)"))
