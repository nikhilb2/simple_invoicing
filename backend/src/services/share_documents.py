"""Document rendering shared by the authenticated app and the public share page.

The owner's copy and the customer's copy are produced by the *same* function on
purpose. Before this module the PDF-building code lived inside the three
authenticated route handlers, so a public renderer would have had to duplicate it —
and the two copies would have drifted the first time anyone tweaked a template.

Circular-import note
--------------------
``_build_receipt_html`` lives in ``src.api.routes.payments`` and
``_build_ledger_statement_data`` lives in ``src.api.routes.ledgers``. Both of those
route modules now import *this* module, so importing them at module scope here
would close a cycle. Moving the two helpers into ``src/services`` would be the
tidier fix, but ``_build_ledger_statement_data`` drags four private query helpers
and a dataclass with it, and ``src.api.routes.email`` plus ``tests/api/test_payments.py``
both import them from their current homes. The cheap, zero-blast-radius fix is a
deferred import inside the two functions that need them — the import graph stays
acyclic at module-import time and nothing outside this feature moves.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO

import weasyprint
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.company_account import CompanyAccount
from src.models.invoice import Invoice
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.models.product import Product
from src.models.share_link import ShareLink
from src.services.invoice_payments import build_invoice_payment_summaries
from src.services.pdf_templates import _build_multi_copy_invoice_html, _build_statement_html, _fmt_currency
from src.services.serial_service import SerialManager

RESOURCE_INVOICE = "invoice"
RESOURCE_STATEMENT = "ledger_statement"
RESOURCE_PAYMENT = "payment"
SHARE_RESOURCE_TYPES = (RESOURCE_INVOICE, RESOURCE_STATEMENT, RESOURCE_PAYMENT)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def generate_token() -> str:
    """A share token is the entire credential, so it has to be unguessable.

    24 random bytes -> 32 url-safe characters, comfortably inside the VARCHAR(64).
    """
    return secrets.token_urlsafe(24)


def resolve_share_link(db: Session, token: str) -> ShareLink | None:
    """Live links only. A revoked link is indistinguishable from a nonexistent one."""
    if not token:
        return None
    return (
        db.query(ShareLink)
        .filter(ShareLink.token == token, ShareLink.revoked_at.is_(None))
        .first()
    )


# ---------------------------------------------------------------------------
# Row lookups — every one filtered by company_id
# ---------------------------------------------------------------------------

def _company(db: Session, company_id: int) -> CompanyProfile | None:
    return db.query(CompanyProfile).filter(CompanyProfile.id == company_id).first()


def get_invoice(db: Session, company_id: int, invoice_id: int) -> Invoice | None:
    return (
        db.query(Invoice)
        .options(joinedload(Invoice.items), joinedload(Invoice.ledger))
        .filter(Invoice.id == invoice_id, Invoice.company_id == company_id)
        .first()
    )


def get_ledger(db: Session, company_id: int, ledger_id: int) -> Ledger | None:
    # The `company_id IS NULL` arm mirrors the authenticated ledger routes exactly:
    # pre-multi-company rows were never backfilled and are still reachable there.
    return (
        db.query(Ledger)
        .filter(Ledger.id == ledger_id)
        .filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
        .first()
    )


def get_payment(db: Session, company_id: int, payment_id: int, *, active_only: bool = True) -> Payment | None:
    filters = [Payment.id == payment_id]
    if active_only:
        filters.append(Payment.status == "active")
    filters.append(or_(Payment.company_id == company_id, Payment.company_id.is_(None)))
    return (
        db.query(Payment)
        .options(
            joinedload(Payment.ledger),
            joinedload(Payment.account),
            joinedload(Payment.invoice_allocations).joinedload(PaymentInvoiceAllocation.invoice),
        )
        .filter(*filters)
        .first()
    )


# ---------------------------------------------------------------------------
# HTML builders (also served to the desktop iframe) and their PDF wrappers
# ---------------------------------------------------------------------------

def _to_pdf(html: str) -> BytesIO:
    return BytesIO(weasyprint.HTML(string=html).write_pdf())


def build_invoice_html(db: Session, company_id: int, invoice_id: int, copies: int = 1) -> str:
    invoice = get_invoice(db, company_id, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    product_ids = [item.product_id for item in (invoice.items or [])]
    products = (
        db.query(Product)
        .filter(Product.id.in_(product_ids), Product.company_id == company_id)
        .all()
        if product_ids
        else []
    )

    invoice_bank_accounts = (
        db.query(CompanyAccount)
        .filter(
            CompanyAccount.is_active.is_(True),
            CompanyAccount.account_type == "bank",
            CompanyAccount.display_on_invoice.is_(True),
            CompanyAccount.company_id == company_id,
        )
        .order_by(CompanyAccount.display_name.asc(), CompanyAccount.id.asc())
        .all()
    )

    serials = SerialManager(db).serials_for_invoice(invoice)
    company = _company(db, company_id)
    show_sku = company.show_sku_on_pdf if company else True

    return _build_multi_copy_invoice_html(
        invoice, products, invoice_bank_accounts, copies, show_sku=show_sku, serials=serials
    )


def render_invoice_pdf(db: Session, company_id: int, invoice_id: int, copies: int = 1) -> BytesIO:
    return _to_pdf(build_invoice_html(db, company_id, invoice_id, copies=copies))


def build_statement_html(
    db: Session,
    company_id: int,
    ledger_id: int,
    from_date: date,
    to_date: date,
) -> str:
    # Deferred: see the circular-import note at the top of this module.
    from src.api.routes.ledgers import _build_ledger_statement_data

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    ledger = get_ledger(db, company_id, ledger_id)
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    company = _company(db, company_id)
    currency = company.currency_code if company and company.currency_code else "INR"

    statement_data = _build_ledger_statement_data(db, ledger, from_date, to_date, company_id=company_id)

    return _build_statement_html(
        ledger=ledger,
        company=company,
        from_date=from_date,
        to_date=to_date,
        opening_balance=statement_data.opening_balance,
        period_debit=statement_data.period_debit,
        period_credit=statement_data.period_credit,
        closing_balance=statement_data.closing_balance,
        entries=statement_data.entries,
        currency=currency,
    )


def render_statement_pdf(
    db: Session,
    company_id: int,
    ledger_id: int,
    from_date: date,
    to_date: date,
) -> BytesIO:
    return _to_pdf(build_statement_html(db, company_id, ledger_id, from_date, to_date))


def build_receipt_html(db: Session, company_id: int, payment_id: int) -> str:
    # Deferred: see the circular-import note at the top of this module.
    from src.api.routes.payments import _build_receipt_html

    payment = get_payment(db, company_id, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    company = _company(db, company_id)

    allocations_by_invoice_id = {
        allocation.invoice.id: allocation.invoice
        for allocation in payment.invoice_allocations
        if allocation.invoice is not None
    }
    invoice_summaries = build_invoice_payment_summaries(db, list(allocations_by_invoice_id.values()))
    allocation_status_by_invoice_id = {
        invoice_id: summary.payment_status
        for invoice_id, summary in invoice_summaries.items()
    }

    return _build_receipt_html(payment, company, allocation_status_by_invoice_id)


def render_receipt_pdf(db: Session, company_id: int, payment_id: int) -> BytesIO:
    return _to_pdf(build_receipt_html(db, company_id, payment_id))


# ---------------------------------------------------------------------------
# The public summary
# ---------------------------------------------------------------------------

@dataclass
class ShareSummary:
    """Everything the public page is allowed to know about a document.

    Deliberately not ``InvoiceOut``/``PaymentOut``: those carry line items, payment
    history, allocation rows and internal ids, none of which belong on a URL that
    anyone holding the token can open. The PDF is the detailed view; this is the
    preview card and the Open Graph payload.
    """

    title: str
    party_name: str
    company_name: str
    amount_label: str
    date_label: str
    pdf_filename: str
    available: bool
    logo_data: str | None
    logo_mime_type: str | None


def _fmt_date(value: date | datetime | None) -> str:
    return value.strftime("%d %b %Y") if value else ""


def _safe_ledger_slug(name: str | None) -> str:
    return (name or "ledger").replace(" ", "_").replace("/", "_")[:30]


def build_share_summary(db: Session, link: ShareLink) -> ShareSummary | None:
    """Summarise the linked document.

    Returns ``None`` when the underlying row is gone entirely (a dangling token —
    the caller answers with the same uniform 404 it gives an unknown token, so a
    deleted document never confirms that its token once existed). Returns a summary
    with ``available=False`` when the row is there but cancelled or inactive, which
    is the case that gets the "no longer available" page.
    """
    company = _company(db, link.company_id)
    company_name = company.name if company else ""
    logo_data = company.logo_data if company else None
    logo_mime_type = company.logo_mime_type if company else None
    currency = (company.currency_code if company and company.currency_code else "INR")

    if link.resource_type == RESOURCE_INVOICE:
        invoice = get_invoice(db, link.company_id, link.resource_id)
        if invoice is None:
            return None
        label = "Purchase Invoice" if invoice.voucher_type == "purchase" else "Invoice"
        number = invoice.invoice_number or f"#{invoice.id}"
        return ShareSummary(
            title=f"{label} {number}",
            party_name=invoice.ledger_name or (invoice.ledger.name if invoice.ledger else ""),
            # The snapshot wins: an invoice must keep showing the branding it was
            # issued under even if the company has since been renamed or rebranded.
            company_name=invoice.company_name or company_name,
            amount_label=_fmt_currency(
                float(invoice.total_amount or 0),
                invoice.company_currency_code or currency,
            ),
            date_label=_fmt_date(invoice.invoice_date),
            pdf_filename=f"invoice_{invoice.invoice_number or invoice.id}.pdf",
            available=invoice.status != "cancelled",
            logo_data=invoice.company_logo_data or logo_data,
            logo_mime_type=invoice.company_logo_mime_type or logo_mime_type,
        )

    if link.resource_type == RESOURCE_STATEMENT:
        ledger = get_ledger(db, link.company_id, link.resource_id)
        if ledger is None:
            return None
        from_date = link.from_date
        to_date = link.to_date
        if from_date is None or to_date is None:
            return None
        # Deferred: see the circular-import note at the top of this module.
        from src.api.routes.ledgers import _build_ledger_statement_data

        statement_data = _build_ledger_statement_data(
            db, ledger, from_date, to_date, company_id=link.company_id
        )
        closing = statement_data.closing_balance
        suffix = " Dr" if closing >= 0 else " Cr"
        return ShareSummary(
            title="Account Statement",
            party_name=ledger.name or "",
            company_name=company_name,
            amount_label=_fmt_currency(abs(closing), currency) + suffix,
            date_label=f"{_fmt_date(from_date)} – {_fmt_date(to_date)}",
            pdf_filename=f"statement_{_safe_ledger_slug(ledger.name)}_{from_date}_{to_date}.pdf",
            available=True,
            logo_data=logo_data,
            logo_mime_type=logo_mime_type,
        )

    if link.resource_type == RESOURCE_PAYMENT:
        payment = get_payment(db, link.company_id, link.resource_id, active_only=False)
        if payment is None:
            return None
        label = "Receipt" if payment.voucher_type == "receipt" else "Payment"
        number = payment.payment_number or f"#{payment.id}"
        return ShareSummary(
            title=f"{label} {number}",
            party_name=payment.ledger.name if payment.ledger else "",
            company_name=company_name,
            amount_label=_fmt_currency(float(payment.amount or 0), currency),
            date_label=_fmt_date(payment.date),
            pdf_filename=f"receipt_{payment.payment_number or payment.id}.pdf",
            available=payment.status == "active",
            logo_data=logo_data,
            logo_mime_type=logo_mime_type,
        )

    return None


def render_share_pdf(db: Session, link: ShareLink) -> BytesIO:
    """Render the PDF a share link points at.

    Never stamps the Simple Invoicing advertisement: the ad belongs on the landing
    page, not inside a document the recipient files with their accounts.
    """
    if link.resource_type == RESOURCE_INVOICE:
        return render_invoice_pdf(db, link.company_id, link.resource_id)
    if link.resource_type == RESOURCE_STATEMENT:
        return render_statement_pdf(db, link.company_id, link.resource_id, link.from_date, link.to_date)
    if link.resource_type == RESOURCE_PAYMENT:
        return render_receipt_pdf(db, link.company_id, link.resource_id)
    raise HTTPException(status_code=404, detail="Not found")


def render_share_document_html(db: Session, link: ShareLink) -> str:
    """The print-styled document HTML, for the desktop preview iframe.

    An HTML iframe renders everywhere; a PDF iframe does not (iOS Safari and
    Android WebView both fail at it), which is why the mobile path is the summary
    card plus the download button instead.
    """
    if link.resource_type == RESOURCE_INVOICE:
        return build_invoice_html(db, link.company_id, link.resource_id)
    if link.resource_type == RESOURCE_STATEMENT:
        return build_statement_html(db, link.company_id, link.resource_id, link.from_date, link.to_date)
    if link.resource_type == RESOURCE_PAYMENT:
        return build_receipt_html(db, link.company_id, link.resource_id)
    raise HTTPException(status_code=404, detail="Not found")
