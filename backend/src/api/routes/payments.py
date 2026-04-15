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
from src.services.financial_year import get_active_fy, get_fy_for_date

router = APIRouter()


def _find_existing_opening_balance(
    db: Session,
    ledger_id: int,
    exclude_payment_id: int | None = None,
) -> Payment | None:
    query = db.query(Payment).filter(
        Payment.ledger_id == ledger_id,
        Payment.voucher_type == "opening_balance",
        Payment.status == "active",
    )
    if exclude_payment_id is not None:
        query = query.filter(Payment.id != exclude_payment_id)
    return query.first()


def _ensure_single_opening_balance(
    db: Session,
    ledger_id: int,
    voucher_type: str,
    exclude_payment_id: int | None = None,
) -> None:
    if voucher_type != "opening_balance":
        return

    existing = _find_existing_opening_balance(
        db,
        ledger_id,
        exclude_payment_id=exclude_payment_id,
    )
    if existing:
        raise HTTPException(status_code=409, detail="Opening balance already exists for this ledger")


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

    _ensure_single_opening_balance(db, payload.ledger_id, payload.voucher_type)

    payment_date = payload.date or datetime.utcnow()
    payment_day = payment_date.date() if hasattr(payment_date, "date") else payment_date

    active_fy = get_active_fy(db)
    fy_for_payment = active_fy
    if payment_day is not None:
        dated_fy = get_fy_for_date(db, payment_day)
        if dated_fy is not None:
            fy_for_payment = dated_fy
    fy_id = fy_for_payment.id if fy_for_payment else None

    payment_number = None
    if payload.voucher_type != "opening_balance":
        payment_number = generate_next_number(
            db,
            "payment",
            fy_id,
            payment_day,
            active_fy.id if active_fy else None,
        )

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
        pdate = payment_day
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

    _ensure_single_opening_balance(
        db,
        payment.ledger_id,
        payload.voucher_type,
        exclude_payment_id=payment.id,
    )

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
