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


DEFAULT_SERIES_CONFIGS = {
    "sales": {"prefix": "INV", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    "purchase": {"prefix": "PINV", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    "payment": {"prefix": "PAY", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    "credit_note": {"prefix": "CN", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
}


def _seed_series_for_fy(db: Session, new_fy_id: int) -> None:
    """Create FY-scoped series rows with reset counters and complete voucher coverage."""
    active_fy = get_active_fy(db)
    if active_fy is None:
        for voucher_type, config in DEFAULT_SERIES_CONFIGS.items():
            db.add(InvoiceSeries(
                voucher_type=voucher_type,
                financial_year_id=new_fy_id,
                prefix=config["prefix"],
                suffix=config["suffix"],
                include_year=config["include_year"],
                year_format=config["year_format"],
                separator=config["separator"],
                next_sequence=1,
                pad_digits=config["pad_digits"],
            ))
        return

    source_rows = (
        db.query(InvoiceSeries)
        .filter(
            InvoiceSeries.financial_year_id == active_fy.id,
            InvoiceSeries.voucher_type.in_(list(DEFAULT_SERIES_CONFIGS)),
        )
        .all()
    )
    source_by_type = {row.voucher_type: row for row in source_rows}

    for voucher_type, default_config in DEFAULT_SERIES_CONFIGS.items():
        src = source_by_type.get(voucher_type)
        db.add(InvoiceSeries(
            voucher_type=voucher_type,
            financial_year_id=new_fy_id,
            prefix=src.prefix if src else default_config["prefix"],
            suffix=src.suffix if src else default_config["suffix"],
            include_year=src.include_year if src else default_config["include_year"],
            year_format=src.year_format if src else default_config["year_format"],
            separator=src.separator if src else default_config["separator"],
            next_sequence=1,
            pad_digits=src.pad_digits if src else default_config["pad_digits"],
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
