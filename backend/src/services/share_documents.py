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
from decimal import Decimal
from io import BytesIO

import weasyprint
from fastapi import HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from src.core.config import settings
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
from src.services.upi import UpiPaymentRequest, render_qr_png_data_uri, resolve_upi_payment

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
# Minting and addressing
# ---------------------------------------------------------------------------

def build_share_url(request: Request | None, token: str) -> str:
    """Absolute URL for a share token.

    ``PUBLIC_APP_BASE_URL`` is only trusted when it is already an https origin. It
    defaults to ``http://localhost:5173`` and several tenants never set it, so
    trusting it blindly would paste a localhost URL into a customer's WhatsApp
    thread — or, now, print one onto an invoice. When it is not usable we derive the
    origin from the request in hand, which is by definition a host that reached this
    deployment.

    ``request`` is optional because a PDF can be rendered from a background path with
    no request to derive from; there the configured base URL is all there is.
    """
    configured = (settings.PUBLIC_APP_BASE_URL or "").strip().rstrip("/")
    if configured.startswith("https://") or request is None:
        return f"{configured}/s/{token}"

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    scheme = forwarded_proto or request.url.scheme
    host = (request.headers.get("host") or "").strip() or request.url.netloc
    return f"{scheme}://{host}/s/{token}"


def _live_link_query(db: Session, company_id: int, resource_type: str, resource_id: int):
    return (
        db.query(ShareLink)
        .filter(
            ShareLink.company_id == company_id,
            ShareLink.resource_type == resource_type,
            ShareLink.resource_id == resource_id,
            ShareLink.revoked_at.is_(None),
        )
    )


