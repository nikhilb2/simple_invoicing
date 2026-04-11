from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, require_roles
from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.payment import Payment
from src.models.user import User, UserRole
from src.schemas.payment import PaymentCreate, PaymentOut, PaymentUpdate
from src.services.series import generate_next_number
from src.services.financial_year import get_active_fy

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

    active_fy = get_active_fy(db)
    fy_id = active_fy.id if active_fy else None

    payment_number = generate_next_number(db, payload.voucher_type, fy_id)

    payment_date = payload.date or datetime.utcnow()

    payment = Payment(
        ledger_id=payload.ledger_id,
        voucher_type=payload.voucher_type,
        amount=payload.amount,
        date=payment_date,
        mode=payload.mode.strip() if payload.mode else None,
        reference=payload.reference.strip() if payload.reference else None,
        notes=payload.notes.strip() if payload.notes else None,
        payment_number=payment_number,
        financial_year_id=fy_id,
        created_by=current_user.id,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    warnings: list[str] = []
    if active_fy:
        pdate = payment_date.date() if hasattr(payment_date, "date") else payment_date
        if not (active_fy.start_date <= pdate <= active_fy.end_date):
            warnings.append("invoice_date_outside_fy")

    result = PaymentOut.model_validate(payment)
    result.warnings = warnings
    return result


@router.get("", response_model=list[PaymentOut], include_in_schema=False)
@router.get("/", response_model=list[PaymentOut])
def list_payments(
    ledger_id: int | None = Query(None),
    include_cancelled: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Payment)
    if ledger_id is not None:
        query = query.filter(Payment.ledger_id == ledger_id)
    if not include_cancelled:
        query = query.filter(Payment.status == "active")
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


@router.put("/{payment_id}", response_model=PaymentOut)
def update_payment(
    payment_id: int,
    payload: PaymentUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.status == "active").first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    payment.voucher_type = payload.voucher_type
    payment.amount = payload.amount
    if payload.date is not None:
        payment.date = payload.date
    payment.mode = payload.mode.strip() if payload.mode else None
    payment.reference = payload.reference.strip() if payload.reference else None
    payment.notes = payload.notes.strip() if payload.notes else None
    db.commit()
    db.refresh(payment)
    result = PaymentOut.model_validate(payment)
    return result


@router.delete("/{payment_id}")
def delete_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.status == "active").first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment.status = "cancelled"
    db.commit()
    return {"message": "Payment cancelled"}
