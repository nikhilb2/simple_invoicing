"""Add discount_type and discount_value fields to invoices and invoice_items tables."""

from src.db.base import Base
from src.db.session import engine


def upgrade():
    """Add discount columns to invoices and invoice_items."""
    with engine.connect() as conn:
        conn.execute(
            Base.metadata.tables["invoices"].table_valued()
        )
    # SQLite-safe: use ALTER TABLE via raw connection
    # The migration system uses raw SQL
    import sqlite3
    # Detect db URL
    db_url = str(engine.url)
    if "sqlite" in db_url:
        # SQLite path
        sqlite_path = db_url.replace("sqlite:///", "")
        if sqlite_path.startswith("./"):
            sqlite_path = sqlite_path[2:]
        conn = sqlite3.connect(sqlite_path)
        cur = conn.cursor()
        # Add to invoices
        try:
            cur.execute("ALTER TABLE invoices ADD COLUMN discount_type VARCHAR(20)")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            cur.execute("ALTER TABLE invoices ADD COLUMN discount_value NUMERIC(10,2)")
        except sqlite3.OperationalError:
            pass
        # Add to invoice_items
        try:
            cur.execute("ALTER TABLE invoice_items ADD COLUMN discount_type VARCHAR(20)")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE invoice_items ADD COLUMN discount_value NUMERIC(10,2)")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()
    else:
        # PostgreSQL path
        conn = engine.raw_connection()
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS discount_type VARCHAR(20)")
        except Exception:
            conn.rollback()
        try:
            cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS discount_value NUMERIC(10,2)")
        except Exception:
            conn.rollback()
        try:
            cur.execute("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS discount_type VARCHAR(20)")
        except Exception:
            conn.rollback()
        try:
            cur.execute("ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS discount_value NUMERIC(10,2)")
        except Exception:
            conn.rollback()
        conn.commit()
        conn.close()


def downgrade():
    """Remove discount columns."""
    db_url = str(engine.url)
    if "sqlite" in db_url:
        sqlite_path = db_url.replace("sqlite:///", "")
        if sqlite_path.startswith("./"):
            sqlite_path = sqlite_path[2:]
        conn = sqlite3.connect(sqlite_path)
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE invoices DROP COLUMN discount_type")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE invoices DROP COLUMN discount_value")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE invoice_items DROP COLUMN discount_type")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE invoice_items DROP COLUMN discount_value")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()
    else:
        conn = engine.raw_connection()
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS discount_type")
        except Exception:
            conn.rollback()
        try:
            cur.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS discount_value")
        except Exception:
            conn.rollback()
        try:
            cur.execute("ALTER TABLE invoice_items DROP COLUMN IF EXISTS discount_type")
        except Exception:
            conn.rollback()
        try:
            cur.execute("ALTER TABLE invoice_items DROP COLUMN IF EXISTS discount_value")
        except Exception:
            conn.rollback()
        conn.commit()
        conn.close()


if __name__ == "__main__":
    upgrade()
