from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from src.api.deps import require_roles
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.invoice_series import InvoiceSeries
from src.models.user import User, UserRole
from src.schemas.invoice_series import InvoiceSeriesOut, InvoiceSeriesUpdate
from src.api.deps import get_active_company

router = APIRouter()


@router.get("", response_model=list[InvoiceSeriesOut], include_in_schema=False)
@router.get("/", response_model=list[InvoiceSeriesOut])
def list_invoice_series(
    financial_year_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    q = db.query(InvoiceSeries).filter(InvoiceSeries.company_id == active_company.id)
    if financial_year_id is not None:
        q = q.filter(InvoiceSeries.financial_year_id == financial_year_id)
    return q.order_by(InvoiceSeries.id.asc()).all()


@router.put("/{series_id}", response_model=InvoiceSeriesOut)
def update_invoice_series(
    series_id: int,
    payload: InvoiceSeriesUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    series = db.query(InvoiceSeries).filter(
        InvoiceSeries.id == series_id,
        InvoiceSeries.company_id == active_company.id,
    ).first()
    if not series:
        raise HTTPException(status_code=404, detail=f"Invoice series {series_id} not found")

    series.prefix = payload.prefix.strip().upper()
    series.suffix = payload.suffix.strip().upper()
    series.include_year = payload.include_year
    series.year_format = payload.year_format
    series.separator = payload.separator
    series.pad_digits = payload.pad_digits

    db.commit()
    db.refresh(series)
    return series
