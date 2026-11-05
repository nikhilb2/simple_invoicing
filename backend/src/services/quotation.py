"""Quotations and proforma invoices: everything short of the PDF and the routes.

Nothing here touches stock, serials, ledgers, payments or the invoice series until
:func:`convert_quotation`, and that path goes through the same invoice creation as
any other sale. See the note at the top of ``src/models/quotation.py``.

These functions flush but never commit; the routes own the transaction. Every state
change locks the quotation row first. Lock order is always the quotation, then the
invoice, then the series and stock rows the invoice path touches, which is why the
invoice cancel and restore hooks take it before doing anything else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session

from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.ledger_address import LedgerAddress
from src.models.product import Product
from src.models.quotation import (
    DOCUMENT_PROFORMA,
    STATUS_ACCEPTED,
    STATUS_CANCELLED,
    STATUS_CONVERTED,
    STATUS_DECLINED,
    STATUS_EXPIRED,
    STATUS_OPEN,
    Quotation,
    QuotationItem,
)
from src.schemas.invoice import InvoiceItemCreate
from src.schemas.ledger_address import ShippingAddressInline
from src.schemas.quotation import (
    LATEST_DOCUMENT_DATE,
    ConversionWarning,
    QuotationConversionDraft,
    QuotationConvert,
    QuotationCreate,
    QuotationFields,
    QuotationItemCreate,
    QuotationStatusUpdate,
    QuotationUpdate,
)
from src.services.company_access import company_scope
from src.services.document_totals import apply_discount_and_round_off, require_money_fits, snapshot_company_fields
from src.services.financial_year import get_active_fy, get_fy_for_date
from src.services.gst_tax_service import (
    assign_invoice_tax_totals,
    assign_item_tax_split,
    india_today,
    is_interstate_supply,
    money as _money,
)
from src.services.invoice_creation import create_invoice_record
from src.services.invoice_processor import InvoiceProcessor
from src.services.series import generate_next_number

DEFAULT_VALIDITY_DAYS = 30

# Open or accepted can be edited, converted and cancelled. A declined one has to be
# reopened before anything but cancelling.
EDITABLE_STATUSES = (STATUS_OPEN, STATUS_ACCEPTED)
CANCELLABLE_STATUSES = (STATUS_OPEN, STATUS_ACCEPTED, STATUS_DECLINED)
STATUS_MOVES = {
    STATUS_OPEN: (STATUS_ACCEPTED, STATUS_DECLINED),
    STATUS_ACCEPTED: (STATUS_OPEN,),
    STATUS_DECLINED: (STATUS_OPEN,),
}


def document_label(document_type: str) -> str:
    return "Proforma invoice" if document_type == DOCUMENT_PROFORMA else "Quotation"


def display_status(quotation: Quotation, today: date) -> str:
    return STATUS_EXPIRED if quotation.is_expired_on(today) else quotation.status


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_quotation(db: Session, company_id: int, quotation_id: int, *, lock: bool = False) -> Quotation | None:
    """One quotation inside the company, optionally with its row locked.

    Never joinedload here: Postgres refuses FOR UPDATE across an outer join. Items
    load lazily afterwards. populate_existing because a lock is pointless if the
    session then answers from a copy it read before waiting for that lock.
    """
    query = db.query(Quotation).filter(Quotation.id == quotation_id, Quotation.company_id == company_id)
    if lock:
        query = query.populate_existing().with_for_update()
    return query.first()


def require_quotation(db: Session, company_id: int, quotation_id: int, *, lock: bool = False) -> Quotation:
    quotation = get_quotation(db, company_id, quotation_id, lock=lock)
    if quotation is None:
        raise HTTPException(status_code=404, detail=f"Quotation {quotation_id} not found")
    return quotation


def linked_invoices(db: Session, quotation_ids: list[int]) -> dict[int, list]:
    """Id, number and status of every invoice created from these quotations, oldest first."""
    if not quotation_ids:
        return {}
    rows = (
        db.query(Invoice.id, Invoice.source_quotation_id, Invoice.invoice_number, Invoice.status)
        .filter(Invoice.source_quotation_id.in_(quotation_ids))
        .order_by(Invoice.id)
        .all()
    )
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(row.source_quotation_id, []).append(row)
    return grouped


def _active_invoice(db: Session, quotation_id: int, *, excluding: int | None = None) -> Invoice | None:
    query = db.query(Invoice).filter(
        Invoice.source_quotation_id == quotation_id,
        Invoice.status == "active",
    )
    if excluding is not None:
        query = query.filter(Invoice.id != excluding)
    return query.first()


# ---------------------------------------------------------------------------
# Create and edit
# ---------------------------------------------------------------------------

def _apply_shipping(
    db: Session,
    quotation: Quotation,
    payload: QuotationFields,
    company_id: int,
    *,
    kept_snapshot: tuple[str, str] | None = None,
) -> None:
    """Snapshot the shipping address and remember which saved row it came from.

    kept_snapshot is a (label, address) already on the quote whose saved row has gone.
    Sending it back unchanged keeps it on the quote alone: it must not return to the
    ledger's list. Any other address typed in is genuinely new and gets a row.
    """
    quotation.shipping_address = None
    quotation.shipping_address_label = None
    quotation.shipping_address_id = None
    if payload.shipping_address_same_as_billing:
        return

    address = None
    if payload.shipping_address_id is not None:
        address = (
            db.query(LedgerAddress)
            .filter(
                LedgerAddress.id == payload.shipping_address_id,
                LedgerAddress.ledger_id == quotation.ledger_id,
                LedgerAddress.company_id == company_id,
            )
            .first()
        )
        if address is None:
            raise HTTPException(
                status_code=404,
                detail=f"Shipping address {payload.shipping_address_id} not found for this ledger",
            )
    elif (
        payload.new_shipping_address is not None
        and kept_snapshot is not None
        and kept_snapshot == (payload.new_shipping_address.label.strip(), payload.new_shipping_address.address.strip())
    ):
        quotation.shipping_address = kept_snapshot[1]
        quotation.shipping_address_label = kept_snapshot[0]
        return
    elif payload.new_shipping_address is not None:
        # Re-saving a quotation sends its address again; only a new one gets a row.
        address = (
            db.query(LedgerAddress)
            .filter(
                LedgerAddress.ledger_id == quotation.ledger_id,
                LedgerAddress.company_id == company_id,
                LedgerAddress.label == payload.new_shipping_address.label,
                LedgerAddress.address == payload.new_shipping_address.address,
            )
            .first()
        )
        if address is None:
            address = LedgerAddress(
                ledger_id=quotation.ledger_id,
                company_id=company_id,
                label=payload.new_shipping_address.label,
                address=payload.new_shipping_address.address,
                is_default=False,
            )
            db.add(address)
            db.flush()

    if address is not None:
        quotation.shipping_address = address.address
        quotation.shipping_address_label = address.label
        quotation.shipping_address_id = address.id


def _reject_lines_conversion_would_refuse(validated: list[tuple]) -> None:
    """A serial-tracked product can only appear on one invoice line, in whole units.

    Quotes hold no serials, but a quote that can never convert as written is worth
    catching now rather than when the customer has already agreed to it.
    """
    seen: set[int] = set()
    for _, product, quantity in validated:
        if not product.track_serials:
            continue
        if product.id in seen:
            raise HTTPException(
                status_code=400,
                detail=f"{product.name} is serial-tracked and can only appear on one line",
            )
        seen.add(product.id)
        if quantity != quantity.to_integral_value():
            raise HTTPException(
                status_code=400,
                detail=f"{product.name} is serial-tracked, so its quantity must be a whole number",
            )


def _apply_payload(
    db: Session,
    quotation: Quotation,
    payload: QuotationFields,
    company: CompanyProfile,
    *,
    kept_snapshot: tuple[str, str] | None = None,
) -> None:
    """Snapshot the parties and price the lines, with the arithmetic invoices use."""
    processor = InvoiceProcessor(db)
    ledger = processor.require_ledger(payload.ledger_id, company.id)

    quotation.ledger_id = ledger.id
    quotation.ledger_name = ledger.name
    quotation.ledger_address = ledger.address
    quotation.ledger_gst = ledger.gst
    quotation.ledger_phone = ledger.phone_number
    snapshot_company_fields(quotation, company)
    quotation.reference_notes = payload.reference_notes
    quotation.tax_inclusive = payload.tax_inclusive
    quotation.apply_round_off = payload.apply_round_off
    _apply_shipping(db, quotation, payload, company.id, kept_snapshot=kept_snapshot)

    validated = processor.resolve_items(payload.items, company.id, document_label="Quotation")
    _reject_lines_conversion_would_refuse(validated)

    taxable_total = Decimal("0")
    items: list[QuotationItem] = []
    for result in processor.calculate_totals(validated, payload.tax_inclusive):
        require_money_fits(
            f"The total for {result['product'].name}",
            result["taxable_amount"],
            result["tax_amount"],
            result["line_total"],
        )
        taxable_total += result["taxable_amount"]
        schema = result["item_schema"]
        items.append(
            QuotationItem(
                product_id=result["product"].id,
                quantity=float(result["quantity_value"]),
                hsn_sac=result["product"].hsn_sac,
                unit_price=float(result["unit_price"]),
                gst_rate=float(result["gst_rate"]),
                taxable_amount=float(result["taxable_amount"]),
                tax_amount=float(result["tax_amount"]),
                line_total=float(result["line_total"]),
                description=schema.description,
                discount_type=schema.discount_type,
                discount_value=schema.discount_value,
            )
        )
    quotation.items = items

    taxable_total = _money(taxable_total)
    quotation.taxable_amount = float(taxable_total)
    # An estimate of the split, from the GSTINs as they stand. Conversion works it
    # out again from whatever they are by then.
    interstate = is_interstate_supply(quotation.company_gst, quotation.ledger_gst)
    assign_item_tax_split(items, interstate_supply=interstate)
    tax_total = assign_invoice_tax_totals(quotation, items, interstate_supply=interstate)
    apply_discount_and_round_off(
        quotation,
        _money(taxable_total + tax_total),
        payload.discount_type,
        payload.discount_value,
    )
    require_money_fits(
        "The total of this document",
        taxable_total,
        tax_total,
        Decimal(str(quotation.total_amount)),
    )


def create_quotation(
    db: Session,
    payload: QuotationCreate,
    *,
    created_by: int,
    company: CompanyProfile,
    kept_snapshot: tuple[str, str] | None = None,
) -> Quotation:
    """A new open quotation on its own number series. Moves nothing else."""
    quotation_date = payload.quotation_date or india_today()
    valid_until = payload.valid_until
    if "valid_until" not in payload.model_fields_set:
        valid_until = min(quotation_date + timedelta(days=DEFAULT_VALIDITY_DAYS), LATEST_DOCUMENT_DATE)
    elif valid_until is not None and valid_until < quotation_date:
        raise HTTPException(status_code=400, detail="valid_until must be on or after quotation_date")

    active_fy = get_active_fy(db, company_id=company.id)
    fy = get_fy_for_date(db, quotation_date, company_id=company.id) or active_fy
    fy_id = fy.id if fy else None

    quotation = Quotation(
        company_id=company.id,
        document_type=payload.document_type,
        status=STATUS_OPEN,
        quotation_date=quotation_date,
        valid_until=valid_until,
        financial_year_id=fy_id,
        created_by=created_by,
    )
    quotation.quotation_number = generate_next_number(
        db,
        payload.document_type,
        fy_id,
        quotation_date,
        active_fy.id if active_fy else None,
        company_id=company.id,
    )
    # Added only once the required columns are filled: the lookups in _apply_payload
    # would otherwise autoflush a half-built row.
    _apply_payload(db, quotation, payload, company, kept_snapshot=kept_snapshot)
    db.add(quotation)
    db.flush()
    return quotation


def _orphaned_snapshot(quotation: Quotation) -> tuple[str, str] | None:
    """The (label, address) a quote carries after the saved row it came from was deleted."""
    if quotation.shipping_address_id is not None or not quotation.shipping_address:
        return None
    # The form fills a blank label with "Shipping" before sending, so compare on that.
    return ((quotation.shipping_address_label or "Shipping").strip(), quotation.shipping_address.strip())


def update_quotation(db: Session, quotation: Quotation, payload: QuotationUpdate, *, company: CompanyProfile) -> Quotation:
    """Replace the fields and lines. The number and document type never change."""
    if quotation.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"A {quotation.status} {document_label(quotation.document_type).lower()} cannot be edited",
        )

    # An invoice cancelled earlier was for the offer as it stood then. After an edit,
    # restoring that invoice must not mark this quotation as converted, so the link ends
    # here and the invoice comes back on its own. Any save counts, even one that changes
    # nothing: telling those apart would mean comparing every field and line.
    db.query(Invoice).filter(
        Invoice.source_quotation_id == quotation.id,
        Invoice.company_id == company.id,
        Invoice.status == "cancelled",
    ).update({Invoice.source_quotation_id: None}, synchronize_session=False)

    quotation_date = payload.quotation_date or quotation.quotation_date
    valid_until = payload.valid_until if "valid_until" in payload.model_fields_set else quotation.valid_until
    if valid_until is not None and valid_until < quotation_date:
        raise HTTPException(status_code=400, detail="valid_until must be on or after quotation_date")
    if quotation_date != quotation.quotation_date:
        fy = get_fy_for_date(db, quotation_date, company_id=company.id)
        if fy is not None:
            quotation.financial_year_id = fy.id
    quotation.quotation_date = quotation_date
    quotation.valid_until = valid_until

    # Clear first: a delete-orphan replacement would otherwise flush inserts and
    # deletes in whichever order suits the unit of work.
    quotation.items = []
    db.flush()
    _apply_payload(db, quotation, payload, company, kept_snapshot=_orphaned_snapshot(quotation))
    quotation.updated_at = datetime.utcnow()
    db.flush()
    return quotation


def duplicate_quotation(db: Session, original: Quotation, *, created_by: int, company: CompanyProfile) -> Quotation:
    """A fresh open copy dated today, on the same validity span, at today's tax rates."""
    today = india_today()
    valid_until = None
    if original.valid_until is not None:
        # The span moves with the date, so a very long one would land past the limit.
        span = original.valid_until - original.quotation_date
        valid_until = today + min(span, LATEST_DOCUMENT_DATE - today)

    # A snapshot whose saved row has gone is still where the goods were going.
    shipping_id = original.shipping_address_id
    new_address = None
    if shipping_id is None and original.shipping_address:
        new_address = ShippingAddressInline(
            label=original.shipping_address_label or "Shipping",
            address=original.shipping_address,
        )
    fields = {
        "ledger_id": original.ledger_id,
        "document_type": original.document_type,
        "quotation_date": today,
        "valid_until": valid_until,
        "reference_notes": original.reference_notes,
        "tax_inclusive": original.tax_inclusive,
        "apply_round_off": original.apply_round_off,
        "discount_type": original.discount_type,
        "discount_value": float(original.discount_value) if original.discount_value is not None else None,
        "shipping_address_same_as_billing": shipping_id is None and new_address is None,
        "shipping_address_id": shipping_id,
        "new_shipping_address": new_address,
        "items": [
            QuotationItemCreate(
                product_id=item.product_id,
                quantity=float(item.quantity),
                unit_price=float(item.unit_price),
                description=item.description,
                discount_type=item.discount_type,
                discount_value=float(item.discount_value) if item.discount_value is not None else None,
            )
            for item in original.items
        ],
    }
    return create_quotation(
        db,
        QuotationCreate(**fields),
        created_by=created_by,
        company=company,
        kept_snapshot=_orphaned_snapshot(original),
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def set_quotation_status(quotation: Quotation, payload: QuotationStatusUpdate) -> str:
    """Accept, decline or reopen. Returns the status it moved from."""
    previous = quotation.status
    if payload.status not in STATUS_MOVES.get(previous, ()):
        raise HTTPException(status_code=400, detail=f"Cannot move from {previous} to {payload.status}")

    now = datetime.utcnow()
    quotation.status = payload.status
    quotation.status_note = payload.note
    if payload.status == STATUS_ACCEPTED:
        quotation.accepted_at = now
        quotation.declined_at = None
    elif payload.status == STATUS_DECLINED:
        quotation.declined_at = now
        quotation.accepted_at = None
    else:
        # Reopening takes back the customer's answer. accepted_at has to go with it:
        # cancelling a later invoice restores "accepted" from it.
        quotation.accepted_at = None
        quotation.declined_at = None
    quotation.updated_at = now
    return previous


def cancel_quotation(db: Session, quotation: Quotation) -> None:
    if quotation.status == STATUS_CANCELLED:
        raise HTTPException(status_code=400, detail="Quotation is already cancelled")
    if quotation.status == STATUS_CONVERTED or _active_invoice(db, quotation.id) is not None:
        raise HTTPException(
            status_code=400,
            detail="This quotation has a live invoice. Cancel the invoice first.",
        )
    if quotation.status not in CANCELLABLE_STATUSES:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"Cannot cancel a {quotation.status} quotation")
    quotation.status = STATUS_CANCELLED
    quotation.cancelled_at = datetime.utcnow()
    quotation.updated_at = quotation.cancelled_at


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def already_converted_error(quotation: Quotation, invoice: Invoice | None) -> HTTPException:
    """The 409 a second conversion gets, naming the invoice that already exists."""
    number = invoice.invoice_number if invoice is not None else None
    return HTTPException(
        status_code=409,
        detail={
            "code": "quotation_already_converted",
            "message": (
                f"{quotation.quotation_number} was already converted to invoice {number}"
                if number
                else f"{quotation.quotation_number} was already converted to an invoice"
            ),
            "invoice_id": invoice.id if invoice is not None else None,
            "invoice_number": number,
        },
    )


