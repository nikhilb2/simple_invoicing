from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from src.models.financial_year import FinancialYear


def get_active_fy(db: Session, company_id: int | None = None) -> Optional[FinancialYear]:
    """Return the currently active financial year, or None if none is set."""
    query = db.query(FinancialYear).filter(FinancialYear.is_active.is_(True))
    if company_id is not None:
        query = query.filter(FinancialYear.company_id == company_id)
    return query.first()


def get_fy_for_date(db: Session, invoice_date: date, company_id: int | None = None) -> Optional[FinancialYear]:
    """Return the financial year whose range contains invoice_date, or None."""
    query = db.query(FinancialYear).filter(
        FinancialYear.start_date <= invoice_date,
        FinancialYear.end_date >= invoice_date,
    )
    if company_id is not None:
        query = query.filter(FinancialYear.company_id == company_id)
    return query.first()


def activate_fy(db: Session, fy_id: int, company_id: int | None = None) -> FinancialYear:
    """Set the target FY as active; deactivate all others atomically."""
    target_query = db.query(FinancialYear).filter(FinancialYear.id == fy_id)
    if company_id is not None:
        target_query = target_query.filter(FinancialYear.company_id == company_id)
    target = target_query.first()
    if not target:
        return None

    deactivate_query = db.query(FinancialYear).filter(FinancialYear.is_active.is_(True))
    if company_id is not None:
        deactivate_query = deactivate_query.filter(FinancialYear.company_id == company_id)

    deactivate_query.update(
        {"is_active": False}, synchronize_session="fetch"
    )
    target.is_active = True
    db.commit()
    db.refresh(target)
    return target
