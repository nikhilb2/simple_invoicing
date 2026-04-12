from datetime import date, datetime, time
from pathlib import Path

import weasyprint
from fastapi import APIRouter, Body, Depends, HTTPException
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from src.api.deps import require_roles
from src.api.routes.invoices import _build_invoice_pdf
from src.api.routes.ledgers import _build_statement_html, _make_aware
from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.ledger import LedgerStatementEntry
from src.services.credit_note_reporting import get_credit_note_ledger_summary
from src.services.mail import send_email

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "services" / "email_templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)

_CURRENCY_SYMBOLS: dict[str, str] = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def _symbol(code: str | None) -> str:
    return _CURRENCY_SYMBOLS.get(code or "INR", code or "₹")


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class EmailSendRequest(BaseModel):
    to: str | None = None
    cc: str | None = None
    subject: str | None = None
    message: str | None = None


class StatementEmailSendRequest(EmailSendRequest):
    from_date: date
    to_date: date


# ---------------------------------------------------------------------------
# POST /invoice/{invoice_id}
# ---------------------------------------------------------------------------

@router.post("/invoice/{invoice_id}")
async def send_invoice_email(
    invoice_id: int,
    payload: EmailSendRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    if payload is None:
        payload = EmailSendRequest()

    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.items), joinedload(Invoice.ledger))
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    to_email = payload.to or (invoice.ledger.email if invoice.ledger else None)
    if not to_email:
        raise HTTPException(
            status_code=400,
            detail="No recipient email address. Provide 'to' in the request body or add an email to the ledger.",
        )

    company = db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    currency_code = invoice.company_currency_code or (company.currency_code if company else "INR")

    product_ids = [item.product_id for item in (invoice.items or [])]
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []

    pdf_buf = _build_invoice_pdf(invoice, products)
    pdf_bytes = pdf_buf.read()

    inv_number = invoice.invoice_number or f"#{invoice.id}"
    inv_date = invoice.invoice_date.strftime("%d %b %Y") if invoice.invoice_date else "N/A"

    template = _jinja_env.get_template("invoice_email.html")
    html_body = template.render(
        company_name=invoice.company_name or (company.name if company else ""),
        company_email=invoice.company_email or (company.email if company else None),
        company_phone=invoice.company_phone or (company.phone_number if company else None),
        company_address=invoice.company_address or (company.address if company else None),
        invoice_number=inv_number,
        invoice_date=inv_date,
        due_date=None,  # due_date column is not yet mapped in the Python Invoice model
        buyer_name=invoice.ledger_name or (invoice.ledger.name if invoice.ledger else ""),
        total_amount=_fmt(float(invoice.total_amount)),
        items_count=len(invoice.items or []),
        currency=_symbol(currency_code),
        message=payload.message,
    )

    subject = payload.subject or f"Invoice {inv_number}"
    filename = f"invoice_{(invoice.invoice_number or str(invoice.id)).replace('/', '_')}.pdf"
    cc_list = [payload.cc] if payload.cc else None

    try:
        await send_email(
            db=db,
            to=to_email,
            subject=subject,
            html_body=html_body,
            attachments=[(pdf_bytes, filename)],
            cc=cc_list,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"message": f"Invoice email sent successfully to {to_email}"}


# ---------------------------------------------------------------------------
# POST /ledger-statement/{ledger_id}
# ---------------------------------------------------------------------------

