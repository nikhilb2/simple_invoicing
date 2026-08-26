"""Idempotent invoice posting for marketplace orders.

This module is deliberately the *only* place that creates invoices from
marketplace data, and it is never called from event ingestion. Draining events
only advances order state; posting is a separate, independently retryable pass
keyed off ``marketplace_orders.posting_state``. That split is what makes the
whole pipeline crash-safe — if the process dies mid-post the cursor is already
committed for the event, but the order row is still ``pending``, so the next
drain retries the post.

Three independent idempotency layers guard against a double invoice: the event
ledger (sync.py), ``UNIQUE (company_id, remote_order_id)``, and the conditional
state transition claimed here.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from src.core.validation import normalize_gstin
from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.marketplace import (
    MarketplaceConnection,
    MarketplaceLedgerLink,
    MarketplaceListing,
    MarketplaceOrder,
    MarketplaceProductLink,
)
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from src.services.financial_year import get_active_fy, get_fy_for_date
from src.services.inventory_service import InventoryManager
from src.services.invoice_processor import InvoiceProcessor

logger = logging.getLogger(__name__)

MAX_POSTING_ATTEMPTS = 5
POSTING_LOCK_SECONDS = 120

# Failures that will never succeed on a retry. Retrying them burns the attempt
# budget and hides the real problem behind "attempt 5 of 5".
PERMANENT_ERRORS = {
    "no_financial_year",
    "no_posting_user",
    "invalid_counterparty_gstin",
    "payload_diverged_from_order",
    "unknown_listing",
    "no_order_items",
    "serial_tracked_product",
}


class PostingError(Exception):
    """A posting attempt failed with a classified reason code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code

    @property
    def permanent(self) -> bool:
        return self.code in PERMANENT_ERRORS