def _require_convertible(db: Session, quotation: Quotation) -> None:
    if quotation.status == STATUS_CONVERTED:
        raise already_converted_error(quotation, _active_invoice(db, quotation.id))
    if quotation.status == STATUS_CANCELLED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "quotation_cancelled",
                "message": f"{quotation.quotation_number} is cancelled and cannot be converted",
            },
        )
    if quotation.status == STATUS_DECLINED:
        raise HTTPException(
            status_code=400,
            detail=f"{quotation.quotation_number} was declined. Reopen it before converting.",
        )
    # The status check and the row lock settle the normal race; this catches a live
    # invoice left against a quotation that somehow reads as open.
    existing = _active_invoice(db, quotation.id)
    if existing is not None:
        raise already_converted_error(quotation, existing)


def _require_same_version(quotation: Quotation, seen: datetime | None) -> None:
    """Refuse a draft read before the quotation last changed.

    Without this an old tab closes the edited quotation as converted, with an invoice
    for the old figures. What the user changes on the invoice itself is not looked at.
    """
    if seen is None:
        return
    # The column holds naive UTC; a caller may send the same instant with an offset.
    if seen.tzinfo is not None:
        seen = seen.astimezone(timezone.utc).replace(tzinfo=None)
    if seen != quotation.updated_at:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "quotation_changed",
                "message": (
                    f"{quotation.quotation_number} was changed after this conversion was opened, "
                    "so these figures may be out of date. Load the latest version and check it before saving."
                ),
            },
        )


