from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.db.session import get_db
from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries
from src.models.user import User
from src.schemas.financial_year import FinancialYearCreate, FinancialYearOut
from src.services.financial_year import activate_fy, get_active_fy

router = APIRouter()


def _seed_series_for_fy(db: Session, new_fy_id: int) -> None:
    """Clone the 3 core series rows from the active FY into the new FY."""
    active_fy = get_active_fy(db)
    if active_fy is None:
        # No active FY to clone from; seed bare defaults
        for vtype, prefix in [("sales", "INV"), ("purchase", "PINV"), ("payment", "PAY")]:
            db.add(InvoiceSeries(
                voucher_type=vtype,
                financial_year_id=new_fy_id,
                prefix=prefix,
                include_year=True,
                year_format="YYYY",
                separator="-",
                next_sequence=1,
                pad_digits=3,
            ))
        return

    source_rows = (
        db.query(InvoiceSeries)
        .filter(
            InvoiceSeries.financial_year_id == active_fy.id,
            InvoiceSeries.voucher_type.in_(["sales", "purchase", "payment"]),
        )
        .all()
    )

    for src in source_rows:
        db.add(InvoiceSeries(
            voucher_type=src.voucher_type,
            financial_year_id=new_fy_id,
            prefix=src.prefix,
            include_year=src.include_year,
            year_format=src.year_format,
            separator=src.separator,
            next_sequence=1,
            pad_digits=src.pad_digits,
        ))


@router.get("", response_model=list[FinancialYearOut], include_in_schema=False)
@router.get("/", response_model=list[FinancialYearOut])
def list_financial_years(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(FinancialYear).order_by(FinancialYear.start_date.asc()).all()


@router.post("/", response_model=FinancialYearOut, status_code=201)
def create_financial_year(
    payload: FinancialYearCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    existing = db.query(FinancialYear).filter(FinancialYear.label == payload.label).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Financial year '{payload.label}' already exists.")

    fy = FinancialYear(
        label=payload.label,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_active=False,
    )
    db.add(fy)
    db.flush()  # get fy.id before committing
    _seed_series_for_fy(db, fy.id)
    db.commit()
    db.refresh(fy)
    return fy


@router.put("/{fy_id}/activate", response_model=FinancialYearOut)
def activate_financial_year(
    fy_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    fy = activate_fy(db, fy_id)
    if not fy:
        raise HTTPException(status_code=404, detail=f"Financial year {fy_id} not found")
    return fy
