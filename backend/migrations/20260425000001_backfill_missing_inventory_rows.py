"""Backfill zero-quantity inventory rows for products missing inventory."""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        INSERT INTO inventory (company_id, product_id, quantity)
        SELECT p.company_id, p.id, 0
        FROM products p
        LEFT JOIN inventory i
          ON i.product_id = p.id
         AND (
              i.company_id = p.company_id
              OR (i.company_id IS NULL AND p.company_id IS NULL)
         )
        WHERE i.id IS NULL
    """))


def down(conn) -> None:
    """No-op: this data backfill is intentionally not reversed automatically."""
    pass