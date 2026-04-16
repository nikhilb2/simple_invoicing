"""
Add item-level GST split fields to invoice_items
"""

from sqlalchemy import text


def up(conn) -> None:
    columns = {
        "cgst_amount": "ALTER TABLE invoice_items ADD COLUMN cgst_amount NUMERIC(10,2) NOT NULL DEFAULT 0",
        "sgst_amount": "ALTER TABLE invoice_items ADD COLUMN sgst_amount NUMERIC(10,2) NOT NULL DEFAULT 0",
        "igst_amount": "ALTER TABLE invoice_items ADD COLUMN igst_amount NUMERIC(10,2) NOT NULL DEFAULT 0",
    }

    existing = {
        row[0]
        for row in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'invoice_items'")
        ).fetchall()
    }

    for name, stmt in columns.items():
        if name not in existing:
            conn.execute(text(stmt))


def down(conn) -> None:
    for col in ["cgst_amount", "sgst_amount", "igst_amount"]:
        conn.execute(text(f"ALTER TABLE invoice_items DROP COLUMN IF EXISTS {col}"))