def _dec(value) -> Decimal:
    """Parse a wire value into Decimal. The contract transports money and
    quantities as strings precisely so this never round-trips through float."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


# ---------------------------------------------------------------------------
# Counterparty ledger
# ---------------------------------------------------------------------------

def resolve_counterparty_ledger(
    db: Session, connection: MarketplaceConnection, order: MarketplaceOrder
) -> Ledger:
    """Find-or-create the local ledger for the order's counterparty.

    The lookup by GSTIN is mandatory before creating: ``ux_buyers_company_id_gst``
    makes a blind insert raise. We also cannot go through the ledgers route,
    which 400s on a duplicate GST.
    """
    try:
        gstin = normalize_gstin(order.counterparty_gstin)
    except ValueError as exc:
        raise PostingError("invalid_counterparty_gstin", str(exc)) from exc
    if not gstin:
        # A missing GSTIN must never be treated as an intrastate supply —
        # is_interstate_supply() returns False when either side is blank, which
        # would silently book CGST/SGST on an interstate sale.
        raise PostingError(
            "invalid_counterparty_gstin", "Counterparty GSTIN is missing"
        )

    remote_id = order.counterparty_remote_id
    if remote_id:
        link = (
            db.query(MarketplaceLedgerLink)
            .filter(
                MarketplaceLedgerLink.company_id == connection.company_id,
                MarketplaceLedgerLink.remote_seller_id == remote_id,
            )
            .first()
        )
        if link:
            ledger = db.query(Ledger).filter(Ledger.id == link.ledger_id).first()
            if ledger:
                return ledger

    ledger = (
        db.query(Ledger)
        .filter(Ledger.company_id == connection.company_id, Ledger.gst == gstin)
        .first()
    )
    if ledger is None:
        ledger = Ledger(
            company_id=connection.company_id,
            name=order.counterparty_name or gstin,
            # Both NOT NULL and normally typed by a human.
            address=order.counterparty_address or "—",
            gst=gstin,
            phone_number=order.counterparty_phone or "",
            email=order.counterparty_email,
        )
        db.add(ledger)
        db.flush()

    if remote_id:
        db.add(
            MarketplaceLedgerLink(
                company_id=connection.company_id,
                remote_seller_id=remote_id,
                ledger_id=ledger.id,
            )
        )
        db.flush()
    return ledger


# ---------------------------------------------------------------------------
# Product resolution (buyer side)
# ---------------------------------------------------------------------------

def _unique_sku(db: Session, company_id: int, base: str) -> str:
    """Return *base*, or base-2/base-3… against ux_products_company_id_sku."""
    candidate = base[:64]
    suffix = 1
    while (
        db.query(Product)
        .filter(Product.company_id == company_id, Product.sku == candidate)
        .first()
        is not None
    ):
        suffix += 1
        candidate = f"{base[:60]}-{suffix}"
    return candidate


def resolve_buyer_product(
    db: Session, connection: MarketplaceConnection, item
) -> Product:
    """Find the linked local product for a purchased listing, or create one.

    The link row is always written so a repeat purchase from the same listing
    reuses the product. A later "link to existing product" remap only affects
    *future* orders — posted accounting is never rewritten.
    """
    company_id = connection.company_id
    remote_listing_id = item.remote_listing_id

    if remote_listing_id:
        link = (
            db.query(MarketplaceProductLink)
            .filter(
                MarketplaceProductLink.company_id == company_id,
                MarketplaceProductLink.remote_listing_id == remote_listing_id,
            )
            .first()
        )
        if link:
            product = db.query(Product).filter(Product.id == link.product_id).first()
            if product:
                return product

    price = _dec(item.unit_price)
    product = Product(
        # company_id is nullable and every product query does
        # or_(company_id == X, is_(None)), so an unset one leaks across tenants.
        company_id=company_id,
        sku=_unique_sku(db, company_id, f"MKT-{remote_listing_id or 'ITEM'}"),
        name=item.title or f"Marketplace item {remote_listing_id}",
        hsn_sac=item.hsn_sac,
        price=price,
        purchase_price=price,
        gst_rate=_dec(item.gst_rate),
        unit=item.unit or "Pieces",
        # Permissive: never reject the seller's quantity on a rounding rule the
        # buyer happens to have set.
        allow_decimal=True,
        maintain_inventory=True,
    )
    db.add(product)
    db.flush()

    if remote_listing_id:
        db.add(
            MarketplaceProductLink(
                company_id=company_id,
                remote_listing_id=remote_listing_id,
                product_id=product.id,
            )
        )
        db.flush()
    return product


def resolve_seller_product(
    db: Session, connection: MarketplaceConnection, item
) -> Product:
    """Resolve the local product behind a sold listing via marketplace_listings."""
    if item.product_id:
        product = (
            db.query(Product)
            .filter(
                Product.id == item.product_id,
                or_(Product.company_id == connection.company_id, Product.company_id.is_(None)),
            )
            .first()
        )
        if product:
            return product

    listing = (
        db.query(MarketplaceListing)
        .filter(
            MarketplaceListing.company_id == connection.company_id,
            MarketplaceListing.remote_listing_id == item.remote_listing_id,
        )
        .first()
    )
    if listing is None:
        raise PostingError(
            "unknown_listing",
            f"No local listing for {item.remote_listing_id}",
        )
    product = db.query(Product).filter(Product.id == listing.product_id).first()
    if product is None:
        raise PostingError(
            "unknown_listing", f"Listing {item.remote_listing_id} has no local product"
        )
    return product


# ---------------------------------------------------------------------------
# The mandatory divergence check
# ---------------------------------------------------------------------------

def validate_posted_payload(order: MarketplaceOrder, payload: dict) -> None:
    """Compare a seller's ``order.posted`` payload against the order we hold.

    Without this a compromised central server can inject a fabricated purchase
    invoice into any instance that ever placed an order. Contract §6.3 makes it
    mandatory, not advisory.
    """
    expected_gstin = (order.counterparty_gstin or "").strip().upper()
    reported_gstin = str(payload.get("seller_gstin") or "").strip().upper()
    if expected_gstin and reported_gstin and expected_gstin != reported_gstin:
        raise PostingError(
            "payload_diverged_from_order",
            f"seller_gstin {reported_gstin} != {expected_gstin}",
        )

    lines = payload.get("lines") or []
    held = {item.line_no: item for item in order.items}
    if len(lines) != len(held):
        raise PostingError(
            "payload_diverged_from_order",
            f"line count {len(lines)} != {len(held)}",
        )

    for line in lines:
        line_no = int(line.get("line_no") or 0)
        item = held.get(line_no)
        if item is None:
            raise PostingError(
                "payload_diverged_from_order", f"unknown line_no {line_no}"
            )
        if str(line.get("listing_id") or "") != str(item.remote_listing_id or ""):
            raise PostingError(
                "payload_diverged_from_order",
                f"line {line_no} listing_id diverged",
            )
        if _dec(line.get("quantity")) != _dec(item.quantity):
            raise PostingError(
                "payload_diverged_from_order",
                f"line {line_no} quantity {line.get('quantity')} != {item.quantity}",
            )
        if _dec(line.get("unit_price")) != _dec(item.unit_price):
            raise PostingError(
                "payload_diverged_from_order",
                f"line {line_no} unit_price {line.get('unit_price')} != {item.unit_price}",
            )


# ---------------------------------------------------------------------------
# Claim / release
# ---------------------------------------------------------------------------

def claim_order_for_posting(db: Session, order_id: int) -> bool:
    """Claim an order for posting with a conditional UPDATE.

    Not an ORM assignment: two workers reading ``posting_state == 'pending'``
    and both writing ``'posting'`` would each post an invoice. ``rowcount == 0``
    means somebody else already holds it.
    """
    now = datetime.utcnow()
    result = db.execute(
        text(
            """
            UPDATE marketplace_orders
               SET posting_state = 'posting',
                   posting_lock_until = :lock_until,
                   posting_attempts = posting_attempts + 1
             WHERE id = :id
               AND posting_state = 'pending'
            """
        ),
        {"id": order_id, "lock_until": now + timedelta(seconds=POSTING_LOCK_SECONDS)},
    )
    claimed = result.rowcount == 1
    db.commit()
    return claimed


def reclaim_stale_posting_locks(db: Session, company_id: int) -> int:
    """Return orders abandoned mid-post to ``pending``.

    Only safe when ``posted_invoice_id IS NULL`` — otherwise the invoice exists
    and the row simply never recorded it, which a second post would duplicate.
    """
    result = db.execute(
        text(
            """
            UPDATE marketplace_orders
               SET posting_state = 'pending', posting_lock_until = NULL
             WHERE company_id = :company_id
               AND posting_state = 'posting'
               AND posted_invoice_id IS NULL
               AND posting_lock_until IS NOT NULL
               AND posting_lock_until < :now
            """
        ),
        {"company_id": company_id, "now": datetime.utcnow()},
    )
    db.commit()
    return result.rowcount or 0


def _resolve_posting_user(db: Session, connection: MarketplaceConnection) -> int:
    """``Invoice.created_by`` is NOT NULL and normally comes from the request."""
    if connection.created_by_user_id:
        user = db.query(User).filter(User.id == connection.created_by_user_id).first()
        if user:
            return user.id
    admin = db.query(User).filter(User.role == UserRole.admin).order_by(User.id.asc()).first()
    if admin:
        return admin.id
    raise PostingError("no_posting_user", "No user available to own the invoice")


def _resolve_financial_year(db: Session, company_id: int, when: date):
    """Never auto-create a financial year — that is an accounting decision."""
    active_fy = get_active_fy(db, company_id=company_id)
    fy = get_fy_for_date(db, when, company_id=company_id) or active_fy
    if fy is None:
        raise PostingError(
            "no_financial_year", f"No financial year covers {when.isoformat()}"
        )
    return fy, active_fy


def _order_date(order: MarketplaceOrder) -> date:
    placed = order.order_placed_at or order.accepted_at or datetime.utcnow()
    return placed.date() if isinstance(placed, datetime) else placed


# ---------------------------------------------------------------------------
# The two posting paths
# ---------------------------------------------------------------------------

def _build_and_apply(
    db: Session,
    connection: MarketplaceConnection,
    order: MarketplaceOrder,
    company: CompanyProfile,
    *,
    voucher_type: str,
    products_by_line: dict[int, Product],
) -> Invoice:
    # Marketplace orders post with nobody at the keyboard, so there is no one to
    # scan the IMEIs. Posting one anyway would move stock with no serials behind
    # it and break the invariant that a tracked product's quantity equals its
    # in-stock serial count — so it is refused and left for a human instead.
    for line_no in sorted(products_by_line):
        product = products_by_line[line_no]
        if product.track_serials:
            raise PostingError(
                "serial_tracked_product",
                f"{product.name} is serial-tracked and must be invoiced manually",
            )

    ledger = resolve_counterparty_ledger(db, connection, order)
    when = _order_date(order)
    fy, active_fy = _resolve_financial_year(db, connection.company_id, when)
    user_id = _resolve_posting_user(db, connection)

    items = [
        InvoiceItemCreate(
            product_id=products_by_line[item.line_no].id,
            quantity=float(item.quantity),
            unit_price=float(item.unit_price),
            # The seller's rate and HSN, not the local product master: the two
            # legally-linked invoices must agree on tax to the paisa.
            gst_rate=float(item.gst_rate or 0),
            hsn_sac=item.hsn_sac,
            description=item.title,
        )
        for item in order.items
    ]

    payload = InvoiceCreate(
        ledger_id=ledger.id,
        voucher_type=voucher_type,
        invoice_date=when,
        supplier_invoice_number=(
            order.seller_invoice_number if voucher_type == "purchase" else None
        ),
        reference_notes=f"Marketplace order {order.remote_order_id}",
        # Forced on both sides. The contract defines unit_price as tax-exclusive,
        # and round-off applied on only one side would break the paisa match.
        tax_inclusive=False,
        apply_round_off=False,
        shipping_address_same_as_billing=True,
        items=items,
    )

    invoice = Invoice(total_amount=0, created_by=user_id, company_id=connection.company_id)
    db.add(invoice)
    db.flush()
    InvoiceProcessor(db).apply_payload(
        invoice,
        payload,
        company,
        created_by=user_id,
        financial_year_id=fy.id,
        active_financial_year_id=active_fy.id if active_fy else None,
    )
    return invoice


def post_sales_invoice(
    db: Session,
    connection: MarketplaceConnection,
    order: MarketplaceOrder,
    company: CompanyProfile,
) -> Invoice:
    products = {
        item.line_no: resolve_seller_product(db, connection, item) for item in order.items
    }
    return _build_and_apply(
        db, connection, order, company, voucher_type="sales", products_by_line=products
    )


def post_purchase_invoice(
    db: Session,
    connection: MarketplaceConnection,
    order: MarketplaceOrder,
    company: CompanyProfile,
) -> Invoice:
    products = {}
    for item in order.items:
        product = resolve_buyer_product(db, connection, item)
        products[item.line_no] = product
        # Remember the resolution so the Orders page can show what was booked.
        item.product_id = product.id
    return _build_and_apply(
        db, connection, order, company, voucher_type="purchase", products_by_line=products
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def post_order(
    db: Session,
    connection: MarketplaceConnection,
    order_id: int,
    *,
    force: bool = False,
) -> str:
    """Post a single order's invoice. Returns 'posted' | 'failed' | 'abandoned'.

    ``force`` is the manual Retry button: it flips a ``failed`` order back to
    ``pending`` and resets the attempt counter before claiming.
    """
    if force:
        db.execute(
            text(
                """
                UPDATE marketplace_orders
                   SET posting_state = 'pending', posting_attempts = 0,
                       posting_error = NULL, posting_lock_until = NULL
                 WHERE id = :id AND posted_invoice_id IS NULL
                   AND posting_state IN ('failed', 'skipped', 'posting')
                """
            ),
            {"id": order_id},
        )
        db.commit()

    if not claim_order_for_posting(db, order_id):
        return "abandoned"

    order = db.query(MarketplaceOrder).filter(MarketplaceOrder.id == order_id).first()
    if order is None:
        return "abandoned"

    company = (
        db.query(CompanyProfile)
        .filter(CompanyProfile.id == connection.company_id)
        .first()
    )

    try:
        if not order.items:
            raise PostingError("no_order_items", "Order has no line items")
        if order.side == "sell":
            invoice = post_sales_invoice(db, connection, order, company)
        else:
            invoice = post_purchase_invoice(db, connection, order, company)

        # Invoice creation and the posted-state write land in ONE transaction, so
        # there is no window where an invoice exists and the order doesn't know it.
        order.posting_state = "posted"
        order.posted_invoice_id = invoice.id
        order.posted_at = datetime.utcnow()
        order.posting_error = None
        order.posting_lock_until = None
        if order.remote_total_amount is not None:
            # The invoice is local truth; a mismatch is a badge, not a rollback.
            order.total_mismatch = _dec(invoice.total_amount) != _dec(
                order.remote_total_amount
            )
        db.commit()
        return "posted"
    except PostingError as exc:
        db.rollback()
        _record_failure(db, order_id, exc.code, exc.detail, permanent=exc.permanent)
        return "failed"
    except Exception as exc:  # noqa: BLE001 — any failure must leave a retryable row
        db.rollback()
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("marketplace: posting order %s failed: %s", order_id, detail)
        _record_failure(db, order_id, "posting_failed", str(detail), permanent=False)
        return "failed"


def _record_failure(
    db: Session, order_id: int, code: str, detail: str, *, permanent: bool
) -> None:
    order = db.query(MarketplaceOrder).filter(MarketplaceOrder.id == order_id).first()
    if order is None:
        return
    order.posting_error = f"{code}: {detail}"[:1000]
    order.posting_lock_until = None
    # A permanent error will never succeed; retrying it four more times only
    # hides the real cause behind "attempt 5 of 5".
    if permanent or order.posting_attempts >= MAX_POSTING_ATTEMPTS:
        order.posting_state = "failed"
    else:
        order.posting_state = "pending"
    db.commit()


def run_posting_reconciler(
    db: Session,
    connection: MarketplaceConnection,
    *,
    limit: int = 25,
) -> tuple[int, int]:
    """Post every pending order for this connection, oldest first.

    Returns ``(posted, failed)``. Runs as a pass wholly separate from event
    ingestion so a posting failure can never stall the cursor.
    """
    reclaim_stale_posting_locks(db, connection.company_id)

    order_ids = [
        row[0]
        for row in db.query(MarketplaceOrder.id)
        .filter(
            MarketplaceOrder.company_id == connection.company_id,
            MarketplaceOrder.posting_state == "pending",
        )
        .order_by(MarketplaceOrder.id.asc())
        .limit(limit)
        .all()
    ]

    posted = failed = 0
    for order_id in order_ids:
        outcome = post_order(db, connection, order_id)
        if outcome == "posted":
            posted += 1
        elif outcome == "failed":
            failed += 1
    return posted, failed


# ---------------------------------------------------------------------------
# Stock check at accept time — the real reservation
# ---------------------------------------------------------------------------

def seller_has_stock(
    db: Session, connection: MarketplaceConnection, order: MarketplaceOrder
) -> bool:
    """True when local stock covers every line of a sell-side order.

    The marketplace's advertised quantity is an advisory snapshot; this is the
    only authoritative check, and it must run *before* accepting so an
    unfulfillable order is rejected rather than accepted-and-failed.
    """
    inventory = InventoryManager(db)
    for item in order.items:
        try:
            product = resolve_seller_product(db, connection, item)
        except PostingError:
            return False
        if not product.maintain_inventory:
            continue
        try:
            inventory.check_availability(
                product.id,
                _dec(item.quantity),
                company_id=connection.company_id,
                product_name=product.name,
            )
        except Exception:
            return False
    return True


def build_posting_report(order: MarketplaceOrder, invoice: Invoice) -> dict:
    """The ``POST /orders/{id}/posting`` body — money as decimal strings."""
    lines = []
    invoice_items = list(invoice.items or [])
    for index, item in enumerate(order.items):
        booked = invoice_items[index] if index < len(invoice_items) else None
        lines.append(
            {
                "line_no": item.line_no,
                "listing_id": item.remote_listing_id,
                "title": item.title,
                "quantity": str(_dec(item.quantity)),
                "unit": item.unit,
                "unit_price": str(_dec(item.unit_price)),
                "gst_rate": str(_dec(item.gst_rate)),
                "hsn_sac": item.hsn_sac,
                "taxable_amount": str(_dec(booked.taxable_amount if booked else 0)),
                "tax_amount": str(_dec(booked.tax_amount if booked else 0)),
                "line_total": str(_dec(booked.line_total if booked else 0)),
            }
        )
    invoice_date = invoice.invoice_date
    return {
        "invoice_number": invoice.invoice_number,
        "invoice_date": (
            invoice_date.date().isoformat()
            if isinstance(invoice_date, datetime)
            else str(invoice_date)
        ),
        "currency_code": order.currency_code or "INR",
        "seller_gstin": invoice.company_gst,
        "taxable_amount": str(_dec(invoice.taxable_amount)),
        "tax_amount": str(_dec(invoice.total_tax_amount)),
        "total_amount": str(_dec(invoice.total_amount)),
        "lines": lines,
    }
