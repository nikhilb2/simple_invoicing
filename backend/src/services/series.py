from datetime import datetime

from sqlalchemy.orm import Session

from src.models.invoice_series import InvoiceSeries


def generate_next_number(db: Session, voucher_type: str) -> str:
    """Atomically increment the series counter and return the formatted number."""
    series = (
        db.query(InvoiceSeries)
        .filter(InvoiceSeries.voucher_type == voucher_type)
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
        now = datetime.utcnow()
        if series.year_format == "MM-YYYY":
            year_part = now.strftime("%m") + sep + str(now.year)
        else:
            year_part = str(now.year)
        return f"{series.prefix}{sep}{year_part}{sep}{seq_str}"
    else:
        return f"{series.prefix}{sep}{seq_str}"
