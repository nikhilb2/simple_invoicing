from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries


def generate_next_number(
    db: Session, voucher_type: str, financial_year_id: Optional[int] = None
) -> str:
    """Atomically increment the series counter and return the formatted number.

    Lookup order:
    1. Exact match on (voucher_type, financial_year_id) if provided.
    2. Fall back to a row with NULL financial_year_id for backward compatibility.
    """
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

    seq = series.next_sequence
    series.next_sequence = seq + 1

    sep = series.separator
    seq_str = str(seq).zfill(series.pad_digits)

    if series.include_year:
        if series.year_format == "FY":
            # Use the label from the linked financial_year row
            fy = None
            if series.financial_year_id is not None:
                fy = db.query(FinancialYear).filter(
                    FinancialYear.id == series.financial_year_id
                ).first()
            year_part = fy.label if fy else "FY"
        elif series.year_format == "MM-YYYY":
            now = datetime.utcnow()
            year_part = now.strftime("%m") + sep + str(now.year)
        else:
            year_part = str(datetime.utcnow().year)
        return f"{series.prefix}{sep}{year_part}{sep}{seq_str}"
    else:
        return f"{series.prefix}{sep}{seq_str}"
