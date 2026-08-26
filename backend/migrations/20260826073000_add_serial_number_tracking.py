"""
add_serial_number_tracking

IF NOT EXISTS throughout: app_main.py runs Base.metadata.create_all() before the
migration runner, so on a fresh database the column, table and indexes already
exist by the time this runs.
"""

from sqlalchemy import text


def up(conn) -> None:
    """Apply migration."""
    conn.execute(text(
        "ALTER TABLE products "
        "ADD COLUMN IF NOT EXISTS track_serials BOOLEAN NOT NULL DEFAULT FALSE"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS product_serials (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            serial_number VARCHAR(64) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'in_stock',
            purchase_invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
            sales_invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # Case-insensitive uniqueness per tenant; voided rows are excluded so a
    # wrongly-entered IMEI can be re-registered after the purchase is cancelled.
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_product_serials_company_number "
        "ON product_serials (company_id, upper(serial_number)) "
        "WHERE status <> 'void'"
    ))
    # The picker's and the stock-count's only query shape.
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_product_serials_product_status "
        "ON product_serials (company_id, product_id, status)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_product_serials_sales_invoice "
        "ON product_serials (sales_invoice_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_product_serials_purchase_invoice "
        "ON product_serials (purchase_invoice_id)"
    ))


def down(conn) -> None:
    """Reverse migration."""
    conn.execute(text("DROP TABLE IF EXISTS product_serials"))
    conn.execute(text("ALTER TABLE products DROP COLUMN IF EXISTS track_serials"))
