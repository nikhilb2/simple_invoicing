"""Add created_at timestamp to products table."""

from sqlalchemy import text


def up(conn) -> None:
    existing = {
        row[0]
        for row in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'products'")
        ).fetchall()
    }
    if "created_at" not in existing:
        conn.execute(text(
            "ALTER TABLE products ADD COLUMN created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"
        ))
    conn.execute(text(
        "UPDATE products SET created_at = NOW() WHERE created_at IS NULL"
    ))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE products DROP COLUMN IF EXISTS created_at"))
