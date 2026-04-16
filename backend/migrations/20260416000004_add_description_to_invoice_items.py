"""
Add description field to invoice_items for serial numbers and batch codes
"""

from sqlalchemy import text


def up(conn) -> None:
    stmt = "ALTER TABLE invoice_items ADD COLUMN description TEXT"
    
    existing = {
        row[0]
        for row in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'invoice_items'")
        ).fetchall()
    }
    
    if "description" not in existing:
        conn.execute(text(stmt))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoice_items DROP COLUMN IF EXISTS description"))
