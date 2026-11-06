"""Initialize the current financial year for an unused single-tenant install."""

from datetime import date

from sqlalchemy import text

from src.core.config import settings
from src.services.gst_tax_service import india_today


def up(conn) -> None:
    if settings.is_shared_hosting:
        return

    today = india_today()
    # Match only the legacy bootstrap state. Never change a configured company,
    # an installation that has invoiced, or a manually created financial year.
    bootstrap_year = conn.execute(text("""
        SELECT fy.id, fy.company_id
          FROM financial_years fy
          JOIN company_profiles company ON company.id = fy.company_id
         WHERE fy.is_active = TRUE
           AND fy.label = '2025-26'
           AND fy.start_date = :seed_start AND fy.end_date = :seed_end
           AND fy.end_date < :today
           AND company.name = 'Default Company'
           AND company.address = '' AND COALESCE(company.gst, '') = ''
           AND NOT EXISTS (SELECT 1 FROM invoices)
           AND NOT EXISTS (SELECT 1 FROM company_profiles other WHERE other.id <> company.id)
           AND NOT EXISTS (SELECT 1 FROM financial_years other WHERE other.id <> fy.id)
    """), {"today": today, "seed_start": date(2025, 4, 1), "seed_end": date(2026, 3, 31)}).one_or_none()
    if bootstrap_year is None:
        return

    old_fy_id, company_id = bootstrap_year
    start_year = today.year if today.month >= 4 else today.year - 1
    new_fy_id = conn.execute(text("""
        INSERT INTO financial_years (company_id, label, start_date, end_date, is_active, created_at)
        VALUES (:company_id, :label, :start_date, :end_date, TRUE, CURRENT_TIMESTAMP)
        RETURNING id
    """), {
        "company_id": company_id,
        "label": f"{start_year}-{(start_year + 1) % 100:02d}",
        "start_date": date(start_year, 4, 1),
        "end_date": date(start_year + 1, 3, 31),
    }).scalar_one()
    conn.execute(text("""
        INSERT INTO invoice_series
            (company_id, financial_year_id, voucher_type, prefix, suffix, include_year,
             year_format, separator, next_sequence, pad_digits, created_at)
        SELECT company_id, :new_fy_id, voucher_type, prefix, suffix, include_year,
               year_format, separator, 1, pad_digits, CURRENT_TIMESTAMP
          FROM invoice_series
         WHERE financial_year_id = :old_fy_id AND company_id = :company_id
    """), {"new_fy_id": new_fy_id, "old_fy_id": old_fy_id, "company_id": company_id})
    conn.execute(text("UPDATE financial_years SET is_active = FALSE WHERE id = :id"), {"id": old_fy_id})


def down(conn) -> None:
    # Documents may have used the new year since migration; keep it on rollback.
    pass
