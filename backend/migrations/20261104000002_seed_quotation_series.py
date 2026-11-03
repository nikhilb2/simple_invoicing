"""
Seed a quotation (QT) and a proforma (PI) number series for every financial year.

Separate counters: a quotation must never use up a number in the sales series, which
feeds GSTR-1 Table 13. The format follows the same year's sales series, so numbers
look alike across a company; the prefix stays editable like the rest.

New companies and new financial years get theirs from DEFAULT_SERIES_CONFIGS.
"""

from sqlalchemy import text

PREFIXES = {"quotation": "QT", "proforma": "PI"}


def up(conn) -> None:
    fy_rows = conn.execute(text("SELECT id, company_id FROM financial_years ORDER BY id")).fetchall()

    for fy_id, fy_company_id in fy_rows:
        source = conn.execute(
            text("""
                SELECT suffix, include_year, year_format, separator, pad_digits, company_id
                  FROM invoice_series
                 WHERE voucher_type = 'sales' AND financial_year_id = :fy_id
                 LIMIT 1
            """),
            {"fy_id": fy_id},
        ).fetchone()
        suffix, include_year, year_format, separator, pad_digits, source_company_id = source or (
            "", True, "YYYY", "-", 3, None,
        )
        company_id = fy_company_id if fy_company_id is not None else source_company_id

        for voucher_type, prefix in PREFIXES.items():
            exists = conn.execute(
                text("""
                    SELECT 1 FROM invoice_series
                     WHERE voucher_type = :voucher_type
                       AND financial_year_id = :fy_id
                       AND company_id IS NOT DISTINCT FROM :company_id
                     LIMIT 1
                """),
                {"voucher_type": voucher_type, "fy_id": fy_id, "company_id": company_id},
            ).fetchone()
            if exists:
                continue
            conn.execute(
                text("""
                    INSERT INTO invoice_series
                        (voucher_type, financial_year_id, company_id, prefix, suffix,
                         include_year, year_format, separator, next_sequence, pad_digits)
                    VALUES
                        (:voucher_type, :fy_id, :company_id, :prefix, :suffix,
                         :include_year, :year_format, :separator, 1, :pad_digits)
                """),
                {
                    "voucher_type": voucher_type,
                    "fy_id": fy_id,
                    "company_id": company_id,
                    "prefix": prefix,
                    "suffix": suffix if suffix is not None else "",
                    "include_year": include_year,
                    "year_format": year_format,
                    "separator": separator,
                    "pad_digits": pad_digits,
                },
            )


def down(conn) -> None:
    conn.execute(text("DELETE FROM invoice_series WHERE voucher_type IN ('quotation', 'proforma')"))