def _fmt_rate(value: Decimal | float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _available_quantity(db: Session, product_id: int, company_id: int) -> Decimal:
    """Current stock for the early warning. The real check runs when the invoice is saved."""
    row = (
        db.query(Inventory)
        .filter(Inventory.product_id == product_id, company_scope(Inventory.company_id, company_id))
        .order_by(case((Inventory.company_id == company_id, 0), else_=1))
        .first()
    )
    return Decimal(str(row.quantity)) if row is not None else Decimal("0")


def _draft_warnings(
    db: Session,
    quotation: Quotation,
    products: dict[int, Product],
    company: CompanyProfile,
    today: date,
) -> list[ConversionWarning]:
    warnings: list[ConversionWarning] = []

    def warn(code: str, message: str) -> None:
        warnings.append(ConversionWarning(code=code, message=message))

    label = document_label(quotation.document_type)
    if quotation.is_expired_on(today):
        warn("expired", f"This {label.lower()} expired on {quotation.valid_until:%d %b %Y}. You can still convert it.")

    ledger = quotation.ledger
    was_interstate = is_interstate_supply(quotation.company_gst, quotation.ledger_gst)
    is_interstate = is_interstate_supply(company.gst, ledger.gst if ledger else None)
    if was_interstate != is_interstate:
        old, new = ("IGST", "CGST + SGST") if was_interstate else ("CGST + SGST", "IGST")
        warn(
            "tax_split_changed",
            f"Tax will now be {new} instead of {old}, because a GSTIN has changed since this was "
            "written. The tax heads change; the total tax stays the same apart from rounding.",
        )

    wanted: dict[int, Decimal] = {}
    for item in quotation.items:
        product = products.get(item.product_id)
        if product is None:
            continue
        quoted_rate = Decimal(str(item.gst_rate or 0))
        current_rate = Decimal(str(product.gst_rate or 0))
        if quoted_rate != current_rate:
            # The price stays as quoted, so which figure moves depends on whether
            # that price already includes tax.
            effect = (
                "The price includes GST, so the taxable value changes and the total stays the same, "
                "give or take rounding."
                if quotation.tax_inclusive
                else "The price is kept, so the total changes."
            )
            warn(
                "rate_changed",
                f"GST on {product.name} was {_fmt_rate(quoted_rate)}% and is now "
                f"{_fmt_rate(current_rate)}%. The invoice uses the current rate. {effect}",
            )
        if Decimal(str(product.price or 0)) != Decimal(str(item.unit_price or 0)):
            warn(
                "price_changed",
                f"{product.name} is now listed at {float(product.price or 0):,.2f}. The quoted "
                f"price of {float(item.unit_price or 0):,.2f} is kept; change it here if you need to.",
            )
        if (item.hsn_sac or None) != (product.hsn_sac or None):
            warn(
                "hsn_changed",
                f"HSN/SAC of {product.name} is now {product.hsn_sac or 'not set'}. The invoice uses the current code.",
            )
        quoted_quantity = Decimal(str(item.quantity))
        if not product.allow_decimal and quoted_quantity != quoted_quantity.to_integral_value():
            warn(
                "quantity_not_whole",
                f"{product.name} is now sold in whole numbers, but this quotes {quoted_quantity.normalize():f}. "
                "Change the quantity before saving.",
            )
        if product.track_serials:
            units = int(item.quantity)
            warn(
                "serials_required",
                f"{product.name} is serial-tracked. Scan the {units} unit{'' if units == 1 else 's'} "
                "going out before saving.",
            )
        if product.maintain_inventory:
            wanted[product.id] = wanted.get(product.id, Decimal("0")) + Decimal(str(item.quantity))

    for product_id, quantity in wanted.items():
        product = products[product_id]
        available = _available_quantity(db, product_id, company.id)
        if available < quantity:
            warn(
                "stock_shortfall",
                f"{product.name} has {_fmt_rate(available)} in stock and this needs {_fmt_rate(quantity)}. "
                "Update stock or change the quantity before saving.",
            )

    if quotation.shipping_address and not _usable_shipping_address_id(db, quotation, company.id):
        warn(
            "shipping_address_gone",
            "The shipping address on this document has since been deleted from the ledger. "
            "The invoice defaults to the billing address; choose another if needed.",
        )
    return warnings


def _usable_shipping_address_id(db: Session, quotation: Quotation, company_id: int) -> int | None:
    if quotation.shipping_address_id is None:
        return None
    exists = (
        db.query(LedgerAddress.id)
        .filter(
            LedgerAddress.id == quotation.shipping_address_id,
            LedgerAddress.ledger_id == quotation.ledger_id,
            LedgerAddress.company_id == company_id,
        )
        .first()
    )
    return quotation.shipping_address_id if exists else None


def build_conversion_draft(db: Session, quotation: Quotation, *, company: CompanyProfile) -> QuotationConversionDraft:
    """What the composer opens with, and what to look at before saving. Reads only."""
    _require_convertible(db, quotation)
    # The date a caller gets if it posts this straight back. The composer sends the
    # browser's date instead, as it does for any other invoice.
    today = india_today()

    product_ids ={item.product_id for item in quotation.items}
    products = {
        product.id: product
        for product in db.query(Product).filter(
            Product.id.in_(product_ids),
            company_scope(Product.company_id, company.id),
        )
    } if product_ids else {}

    # By id, never by copying the snapshot into new_shipping_address: that field
    # always inserts a row, so each conversion would add a duplicate address.
    shipping_id = _usable_shipping_address_id(db, quotation, company.id)
    reference = f"Against {document_label(quotation.document_type).lower()} {quotation.quotation_number}"
    if quotation.reference_notes:
        reference = f"{quotation.reference_notes} ({reference})"

    invoice = QuotationConvert(
        quotation_updated_at=quotation.updated_at,
        ledger_id=quotation.ledger_id,
        voucher_type="sales",
        invoice_date=today,
        reference_notes=reference,
        tax_inclusive=quotation.tax_inclusive,
        apply_round_off=quotation.apply_round_off,
        discount_type=quotation.discount_type,
        discount_value=float(quotation.discount_value) if quotation.discount_value is not None else None,
        shipping_address_same_as_billing=shipping_id is None,
        shipping_address_id=shipping_id,
        items=[
            InvoiceItemCreate(
                product_id=item.product_id,
                quantity=float(item.quantity),
                unit_price=float(item.unit_price),
                description=item.description,
                discount_type=item.discount_type,
                discount_value=float(item.discount_value) if item.discount_value is not None else None,
            )
            for item in quotation.items
        ],
    )
    return QuotationConversionDraft(
        quotation_id=quotation.id,
        quotation_number=quotation.quotation_number,
        document_type=quotation.document_type,
        invoice=invoice,
        warnings=_draft_warnings(db, quotation, products, company, today),
    )


def convert_quotation(
    db: Session,
    quotation_id: int,
    payload: QuotationConvert,
    *,
    created_by: int,
    company: CompanyProfile,
) -> tuple[Quotation, Invoice, list[str]]:
    """Create the invoice and close the quotation, in the caller's one transaction.

    The row lock serialises two conversions of one quotation: the second waits here,
    then reads ``converted`` and gets its 409. The partial unique index on
    ``invoices.source_quotation_id`` is the backstop for anything that gets past this.
    The invoice's stock check, serial validation and number all run inside the same
    transaction, so a failure leaves the quotation open and the counter unmoved.
    """
    if payload.voucher_type != "sales":
        raise HTTPException(status_code=400, detail="A quotation can only convert to a sales invoice")

    quotation = require_quotation(db, company.id, quotation_id, lock=True)
    _require_convertible(db, quotation)
    _require_same_version(quotation, payload.quotation_updated_at)

    invoice, warnings = create_invoice_record(
        db,
        payload,
        created_by=created_by,
        company=company,
        active_fy=get_active_fy(db, company_id=company.id),
    )
    invoice.source_quotation_id = quotation.id
    quotation.status = STATUS_CONVERTED
    quotation.converted_at = datetime.utcnow()
    quotation.updated_at = quotation.converted_at
    return quotation, invoice, warnings


# ---------------------------------------------------------------------------
# Hooks for the invoice routes
# ---------------------------------------------------------------------------

def lock_invoice_for_status_change(db: Session, invoice: Invoice) -> tuple[Invoice, Quotation | None]:
    """Lock an invoice and the quotation it came from, and read both as they now stand.

    Take this before moving any stock, then check the invoice's status on what it
    returns: the caller's copy was read before waiting, so a request queued behind
    another cancel or restore still sees the old status on it. The quotation comes
    first, as in conversion and every other quotation change, so no two of these can
    wait on each other.
    """
    quotation = None
    if invoice.source_quotation_id is not None:
        quotation = (
            db.query(Quotation)
            .filter(Quotation.id == invoice.source_quotation_id, Quotation.company_id == invoice.company_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
    locked = lock_invoice(db, invoice.id, invoice.company_id)
    if locked is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice.id} not found")
    # An edit of the quotation can unlink this invoice while it waits for that lock.
    if quotation is not None and locked.source_quotation_id != quotation.id:
        quotation = None
    return locked, quotation


def lock_invoice(db: Session, invoice_id: int, company_id: int | None) -> Invoice | None:
    """One invoice with its row locked, re-read. Never joinedload: see get_quotation."""
    return (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.company_id == company_id)
        .populate_existing()
        .with_for_update()
        .first()
    )


def reopen_after_invoice_cancelled(quotation: Quotation | None) -> None:
    """The deal is back on the table: an accepted quote returns to accepted, else open.

    The cancelled invoice keeps its link, so the history still shows it, until the
    quotation is next edited: see update_quotation.
    """
    if quotation is None or quotation.status != STATUS_CONVERTED:
        return
    quotation.status = STATUS_ACCEPTED if quotation.accepted_at else STATUS_OPEN
    quotation.converted_at = None
    quotation.updated_at = datetime.utcnow()


def require_restorable(db: Session, quotation: Quotation | None, invoice: Invoice) -> None:
    """Refuse to restore an invoice whose quotation has since been re-invoiced."""
    if quotation is None:
        return
    newer = _active_invoice(db, quotation.id, excluding=invoice.id)
    if newer is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "quotation_reinvoiced",
                "message": (
                    f"{quotation.quotation_number} was re-invoiced as {newer.invoice_number}. "
                    "Cancel that invoice first."
                ),
                "invoice_id": newer.id,
                "invoice_number": newer.invoice_number,
            },
        )


def close_after_invoice_restored(quotation: Quotation | None) -> None:
    """The invoice is live again, so its quotation is converted again.

    A quotation cancelled in the meantime stays cancelled: nobody asked to revive the
    offer, only the invoice. One declined in the meantime does not: a live invoice
    outranks that answer, and its decline would otherwise contradict the status.
    """
    if quotation is None or quotation.status == STATUS_CANCELLED:
        return
    quotation.status = STATUS_CONVERTED
    quotation.declined_at = None
    quotation.converted_at = datetime.utcnow()
    quotation.updated_at = quotation.converted_at
