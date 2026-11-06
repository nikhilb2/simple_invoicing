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
from src.services.series import gstr1_number_problem, gstr1_series_warning
from src.api.deps import get_active_company

router = APIRouter()


def _reaches_gstr1(series: InvoiceSeries, company: CompanyProfile) -> bool:
    """Only these two series reach GSTR-1, and only a company with a GSTIN files one."""
    return series.voucher_type in ("sales", "credit_note") and bool((company.gst or "").strip())


def _series_fy(db: Session, series: InvoiceSeries, company: CompanyProfile) -> Optional[FinancialYear]:
    if series.financial_year_id is not None:
        return db.query(FinancialYear).filter(FinancialYear.id == series.financial_year_id).first()
    return get_active_fy(db, company_id=company.id)


def _active_series(db: Session, series: InvoiceSeries, company: CompanyProfile) -> Optional[InvoiceSeries]:
    """The active year's row for this voucher type, whose format every year's numbers take."""
    active_fy = get_active_fy(db, company_id=company.id)
    if active_fy is None:
        return None
    return db.query(InvoiceSeries).filter(
        InvoiceSeries.company_id == company.id,
        InvoiceSeries.voucher_type == series.voucher_type,
        InvoiceSeries.financial_year_id == active_fy.id,
    ).first()


def _series_out(db: Session, series: InvoiceSeries, company: CompanyProfile) -> InvoiceSeriesOut:
    out = InvoiceSeriesOut.model_validate(series)
    if _reaches_gstr1(series, company):
        out.gstr1_warning = gstr1_series_warning(
            series, _series_fy(db, series, company), _active_series(db, series, company),
        )
    return out


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
    return [_series_out(db, series, active_company) for series in q.order_by(InvoiceSeries.id.asc()).all()]


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
    # caught here rather than on filing day. A series already off the rule can
    # still have its counter moved, so the check waits for a change of format.
    if _reaches_gstr1(series, active_company) and format_of(series) != format_before:
        problem = gstr1_number_problem(series, _series_fy(db, series, active_company))
        # The active year's format is also what backdated documents are numbered
        # with, under their own year's label.
        active = _active_series(db, series, active_company)
        if not problem and active is not None and active.id == series.id:
            other_years = db.query(InvoiceSeries).filter(
                InvoiceSeries.company_id == active_company.id,
                InvoiceSeries.voucher_type == series.voucher_type,
                InvoiceSeries.id != series.id,
            ).all()
            for other in other_years:
                problem = gstr1_number_problem(other, _series_fy(db, other, active_company), series)
                if problem:
                    break
        if problem:
            db.rollback()
            raise HTTPException(status_code=400, detail=problem)

    db.commit()
    db.refresh(series)
    return _series_out(db, series, active_company)
