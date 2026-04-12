"""
Seed credit_note series rows for all existing financial years that don't already
have one, so CN numbering can be configured without manual DB fixes.

Copies format settings (prefix, suffix, year_format, etc.) from the existing
'sales' series of the same FY where available, then applies CN-specific defaults.
"""

from sqlalchemy import text


def up(conn) -> None:
    # Find all FY IDs that already have a credit_note series row
    existing = {
        row[0]
        for row in conn.execute(
            text("SELECT financial_year_id FROM invoice_series WHERE voucher_type = 'credit_note'")
        ).fetchall()
    }

    # For each FY, copy settings from its sales series (or use defaults)
    fy_rows = conn.execute(text("SELECT id FROM financial_years ORDER BY id")).fetchall()

    for (fy_id,) in fy_rows:
        if fy_id in existing:
            continue

        sales_row = conn.execute(
            text("""
                SELECT prefix, suffix, include_year, year_format, separator, pad_digits
                  FROM invoice_series
                 WHERE voucher_type = 'sales' AND financial_year_id = :fy_id
                 LIMIT 1
            """),
            {"fy_id": fy_id},
        ).fetchone()

        if sales_row:
            prefix, suffix, include_year, year_format, separator, pad_digits = sales_row
        else:
            prefix, suffix, include_year, year_format, separator, pad_digits = (
                "INV", "", True, "YYYY", "-", 3,
            )

        conn.execute(
            text("""
                INSERT INTO invoice_series
                    (voucher_type, financial_year_id, prefix, suffix,
                     include_year, year_format, separator, next_sequence, pad_digits)
                VALUES
                    ('credit_note', :fy_id, :prefix, :suffix,
                     :include_year, :year_format, :separator, 1, :pad_digits)
            """),
            {
                "fy_id": fy_id,
                "prefix": "CN",
                "suffix": suffix,
                "include_year": include_year,
                "year_format": year_format,
                "separator": separator,
                "pad_digits": pad_digits,
            },
        )

    # Also handle the NULL-FY fallback row (legacy environments)
    has_null_fy = conn.execute(
        text("SELECT 1 FROM invoice_series WHERE voucher_type = 'credit_note' AND financial_year_id IS NULL LIMIT 1")
    ).fetchone()

    if not has_null_fy:
        conn.execute(text("""
            INSERT INTO invoice_series
                (voucher_type, financial_year_id, prefix, suffix,
                 include_year, year_format, separator, next_sequence, pad_digits)
            VALUES
                ('credit_note', NULL, 'CN', '', TRUE, 'YYYY', '-', 1, 3)
        """))


def down(conn) -> None:
    conn.execute(text("DELETE FROM invoice_series WHERE voucher_type = 'credit_note'"))
