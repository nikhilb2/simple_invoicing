from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries


def _format_number(series: InvoiceSeries, seq: int, fy: Optional[FinancialYear]) -> str:
    sep = series.separator
    seq_str = str(seq).zfill(series.pad_digits)

    if series.include_year:
        if series.year_format == "FY":
            year_part = fy.label if fy else "FY"
        elif series.year_format == "MM-YYYY":
            now = datetime.utcnow()
            year_part = now.strftime("%m") + sep + str(now.year)
        else:
            year_part = str(datetime.utcnow().year)
        return f"{series.prefix}{sep}{year_part}{sep}{seq_str}"
    else:
        return f"{series.prefix}{sep}{seq_str}"


def generate_next_number(
    db: Session, voucher_type: str, financial_year_id: Optional[int] = None
) -> str:
    """Atomically increment the series counter and return the formatted number.

    Lookup order:
    1. Exact match on (voucher_type, financial_year_id) if provided.
    2. Fall back to a row with NULL financial_year_id for backward compatibility.

    If the generated number already exists in the invoices table (e.g. due to a
    previous rolled-back transaction or cross-FY series overlap), the counter is
    advanced until a unique number is found.
    """
    # Import here to avoid circular imports
    from src.models.invoice import Invoice  # noqa: PLC0415

    series = None

    if financial_year_id is not None:
        series = (
            db.query(InvoiceSeries)
            .filter(
                InvoiceSeries.voucher_type == voucher_type,
                InvoiceSeries.financial_year_id == financial_year_id,
            )
            .with_for_update()
            .first()
        )

    if series is None:
        # Fallback: NULL financial_year_id row (legacy / backward compat)
        series = (
            db.query(InvoiceSeries)
            .filter(
                InvoiceSeries.voucher_type == voucher_type,
                InvoiceSeries.financial_year_id.is_(None),
            )
            .with_for_update()
            .first()
        )

    if not series:
        return "INV-000000"

    # Resolve linked FY label once (only needed for "FY" year_format)
    linked_fy: Optional[FinancialYear] = None
    if series.include_year and series.year_format == "FY" and series.financial_year_id is not None:
        linked_fy = db.query(FinancialYear).filter(
            FinancialYear.id == series.financial_year_id
        ).first()

    # Advance the counter, skipping any numbers already present in the DB.
    # This guards against rollback-caused repeats and cross-FY series collisions.
    MAX_SKIP = 1000
    for _ in range(MAX_SKIP):
        seq = series.next_sequence
        series.next_sequence = seq + 1
        number = _format_number(series, seq, linked_fy)
        existing = db.query(Invoice.id).filter(Invoice.invoice_number == number).first()
        if existing is None:
            return number

    # Extremely unlikely: return a timestamped fallback so creation still succeeds
    return f"{series.prefix}-{int(datetime.utcnow().timestamp())}"
