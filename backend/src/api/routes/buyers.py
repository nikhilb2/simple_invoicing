from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user, require_roles
from src.db.session import get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.user import User, UserRole
from src.schemas.buyer import BuyerCreate, BuyerOut

router = APIRouter()


@router.post("", response_model=BuyerOut, include_in_schema=False)
@router.post("/", response_model=BuyerOut)
def create_buyer(
    payload: BuyerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    gst = payload.gst
    if gst:
        existing_query = db.query(Buyer).filter(Buyer.gst == gst)
        if company_id is not None:
            existing_query = existing_query.filter(or_(Buyer.company_id == company_id, Buyer.company_id.is_(None)))
        existing_buyer = existing_query.first()
        if existing_buyer:
            raise HTTPException(status_code=400, detail="Buyer with this GST already exists")

    buyer = Buyer(
        name=payload.name.strip(),
        address=payload.address.strip(),
        gst=gst,
        phone_number=payload.phone_number.strip(),
        email=payload.email.strip() if payload.email else None,
        website=payload.website.strip() if payload.website else None,
        bank_name=payload.bank_name.strip() if payload.bank_name else None,
        branch_name=payload.branch_name.strip() if payload.branch_name else None,
        account_name=payload.account_name.strip() if payload.account_name else None,
        account_number=payload.account_number.strip() if payload.account_number else None,
        ifsc_code=payload.ifsc_code.strip().upper() if payload.ifsc_code else None,
        company_id=company_id,
    )
    db.add(buyer)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "ix_buyers_gst" in str(exc.orig) or "buyers_gst_key" in str(exc.orig):
            raise HTTPException(
                status_code=400,
                detail="Buyer with this GST already exists. Run latest migrations to enable per-company GST uniqueness.",
            )
        raise
    db.refresh(buyer)
    return buyer


@router.get("", response_model=list[BuyerOut], include_in_schema=False)
@router.get("/", response_model=list[BuyerOut])
def list_buyers(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    query = db.query(Buyer)
    if company_id is not None:
        query = query.filter(or_(Buyer.company_id == company_id, Buyer.company_id.is_(None)))
    return query.order_by(Buyer.name.asc()).all()
