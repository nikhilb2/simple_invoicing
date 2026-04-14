from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, require_roles
from src.db.session import get_db
from src.models.buyer import Buyer
from src.models.user import User, UserRole
from src.schemas.buyer import BuyerCreate, BuyerOut

router = APIRouter()


@router.post("", response_model=BuyerOut, include_in_schema=False)
@router.post("/", response_model=BuyerOut)
def create_buyer(
    payload: BuyerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    gst = payload.gst
    if gst:
        existing_buyer = db.query(Buyer).filter(Buyer.gst == gst).first()
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
    )
    db.add(buyer)
    db.commit()
    db.refresh(buyer)
    return buyer


@router.get("", response_model=list[BuyerOut], include_in_schema=False)
@router.get("/", response_model=list[BuyerOut])
def list_buyers(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(Buyer).order_by(Buyer.name.asc()).all()
