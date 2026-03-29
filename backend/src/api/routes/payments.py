from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, require_roles
from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.payment import Payment
from src.models.user import User, UserRole
from src.schemas.payment import PaymentCreate, PaymentOut

router = APIRouter()


@router.post("", response_model=PaymentOut, include_in_schema=False)
@router.post("/", response_model=PaymentOut)
def create_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    ledger = db.query(Ledger).filter(Ledger.id == payload.ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail="Ledger not found")

    payment = Payment(
        ledger_id=payload.ledger_id,
        voucher_type=payload.voucher_type,
        amount=payload.amount,
        date=payload.date or datetime.utcnow(),
        mode=payload.mode.strip() if payload.mode else None,
        reference=payload.reference.strip() if payload.reference else None,
        notes=payload.notes.strip() if payload.notes else None,
        created_by=current_user.id,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@router.get("", response_model=list[PaymentOut], include_in_schema=False)
@router.get("/", response_model=list[PaymentOut])
def list_payments(
    ledger_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Payment)
    if ledger_id is not None:
        query = query.filter(Payment.ledger_id == ledger_id)
    return query.order_by(Payment.date.desc()).all()


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.delete("/{payment_id}")
def delete_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    db.delete(payment)
    db.commit()
    return {"message": "Payment deleted"}
