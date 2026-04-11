from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from src.models.financial_year import FinancialYear


def get_active_fy(db: Session) -> Optional[FinancialYear]:
    """Return the currently active financial year, or None if none is set."""
    return db.query(FinancialYear).filter(FinancialYear.is_active.is_(True)).first()


def get_fy_for_date(db: Session, invoice_date: date) -> Optional[FinancialYear]:
    """Return the financial year whose range contains invoice_date, or None."""
    return (
        db.query(FinancialYear)
        .filter(
            FinancialYear.start_date <= invoice_date,
            FinancialYear.end_date >= invoice_date,
        )
        .first()
    )


def activate_fy(db: Session, fy_id: int) -> FinancialYear:
    """Set the target FY as active; deactivate all others atomically."""
    target = db.query(FinancialYear).filter(FinancialYear.id == fy_id).first()
    if not target:
        return None

    db.query(FinancialYear).filter(FinancialYear.is_active.is_(True)).update(
        {"is_active": False}, synchronize_session="fetch"
    )
    target.is_active = True
    db.commit()
    db.refresh(target)
    return target
