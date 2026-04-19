from datetime import date
from pathlib import Path

import weasyprint
from fastapi import APIRouter, Body, Depends, HTTPException
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from src.api.deps import require_roles
from src.api.routes.invoices import _build_invoice_pdf
from src.api.routes.ledgers import _build_ledger_statement_data, _build_statement_html
from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.company_account import CompanyAccount
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.product import Product
from src.models.user import User, UserRole
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

    invoice_bank_accounts = (
        db.query(CompanyAccount)
        .filter(
            CompanyAccount.is_active.is_(True),
            CompanyAccount.account_type == "bank",
            CompanyAccount.display_on_invoice.is_(True),
        )
        .order_by(CompanyAccount.display_name.asc(), CompanyAccount.id.asc())
        .all()
    )

    pdf_buf = _build_invoice_pdf(invoice, products, invoice_bank_accounts)
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

    statement_data = _build_ledger_statement_data(db, ledger, payload.from_date, payload.to_date)

    html_pdf = _build_statement_html(
        ledger=ledger,
        company=company,
        from_date=payload.from_date,
        to_date=payload.to_date,
        opening_balance=statement_data.opening_balance,
        period_debit=statement_data.period_debit,
        period_credit=statement_data.period_credit,
        closing_balance=statement_data.closing_balance,
        entries=statement_data.entries,
        currency=currency_code,
    )
    pdf_bytes: bytes = weasyprint.HTML(string=html_pdf).write_pdf() or b""

    # Summarise invoice debits and payment credits separately for the email body
    total_invoiced = sum(entry.debit for entry in statement_data.entries if entry.entry_type == "invoice")
    total_received = sum(entry.credit for entry in statement_data.entries if entry.entry_type == "payment")

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
        balance=_fmt(statement_data.closing_balance),
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
        .filter(Payment.ledger_id == ledger_id, Payment.status == "active")
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
