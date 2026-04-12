from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries


def _format_number(
    series: InvoiceSeries,
    seq: int,
    fy: Optional[FinancialYear],
    invoice_date: Optional[date] = None,
) -> str:
    sep = series.separator
    seq_str = str(seq).zfill(series.pad_digits)
    suffix = series.suffix or ""

    if series.include_year:
        if series.year_format == "FY":
            year_part = fy.label if fy else "FY"
        elif series.year_format == "MM-YYYY":
            ref = invoice_date if invoice_date is not None else datetime.utcnow().date()
            year_part = ref.strftime("%m") + sep + str(ref.year)
        else:
            ref = invoice_date if invoice_date is not None else datetime.utcnow().date()
            year_part = str(ref.year)
        return f"{series.prefix}{sep}{year_part}{sep}{seq_str}{suffix}"
    else:
        return f"{series.prefix}{sep}{seq_str}{suffix}"


def generate_next_number(
    db: Session,
    voucher_type: str,
    financial_year_id: Optional[int] = None,
    invoice_date: Optional[date] = None,
    active_financial_year_id: Optional[int] = None,
) -> str:
    """Atomically increment the series counter and return the formatted number.

    Lookup order:
    1. Exact match on (voucher_type, financial_year_id) if provided.
    2. Fall back to a row with NULL financial_year_id for backward compatibility.

    When the invoice belongs to a non-active FY (backdated/forward-dated),
    format settings (prefix, year_format, separator, etc.) are taken from the
    active FY's series so the user only needs to configure one place.  The
    sequence counter and FY label always come from the target FY.

    If the generated number already exists in the invoices table (e.g. due to a
    previous rolled-back transaction or cross-FY series overlap), the counter is
    advanced until a unique number is found.
    """
    # Import here to avoid circular imports
    from src.models.invoice import Invoice  # noqa: PLC0415
    from src.models.payment import Payment  # noqa: PLC0415

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

    # When the invoice is for a different FY than the active one, borrow the
    # active FY's series for format settings (prefix, year_format, separator,
    # include_year, pad_digits).  This ensures the user-configured numbering
    # style is applied consistently even for backdated/forward-dated invoices.
    format_series = series
    if (
        active_financial_year_id is not None
        and active_financial_year_id != financial_year_id
    ):
        active_series = (
            db.query(InvoiceSeries)
            .filter(
                InvoiceSeries.voucher_type == voucher_type,
                InvoiceSeries.financial_year_id == active_financial_year_id,
            )
            .first()
        )
        if active_series is not None:
            format_series = active_series

    # Resolve the FY label for "FY" year_format.  Always use the TARGET FY
    # (financial_year_id) so a December 2025 invoice gets "2025-26", not "2026-27".
    linked_fy: Optional[FinancialYear] = None
    if format_series.include_year and format_series.year_format == "FY":
        fy_id_for_label = financial_year_id if financial_year_id is not None else series.financial_year_id
        if fy_id_for_label is not None:
            linked_fy = db.query(FinancialYear).filter(
                FinancialYear.id == fy_id_for_label
            ).first()

    # Advance the counter, skipping any numbers already present in the DB.
    # This guards against rollback-caused repeats and cross-FY series collisions.
    MAX_SKIP = 1000
    for _ in range(MAX_SKIP):
        seq = series.next_sequence
        series.next_sequence = seq + 1
        number = _format_number(format_series, seq, linked_fy, invoice_date)
        if voucher_type == "payment":
            existing = db.query(Payment.id).filter(Payment.payment_number == number).first()
        else:
            existing = db.query(Invoice.id).filter(Invoice.invoice_number == number).first()
        if existing is None:
            return number

    # Extremely unlikely: return a timestamped fallback so creation still succeeds
    return f"{series.prefix}-{int(datetime.utcnow().timestamp())}{series.suffix or ''}"
