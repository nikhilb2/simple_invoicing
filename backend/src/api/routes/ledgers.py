from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, require_roles
from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.user import User, UserRole
from src.schemas.ledger import DayBookEntry, DayBookOut, LedgerCreate, LedgerOut, LedgerStatementEntry, LedgerStatementOut, PaginatedLedgerOut

router = APIRouter()


def _make_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC) for consistent sorting."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@router.post("", response_model=LedgerOut, include_in_schema=False)
@router.post("/", response_model=LedgerOut)
def create_ledger(
    payload: LedgerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    existing_ledger = db.query(Ledger).filter(Ledger.gst == payload.gst.strip()).first()
    if existing_ledger:
        raise HTTPException(status_code=400, detail="Ledger with this GST already exists")

    ledger = Ledger(
        name=payload.name.strip(),
        address=payload.address.strip(),
        gst=payload.gst.strip().upper(),
        phone_number=payload.phone_number.strip(),
        email=payload.email.strip() if payload.email else None,
        website=payload.website.strip() if payload.website else None,
        bank_name=payload.bank_name.strip() if payload.bank_name else None,
        branch_name=payload.branch_name.strip() if payload.branch_name else None,
        account_name=payload.account_name.strip() if payload.account_name else None,
        account_number=payload.account_number.strip() if payload.account_number else None,
        ifsc_code=payload.ifsc_code.strip().upper() if payload.ifsc_code else None,
    )
    db.add(ledger)
    db.commit()
    db.refresh(ledger)
    return ledger


@router.get("", response_model=PaginatedLedgerOut, include_in_schema=False)
@router.get("/", response_model=PaginatedLedgerOut)
def list_ledgers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Ledger)
    if search.strip():
        query = query.filter(Ledger.name.ilike(f"%{search.strip()}%"))
    total = query.count()
    items = (
        query.order_by(Ledger.name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedLedgerOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
    )


@router.get("/{ledger_id}", response_model=LedgerOut)
def get_ledger(
    ledger_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")
    return ledger


@router.put("/{ledger_id}", response_model=LedgerOut)
def update_ledger(
    ledger_id: int,
    payload: LedgerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    gst = payload.gst.strip().upper()
    gst_owner = db.query(Ledger).filter(Ledger.gst == gst, Ledger.id != ledger_id).first()
    if gst_owner:
        raise HTTPException(status_code=400, detail="Ledger with this GST already exists")

    ledger.name = payload.name.strip()
    ledger.address = payload.address.strip()
    ledger.gst = gst
    ledger.phone_number = payload.phone_number.strip()
    ledger.email = payload.email.strip() if payload.email else None
    ledger.website = payload.website.strip() if payload.website else None
    ledger.bank_name = payload.bank_name.strip() if payload.bank_name else None
    ledger.branch_name = payload.branch_name.strip() if payload.branch_name else None
    ledger.account_name = payload.account_name.strip() if payload.account_name else None
    ledger.account_number = payload.account_number.strip() if payload.account_number else None
    ledger.ifsc_code = payload.ifsc_code.strip().upper() if payload.ifsc_code else None

    db.commit()
    db.refresh(ledger)
    return ledger


@router.delete("/{ledger_id}")
def delete_ledger(
    ledger_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    has_invoices = db.query(Invoice.id).filter(Invoice.ledger_id == ledger_id).first()
    if has_invoices:
        raise HTTPException(status_code=400, detail="Cannot delete ledger linked to invoices")

    has_payments = db.query(Payment.id).filter(Payment.ledger_id == ledger_id).first()
    if has_payments:
        raise HTTPException(status_code=400, detail="Cannot delete ledger linked to payments")

    db.delete(ledger)
    db.commit()
    return {"message": "Ledger deleted"}


@router.get("/day-book", response_model=DayBookOut)
def get_day_book(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    invoices = (
        db.query(Invoice)
        .filter(Invoice.created_at >= period_start)
        .filter(Invoice.created_at <= period_end)
        .order_by(Invoice.created_at.asc(), Invoice.id.asc())
        .all()
    )

    payments = (
        db.query(Payment)
        .filter(Payment.date >= period_start)
        .filter(Payment.date <= period_end)
        .order_by(Payment.date.asc(), Payment.id.asc())
        .all()
    )

    entries = []
    for invoice in invoices:
        entries.append(DayBookEntry(
            entry_id=invoice.id,
            entry_type="invoice",
            date=invoice.created_at,
            voucher_type=invoice.voucher_type.title(),
            ledger_name=invoice.ledger_name or "Unknown ledger",
            particulars=f"{invoice.voucher_type.title()} Invoice #{invoice.id}",
            debit=float(invoice.total_amount) if invoice.voucher_type == "sales" else 0.0,
            credit=float(invoice.total_amount) if invoice.voucher_type == "purchase" else 0.0,
        ))
    for payment in payments:
        ledger = db.query(Ledger).filter(Ledger.id == payment.ledger_id).first()
        entries.append(DayBookEntry(
            entry_id=payment.id,
            entry_type="payment",
            date=payment.date,
            voucher_type=payment.voucher_type.title(),
            ledger_name=ledger.name if ledger else "Unknown ledger",
            particulars=f"{payment.voucher_type.title()} #{payment.id}" + (f" ({payment.mode})" if payment.mode else ""),
            debit=float(payment.amount) if payment.voucher_type == "payment" else 0.0,
            credit=float(payment.amount) if payment.voucher_type == "receipt" else 0.0,
        ))
    entries.sort(key=lambda e: _make_aware(e.date))

    return DayBookOut(
        from_date=from_date,
        to_date=to_date,
        total_debit=sum(entry.debit for entry in entries),
        total_credit=sum(entry.credit for entry in entries),
        entries=entries,
    )


@router.get("/{ledger_id}/statement", response_model=LedgerStatementOut)
def get_ledger_statement(
    ledger_id: int,
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    opening_totals = (
        db.query(
            func.coalesce(func.sum(case((Invoice.voucher_type == "sales", Invoice.total_amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.voucher_type == "purchase", Invoice.total_amount), else_=0)), 0),
        )
        .filter(Invoice.ledger_id == ledger_id)
        .filter(Invoice.created_at < period_start)
        .one()
    )

    opening_payment_totals = (
        db.query(
            func.coalesce(func.sum(case((Payment.voucher_type == "payment", Payment.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.voucher_type == "receipt", Payment.amount), else_=0)), 0),
        )
        .filter(Payment.ledger_id == ledger_id)
        .filter(Payment.date < period_start)
        .one()
    )

    period_invoices = (
        db.query(Invoice)
        .filter(Invoice.ledger_id == ledger_id)
        .filter(Invoice.created_at >= period_start)
        .filter(Invoice.created_at <= period_end)
        .order_by(Invoice.created_at.asc(), Invoice.id.asc())
        .all()
    )

    period_payments = (
        db.query(Payment)
        .filter(Payment.ledger_id == ledger_id)
        .filter(Payment.date >= period_start)
        .filter(Payment.date <= period_end)
        .order_by(Payment.date.asc(), Payment.id.asc())
        .all()
    )

    entries = []
    for invoice in period_invoices:
        entries.append(LedgerStatementEntry(
            entry_id=invoice.id,
            entry_type="invoice",
            date=invoice.created_at,
            voucher_type=invoice.voucher_type.title(),
            particulars=invoice.ledger_name or ledger.name,
            debit=float(invoice.total_amount) if invoice.voucher_type == "sales" else 0.0,
            credit=float(invoice.total_amount) if invoice.voucher_type == "purchase" else 0.0,
        ))
    for payment in period_payments:
        entries.append(LedgerStatementEntry(
            entry_id=payment.id,
            entry_type="payment",
            date=payment.date,
            voucher_type=payment.voucher_type.title(),
            particulars=f"{payment.voucher_type.title()}" + (f" ({payment.mode})" if payment.mode else ""),
            debit=float(payment.amount) if payment.voucher_type == "payment" else 0.0,
            credit=float(payment.amount) if payment.voucher_type == "receipt" else 0.0,
        ))
    entries.sort(key=lambda e: _make_aware(e.date))

    period_debit = sum(entry.debit for entry in entries)
    period_credit = sum(entry.credit for entry in entries)
    opening_debit = float(opening_totals[0]) + float(opening_payment_totals[0])
    opening_credit = float(opening_totals[1]) + float(opening_payment_totals[1])
    opening_balance = opening_debit - opening_credit
    closing_balance = opening_balance + period_debit - period_credit

    return LedgerStatementOut(
        ledger=ledger,
        from_date=from_date,
        to_date=to_date,
        opening_balance=opening_balance,
        period_debit=period_debit,
        period_credit=period_credit,
        closing_balance=closing_balance,
        entries=entries,
    )