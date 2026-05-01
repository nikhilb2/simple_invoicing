"""
Add product unit and allow_decimal fields, and make inventory quantity decimal-capable.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS unit VARCHAR NOT NULL DEFAULT 'Pieces';
    """))

    conn.execute(text("""
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS allow_decimal BOOLEAN NOT NULL DEFAULT FALSE;
    """))

    conn.execute(text("""
        UPDATE products
        SET unit = 'Pieces'
        WHERE unit IS NULL OR btrim(unit) = '';
    """))

    conn.execute(text("""
        ALTER TABLE inventory
        ALTER COLUMN quantity TYPE NUMERIC(12, 3)
        USING quantity::numeric;
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE inventory
        ALTER COLUMN quantity TYPE INTEGER
        USING ROUND(quantity)::integer;
    """))

    conn.execute(text("ALTER TABLE products DROP COLUMN IF EXISTS allow_decimal"))
    conn.execute(text("ALTER TABLE products DROP COLUMN IF EXISTS unit"))