@router.post("/ledger-statement/{ledger_id}")
async def send_ledger_statement_email(
    ledger_id: int,
    payload: StatementEmailSendRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    if payload.from_date > payload.to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    to_email = payload.to or ledger.email
    if not to_email:
        raise HTTPException(
            status_code=400,
            detail="No recipient email address. Provide 'to' in the request body or add an email to the ledger.",
        )

    company = db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    currency_code = company.currency_code if company and company.currency_code else "INR"

    period_start = datetime.combine(payload.from_date, time.min)
    period_end = datetime.combine(payload.to_date, time.max)

    opening_totals = (
        db.query(
            func.coalesce(func.sum(case((Invoice.voucher_type == "sales", Invoice.total_amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.voucher_type == "purchase", Invoice.total_amount), else_=0)), 0),
        )
        .filter(Invoice.ledger_id == ledger_id)
        .filter(Invoice.invoice_date < period_start)
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
        .filter(Invoice.invoice_date >= period_start)
        .filter(Invoice.invoice_date <= period_end)
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
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

    entries: list[LedgerStatementEntry] = []
    for inv in period_invoices:
        entries.append(LedgerStatementEntry(
            entry_id=inv.id,
            entry_type="invoice",
            date=inv.invoice_date,
            voucher_type=inv.voucher_type.title(),
            particulars=inv.ledger_name or ledger.name,
            debit=float(inv.total_amount) if inv.voucher_type == "sales" else 0.0,
            credit=float(inv.total_amount) if inv.voucher_type == "purchase" else 0.0,
        ))
    for pmt in period_payments:
        entries.append(LedgerStatementEntry(
            entry_id=pmt.id,
            entry_type="payment",
            date=pmt.date,
            voucher_type=pmt.voucher_type.title(),
            particulars=f"{pmt.voucher_type.title()}" + (f" ({pmt.mode})" if pmt.mode else ""),
            debit=float(pmt.amount) if pmt.voucher_type == "payment" else 0.0,
            credit=float(pmt.amount) if pmt.voucher_type == "receipt" else 0.0,
        ))
    entries.sort(key=lambda e: _make_aware(e.date))

    period_debit = sum(e.debit for e in entries)
    period_credit = sum(e.credit for e in entries)
    opening_debit = float(opening_totals[0]) + float(opening_payment_totals[0])
    opening_credit = float(opening_totals[1]) + float(opening_payment_totals[1])
    opening_balance = opening_debit - opening_credit
    closing_balance = opening_balance + period_debit - period_credit

    html_pdf = _build_statement_html(
        ledger=ledger,
        company=company,
        from_date=payload.from_date,
        to_date=payload.to_date,
        opening_balance=opening_balance,
        period_debit=period_debit,
        period_credit=period_credit,
        closing_balance=closing_balance,
        entries=entries,
        currency=currency_code,
    )
    pdf_bytes: bytes = weasyprint.HTML(string=html_pdf).write_pdf() or b""

    # Summarise invoice debits and payment credits separately for the email body
    total_invoiced = sum(e.debit for e in entries if e.entry_type == "invoice")
    total_received = sum(e.credit for e in entries if e.entry_type == "payment")

    template = _jinja_env.get_template("ledger_statement.html")
    html_body = template.render(
        company_name=company.name if company else "",
        company_email=company.email if company else None,
        company_phone=company.phone_number if company else None,
        company_address=company.address if company else None,
        ledger_name=ledger.name,
        date_from=payload.from_date.strftime("%d %b %Y"),
        date_to=payload.to_date.strftime("%d %b %Y"),
        total_invoices=_fmt(total_invoiced),
        total_payments=_fmt(total_received),
        balance=_fmt(closing_balance),
        currency=_symbol(currency_code),
        message=payload.message,
    )

    safe_name = ledger.name.replace(" ", "_").replace("/", "_")[:30]
    filename = f"statement_{safe_name}_{payload.from_date}_{payload.to_date}.pdf"
    subject = payload.subject or f"Account Statement \u2014 {ledger.name}"
    cc_list = [payload.cc] if payload.cc else None

    try:
        await send_email(
            db=db,
            to=to_email,
            subject=subject,
            html_body=html_body,
            attachments=[(pdf_bytes, filename)],
            cc=cc_list,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"message": "Ledger statement email sent successfully"}


# ---------------------------------------------------------------------------
# POST /payment-reminder/{ledger_id}
# ---------------------------------------------------------------------------

@router.post("/payment-reminder/{ledger_id}")
async def send_payment_reminder_email(
    ledger_id: int,
    payload: EmailSendRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    if payload is None:
        payload = EmailSendRequest()

    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    to_email = payload.to or ledger.email
    if not to_email:
        raise HTTPException(
            status_code=400,
            detail="No recipient email address. Provide 'to' in the request body or add an email to the ledger.",
        )

    company = db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    currency_code = company.currency_code if company and company.currency_code else "INR"

    credit_note_summary = get_credit_note_ledger_summary(db, ledger_id=ledger_id)

    # Outstanding balance = active sales invoices − active sales credit notes − active receipts for this ledger
    total_sales = float(
        db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(Invoice.ledger_id == ledger_id, Invoice.voucher_type == "sales", Invoice.status == "active")
        .scalar()
    )
    total_receipts = float(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.ledger_id == ledger_id, Payment.voucher_type == "receipt", Payment.status == "active")
        .scalar()
    )
    outstanding_balance = total_sales - credit_note_summary.sales_credit_total - total_receipts

    last_payment = (
        db.query(Payment)
        .filter(Payment.ledger_id == ledger_id)
        .order_by(Payment.date.desc())
        .first()
    )
    last_payment_date = last_payment.date.strftime("%d %b %Y") if last_payment else None

    sales_invoices = (
        db.query(Invoice)
        .filter(Invoice.ledger_id == ledger_id, Invoice.voucher_type == "sales", Invoice.status == "active")
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        .all()
    )
    unpaid_invoices = []
    for inv in sales_invoices:
        net_amount = float(inv.total_amount) - credit_note_summary.sales_credit_by_invoice.get(inv.id, 0.0)
        if net_amount <= 0:
            continue
        unpaid_invoices.append(
            {
                "invoice_number": inv.invoice_number or f"#{inv.id}",
                "invoice_date": inv.invoice_date.strftime("%d %b %Y") if inv.invoice_date else "N/A",
                "due_date": inv.due_date.strftime("%d %b %Y") if inv.due_date else None,
                "amount": _fmt(net_amount),
            }
        )

    template = _jinja_env.get_template("payment_reminder.html")
    html_body = template.render(
        company_name=company.name if company else "",
        company_email=company.email if company else None,
        company_phone=company.phone_number if company else None,
        company_address=company.address if company else None,
        buyer_name=ledger.name,
        outstanding_balance=_fmt(outstanding_balance),
        currency=_symbol(currency_code),
        last_payment_date=last_payment_date,
        message=payload.message,
        unpaid_invoices=unpaid_invoices,
    )

    subject = payload.subject or f"Payment Reminder \u2014 {ledger.name}"
    cc_list = [payload.cc] if payload.cc else None

    try:
        await send_email(
            db=db,
            to=to_email,
            subject=subject,
            html_body=html_body,
            cc=cc_list,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"message": "Payment reminder sent successfully"}
