from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.db.session import get_db
from src.models.financial_year import FinancialYear
from src.models.user import User
from src.schemas.financial_year import FinancialYearCreate, FinancialYearOut
from src.services.financial_year import activate_fy

router = APIRouter()


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
    fy = FinancialYear(
        label=payload.label,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_active=False,
    )
    db.add(fy)
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
