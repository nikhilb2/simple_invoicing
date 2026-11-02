"""Seed a debit_note series so notes received from suppliers get their own numbers.

The supplier's own number cannot be the primary one: credit_note_number is
globally unique, and two suppliers routinely both issue "CN-001". An internal
DN- number keeps the audit trail while the supplier's number is stored
alongside it for GSTR-2B matching.

A separate series also keeps the outward one contiguous. GSTR-1 Table 13
declares a credit note series as a from/to range with a count, so numbers spent
on documents we never issued would make that range wrong.
"""

from sqlalchemy import text


def up(conn) -> None:
    existing = {
        row[0]
        for row in conn.execute(
            text("SELECT financial_year_id FROM invoice_series WHERE voucher_type = 'debit_note'")
        ).fetchall()
    }

    fy_rows = conn.execute(text("SELECT id, company_id FROM financial_years ORDER BY id")).fetchall()

    for fy_id, fy_company_id in fy_rows:
        if fy_id in existing:
            continue

        # Copy the format from the credit note series of the same FY — the
        # closest sibling — and fall back to sales, then to defaults.
        source_row = conn.execute(
            text("""
                SELECT suffix, include_year, year_format, separator, pad_digits, company_id
                  FROM invoice_series
                 WHERE voucher_type IN ('credit_note', 'sales')
                   AND financial_year_id = :fy_id
                 ORDER BY CASE voucher_type WHEN 'credit_note' THEN 0 ELSE 1 END
                 LIMIT 1
            """),
            {"fy_id": fy_id},
        ).fetchone()

        if source_row:
            suffix, include_year, year_format, separator, pad_digits, source_company_id = source_row
        else:
            suffix, include_year, year_format, separator, pad_digits, source_company_id = (
                "", True, "YYYY", "-", 3, None,
            )

        conn.execute(
            text("""
                INSERT INTO invoice_series
                    (voucher_type, financial_year_id, company_id, prefix, suffix,
                     include_year, year_format, separator, next_sequence, pad_digits)
                VALUES
                    ('debit_note', :fy_id, :company_id, 'DN', :suffix,
                     :include_year, :year_format, :separator, 1, :pad_digits)
            """),
            {
                "fy_id": fy_id,
                "company_id": fy_company_id if fy_company_id is not None else source_company_id,
                "suffix": suffix if suffix is not None else "",
                "include_year": include_year,
                "year_format": year_format,
                "separator": separator,
                "pad_digits": pad_digits,
            },
        )

    # The NULL-FY fallback row that legacy environments number against.
    has_null_fy = conn.execute(
        text("SELECT 1 FROM invoice_series WHERE voucher_type = 'debit_note' AND financial_year_id IS NULL LIMIT 1")
    ).fetchone()

    if not has_null_fy:
        conn.execute(text("""
            INSERT INTO invoice_series
                (voucher_type, financial_year_id, prefix, suffix,
                 include_year, year_format, separator, next_sequence, pad_digits)
            VALUES
                ('debit_note', NULL, 'DN', '', TRUE, 'YYYY', '-', 1, 3)
        """))


def down(conn) -> None:
    conn.execute(text("DELETE FROM invoice_series WHERE voucher_type = 'debit_note'"))
