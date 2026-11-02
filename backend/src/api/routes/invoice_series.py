from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from src.api.deps import require_company_role
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries
from src.models.user import User, UserRole
from src.schemas.invoice_series import InvoiceSeriesOut, InvoiceSeriesUpdate
from src.services.financial_year import get_active_fy
from src.services.series import gstr1_number_problem
from src.api.deps import get_active_company

router = APIRouter()


@router.get("", response_model=list[InvoiceSeriesOut], include_in_schema=False)
@router.get("/", response_model=list[InvoiceSeriesOut])
def list_invoice_series(
    financial_year_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_company_role(UserRole.admin)),
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
    _: User = Depends(require_company_role(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    series = db.query(InvoiceSeries).filter(
        InvoiceSeries.id == series_id,
        InvoiceSeries.company_id == active_company.id,
    ).first()
    if not series:
        raise HTTPException(status_code=404, detail=f"Invoice series {series_id} not found")

    def format_of(row) -> tuple:
        return (row.prefix, row.suffix, row.include_year, row.year_format, row.separator, row.pad_digits)

    format_before = format_of(series)
    series.prefix = payload.prefix.strip().upper()
    series.suffix = payload.suffix.strip().upper()
    series.include_year = payload.include_year
    series.year_format = payload.year_format
    series.separator = payload.separator
    series.pad_digits = payload.pad_digits
    if payload.next_sequence is not None:
        series.next_sequence = payload.next_sequence

    # Numbers cannot be edited once issued, so a format GSTR-1 refuses has to be
    # caught here rather than on filing day. Only these two series reach GSTR-1,
    # and only a company with a GSTIN files one. A series already off the rule can
    # still have its counter moved, so the check waits for a change of format.
    if (
        series.voucher_type in ("sales", "credit_note")
        and (active_company.gst or "").strip()
        and format_of(series) != format_before
    ):
        fy = (
            db.query(FinancialYear).filter(FinancialYear.id == series.financial_year_id).first()
            if series.financial_year_id is not None
            else get_active_fy(db, company_id=active_company.id)
        )
        problem = gstr1_number_problem(series, fy)
        if problem:
            db.rollback()
            raise HTTPException(status_code=400, detail=problem)

    db.commit()
    db.refresh(series)
    return series