def find_live_share_link(
    db: Session,
    company_id: int,
    resource_type: str,
    resource_id: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> ShareLink | None:
    return (
        _live_link_query(db, company_id, resource_type, resource_id)
        .filter(ShareLink.from_date == from_date, ShareLink.to_date == to_date)
        .first()
    )


def ensure_live_share_link(
    db: Session,
    company_id: int,
    resource_type: str,
    resource_id: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    user_id: int | None = None,
) -> tuple[ShareLink, bool]:
    """The live link for a document, minting one only if there is not one already.

    Returns ``(link, created)`` — the flag matters because only a genuinely new token
    is worth an analytics event, and this is called from paths (pressing Share twice,
    rendering the same PDF again) where nothing new happened.

    Idempotent by design: a second live token for one document would leave two URLs
    in circulation and make "revoke" only half work. The ``IntegrityError`` arm
    catches losing a race against the ``ux_share_links_live_resource`` partial unique
    index, where the other writer's link is just as good as ours.
    """
    existing = find_live_share_link(
        db, company_id, resource_type, resource_id, from_date=from_date, to_date=to_date
    )
    if existing is not None:
        return existing, False

    link = ShareLink(
        company_id=company_id,
        token=generate_token(),
        resource_type=resource_type,
        resource_id=resource_id,
        from_date=from_date,
        to_date=to_date,
        view_count=0,
        created_by_user_id=user_id,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = find_live_share_link(
            db, company_id, resource_type, resource_id, from_date=from_date, to_date=to_date
        )
        if existing is None:
            raise HTTPException(status_code=500, detail="Could not create share link")
        return existing, False

    db.refresh(link)
    return link, True


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
# Pay-online QR
# ---------------------------------------------------------------------------

# Appended to the URL a printed QR encodes. The share page reads it back into the
# page-view event, which is the only way to tell a scan off a printed invoice from a
# link somebody forwarded in a chat.
QR_ENTRY_MARKER = "?src=qr"


def document_share_url(
    db: Session,
    request: Request | None,
    company: CompanyProfile | None,
    resource_type: str,
    resource_id: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    user_id: int | None = None,
) -> str | None:
    """The URL a document's printed QR should point at, minting a link if needed.

    ``None`` means print no QR at all, which is the answer whenever share links are
    switched off for the deployment or the company has not opted in. That opt-in is
    the whole reason this is gated: turning it on means that printing an invoice
    starts creating a publicly reachable URL for it, and that is the owner's
    decision to make rather than a side effect of hitting Download.
    """
    if not settings.SHARE_LINKS_ENABLED:
        return None
    if company is None or not getattr(company, "show_pay_qr_on_invoice", False):
        return None

    link, _ = ensure_live_share_link(
        db,
        company.id,
        resource_type,
        resource_id,
        from_date=from_date,
        to_date=to_date,
        user_id=user_id,
    )
    return f"{build_share_url(request, link.token)}{QR_ENTRY_MARKER}"


def build_pay_qr_card_html(share_url: str | None) -> str:
    """The "Pay online" card for a document, or "" when there is nothing to print.

    Deliberately a QR of the *share page*, not of a ``upi://`` intent. A printed UPI
    QR is a snapshot: it carries whatever was outstanding on the day it was printed,
    never expires, and can be scanned and paid a second time a month later. A QR of
    the URL reprices itself on every open, and a settled invoice simply shows no pay
    button. It also sidesteps the Rs 2,000 ceiling NPCI applies to a QR *image* that
    was forwarded rather than scanned live — and invoices get forwarded constantly.
    """
    if not share_url:
        return ""

    # Deferred: pdf_templates imports nothing from this module today and the escape
    # helper is the only thing needed from it.
    from src.services.pdf_templates.builders import _build_pdf_pay_qr_card_html

    return _build_pdf_pay_qr_card_html(share_url, render_qr_png_data_uri(share_url))


def invoice_upi_payment(
    db: Session,
    invoice: Invoice,
    accounts: list[CompanyAccount],
) -> UpiPaymentRequest | None:
    """What is still owed on this invoice, as a UPI payment — or ``None``.

    The amount is the outstanding balance rather than the invoice total, so a part-paid
    invoice asks for the remainder and a settled one asks for nothing.
    ``build_invoice_payment_summaries`` already nets off both allocated receipts and
    active credit notes, and already floors the result at zero.
    """
    if invoice.voucher_type != "sales" or invoice.status != "active":
        return None

    summary = build_invoice_payment_summaries(db, [invoice]).get(invoice.id)
    if summary is None:
        return None

    number = invoice.invoice_number or str(invoice.id)
    return resolve_upi_payment(
        accounts=accounts,
        currency_code=invoice.company_currency_code,
        payee_fallback=invoice.company_name,
        amount=Decimal(str(summary.remaining_amount)),
        note=f"Invoice {number}",
        # Sanitised to bare alphanumerics inside resolve_upi_payment: NPCI declines a
        # transaction whose reference carries a special character, so "INV-26/0042"
        # has to reach the payer as "INV260042".
        ref=f"{number}",
    )


# ---------------------------------------------------------------------------
# HTML builders (also served to the desktop iframe) and their PDF wrappers
# ---------------------------------------------------------------------------

def _to_pdf(html: str) -> BytesIO:
    return BytesIO(weasyprint.HTML(string=html).write_pdf())


def invoice_bank_accounts(db: Session, company_id: int) -> list[CompanyAccount]:
    """The bank accounts an invoice prints, in the order it prints them.

    One query, shared by every renderer. It used to exist twice with different
    company filters — this one strict, the email path's also matching legacy
    ``company_id IS NULL`` rows — which meant the emailed copy of an invoice and the
    downloaded copy could show different bank cards, and would now be able to show
    different UPI addresses. Both callers use this.
    """
    return (
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


def build_invoice_html(
    db: Session,
    company_id: int,
    invoice_id: int,
    copies: int = 1,
    *,
    share_url: str | None = None,
) -> str:
    """The invoice document, identical for the owner and the customer.

    ``share_url``, when given, is rendered as a QR in the payment details block. It
    arrives already built rather than being minted here, because minting needs the
    request the URL's origin comes from and this function is deliberately request-free.
    """
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

    accounts = invoice_bank_accounts(db, company_id)

    serials = SerialManager(db).serials_for_invoice(invoice)
    company = _company(db, company_id)
    show_sku = company.show_sku_on_pdf if company else True

    return _build_multi_copy_invoice_html(
        invoice,
        products,
        accounts,
        copies,
        show_sku=show_sku,
        serials=serials,
        # Rendered once here, not inside the per-copy loop: a triplicate print would
        # otherwise encode the same QR three times.
        pay_qr_html=build_pay_qr_card_html(share_url),
    )


def render_invoice_pdf(
    db: Session,
    company_id: int,
    invoice_id: int,
    copies: int = 1,
    *,
    share_url: str | None = None,
) -> BytesIO:
    return _to_pdf(
        build_invoice_html(db, company_id, invoice_id, copies=copies, share_url=share_url)
    )


def build_statement_html(
    db: Session,
    company_id: int,
    ledger_id: int,
    from_date: date,
    to_date: date,
    *,
    share_url: str | None = None,
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
        pay_qr_html=build_pay_qr_card_html(share_url),
    )


def render_statement_pdf(
    db: Session,
    company_id: int,
    ledger_id: int,
    from_date: date,
    to_date: date,
    *,
    share_url: str | None = None,
) -> BytesIO:
    return _to_pdf(
        build_statement_html(db, company_id, ledger_id, from_date, to_date, share_url=share_url)
    )


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

    # The pay-by-UPI offer, or nothing. Appended with defaults because every field
    # above is passed positionally at some construction site, and all four are
    # optional in the real sense too: most documents have no offer to make.
    #
    # `upi_uri` is carried so the /upi redirect reuses this one resolution instead of
    # growing a second code path that could disagree with what the page displayed.
    # The template never renders it -- the button points at our own counting route.
    upi_uri: str | None = None
    upi_qr_data_uri: str | None = None
    upi_vpa: str | None = None
    upi_amount_label: str | None = None


def _upi_fields(payment: UpiPaymentRequest | None, currency: str) -> dict:
    """The four ShareSummary fields a UPI offer fills in, or all-None."""
    if payment is None:
        return {}
    uri = payment.uri()
    return {
        "upi_uri": uri,
        "upi_qr_data_uri": render_qr_png_data_uri(uri),
        "upi_vpa": payment.vpa,
        "upi_amount_label": _fmt_currency(float(payment.amount), currency),
    }


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
        invoice_currency = invoice.company_currency_code or currency
        # Only a live sales invoice with something still owed gets an offer; every
        # other case falls out of invoice_upi_payment as None.
        upi = _upi_fields(
            invoice_upi_payment(db, invoice, invoice_bank_accounts(db, link.company_id)),
            invoice_currency,
        )
        return ShareSummary(
            title=f"{label} {number}",
            party_name=invoice.ledger_name or (invoice.ledger.name if invoice.ledger else ""),
            # The snapshot wins: an invoice must keep showing the branding it was
            # issued under even if the company has since been renamed or rebranded.
            company_name=invoice.company_name or company_name,
            amount_label=_fmt_currency(float(invoice.total_amount or 0), invoice_currency),
            date_label=_fmt_date(invoice.invoice_date),
            pdf_filename=f"invoice_{invoice.invoice_number or invoice.id}.pdf",
            available=invoice.status != "cancelled",
            logo_data=invoice.company_logo_data or logo_data,
            logo_mime_type=invoice.company_logo_mime_type or logo_mime_type,
            **upi,
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
        # The same comparison drives the label and the offer, so the two can never
        # disagree: Dr means the party owes us and can pay; Cr means we owe them.
        suffix = " Dr" if closing >= 0 else " Cr"
        upi = _upi_fields(
            resolve_upi_payment(
                accounts=invoice_bank_accounts(db, link.company_id),
                currency_code=company.currency_code if company else None,
                payee_fallback=company_name,
                amount=Decimal(str(closing)) if closing > 0 else None,
                note=f"Statement {ledger.name or ''}",
                ref=f"L{ledger.id}",
            ),
            currency,
        )
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
            **upi,
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


def _link_share_url(db: Session, link: ShareLink, request: Request | None) -> str | None:
    """The QR destination for a document being rendered *from* a share link.

    Reuses the token in hand rather than minting, but still honours the company's
    opt-in: a tenant who has not switched the QR on should not find one on the copy
    their customer downloads either.
    """
    if not settings.SHARE_LINKS_ENABLED:
        return None
    company = _company(db, link.company_id)
    if company is None or not company.show_pay_qr_on_invoice:
        return None
    return f"{build_share_url(request, link.token)}{QR_ENTRY_MARKER}"


def render_share_pdf(db: Session, link: ShareLink, *, request: Request | None = None) -> BytesIO:
    """Render the PDF a share link points at.

    Never stamps the Simple Invoicing advertisement: the ad belongs on the landing
    page, not inside a document the recipient files with their accounts.

    Mints nothing. The link is already in hand, so the QR printed on this copy points
    back at the page it was downloaded from -- which is the right destination if the
    recipient forwards the PDF onward.
    """
    share_url = _link_share_url(db, link, request)
    if link.resource_type == RESOURCE_INVOICE:
        return render_invoice_pdf(db, link.company_id, link.resource_id, share_url=share_url)
    if link.resource_type == RESOURCE_STATEMENT:
        return render_statement_pdf(
            db, link.company_id, link.resource_id, link.from_date, link.to_date, share_url=share_url
        )
    if link.resource_type == RESOURCE_PAYMENT:
        return render_receipt_pdf(db, link.company_id, link.resource_id)
    raise HTTPException(status_code=404, detail="Not found")


def render_share_document_html(db: Session, link: ShareLink, *, request: Request | None = None) -> str:
    """The print-styled document HTML, for the desktop preview iframe.

    An HTML iframe renders everywhere; a PDF iframe does not (iOS Safari and
    Android WebView both fail at it), which is why the mobile path is the summary
    card plus the download button instead.
    """
    share_url = _link_share_url(db, link, request)
    if link.resource_type == RESOURCE_INVOICE:
        return build_invoice_html(db, link.company_id, link.resource_id, share_url=share_url)
    if link.resource_type == RESOURCE_STATEMENT:
        return build_statement_html(
            db, link.company_id, link.resource_id, link.from_date, link.to_date, share_url=share_url
        )
    if link.resource_type == RESOURCE_PAYMENT:
        return build_receipt_html(db, link.company_id, link.resource_id)
    raise HTTPException(status_code=404, detail="Not found")
