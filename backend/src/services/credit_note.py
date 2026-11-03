from datetime import datetime, time
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.buyer import Buyer as Ledger
from src.models.credit_note import CreditNote, CreditNoteInvoiceRef, CreditNoteItem
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.schemas.credit_note import CreditNoteCreate, CreditNoteOut
from src.services.financial_year import get_active_fy, get_fy_for_date
from src.services.serial_service import SerialManager
from src.services.series import generate_next_number
from src.services.gst_tax_service import (
    company_state_code,
    default_place_of_supply,
    gstr1_section,
    india_today,
    invoice_is_interstate,
    money as _money,
)
from src.services.inventory_service import InventoryManager
from src.services.company_access import company_scope


def _return_note(credit_note_number: str) -> str:
    """The mark a return stamps on each unit it takes back.

    ``cancel_credit_note`` deletes the credit note row, so the serials it moved
    have to carry their own link back to it — this is what lets one of several
    returns against the same invoice be cancelled without disturbing the units
    the others brought in.
    """
    return f"Returned on credit note {credit_note_number}"


def _supplier_return_note(credit_note_number: str) -> str:
    """The mark a purchase return stamps on each unit it sends back.

    A separate namespace from `_return_note` so the two kinds of return can
    never reverse each other's units.
    """
    return f"Returned to supplier on credit note {credit_note_number}"


def _pro_rata(amount: Decimal, before: Decimal, quantity: int, whole: Decimal) -> Decimal:
    """A return's share of a line amount, given how many units earlier returns took.

    The difference of two running totals, so a line returned in parts adds back
    to exactly what it charged, however each part rounds.
    """
    return _money(amount * (before + quantity) / whole) - _money(amount * before / whole)


def _change_inventory_quantity(
    db: Session,
    product_id: int,
    quantity_delta: Decimal | int,
    *,
    context: str,
    company_id: int | None = None,
) -> None:
    inventory_query = db.query(Inventory).filter(Inventory.product_id == product_id)
    if company_id is not None:
        inventory_query = inventory_query.filter(company_scope(Inventory.company_id, company_id))
    inventory = inventory_query.first()
    if not inventory:
        inventory = Inventory(product_id=product_id, quantity=0, company_id=company_id)
        db.add(inventory)
        db.flush()

    inventory.quantity += quantity_delta
    if inventory.quantity < 0:
        raise HTTPException(status_code=400, detail=f"Insufficient inventory while {context}")


def _recompute_credit_status(invoice_id: int, db: Session, company_id: int | None = None) -> None:
    """Recalculate and persist credit_status for a single invoice."""
    invoice_query = db.query(Invoice).filter(Invoice.id == invoice_id)
    if company_id is not None:
        invoice_query = invoice_query.filter(company_scope(Invoice.company_id, company_id))
    invoice = invoice_query.first()
    if not invoice:
        return

    # Sum line_total of active CN items targeting this invoice
    from src.models.credit_note import CreditNoteItem as CNItem, CreditNote as CN

    result_query = (
        db.query(func.sum(CNItem.line_total))
        .join(CN, CN.id == CNItem.credit_note_id)
        .filter(
            CNItem.invoice_id == invoice_id,
            CN.status == "active",
        )
    )
    if company_id is not None:
        result_query = result_query.filter(company_scope(CN.company_id, company_id))
    result = result_query.scalar()
    credited_total = Decimal(str(result or 0))
    # line_total includes tax, so compare against total_amount (which also
    # includes tax) — taxable_amount excludes tax and would mark an invoice
    # fully credited too early. Fall back to taxable_amount for legacy rows
    # that never stored a total.
    invoice_total = Decimal(str(invoice.total_amount or invoice.taxable_amount or 0))

    if credited_total <= 0:
        invoice.credit_status = "not_credited"
    elif credited_total >= invoice_total:
        invoice.credit_status = "fully_credited"
    else:
        invoice.credit_status = "partially_credited"


def create_credit_note(
    payload: CreditNoteCreate,
    db: Session,
    current_user_id: int,
    company_id: int | None = None,
) -> CreditNote:
    # ── 1. Validate ledger ───────────────────────────────────────────────────
    ledger_query = db.query(Ledger).filter(Ledger.id == payload.ledger_id)
    if company_id is not None:
        ledger_query = ledger_query.filter(company_scope(Ledger.company_id, company_id))
    ledger = ledger_query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {payload.ledger_id} not found")

    # ── 2. Validate all invoices belong to this ledger ───────────────────────
    invoices_query = db.query(Invoice).filter(Invoice.id.in_(payload.invoice_ids))
    if company_id is not None:
        invoices_query = invoices_query.filter(company_scope(Invoice.company_id, company_id))
    invoices = invoices_query.all()
    found_ids = {inv.id for inv in invoices}
    missing = set(payload.invoice_ids) - found_ids
    if missing:
        raise HTTPException(status_code=404, detail=f"Invoices not found: {sorted(missing)}")

    wrong_ledger = [inv.id for inv in invoices if inv.ledger_id != payload.ledger_id]
    if wrong_ledger:
        raise HTTPException(
            status_code=400,
            detail=f"Invoices {wrong_ledger} do not belong to ledger {payload.ledger_id}",
        )

    cancelled_invoices = [inv.id for inv in invoices if inv.status == "cancelled"]
    if cancelled_invoices:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot credit cancelled invoices: {cancelled_invoices}",
        )

    # ── 2b. Settle which way the note runs ───────────────────────────────────
    # A note against a sales invoice is one we issued; a note against a
    # purchase is the supplier's own, and reverses input tax rather than
    # output. The two move stock in opposite directions and number out of
    # different series, so one note cannot be both. The `or "sales"` matters:
    # an Invoice built but never flushed has no column default applied yet.
    voucher_types = {(inv.voucher_type or "sales") for inv in invoices}
    if len(voucher_types) > 1:
        raise HTTPException(
            status_code=400,
            detail="A credit note cannot cover both sales and purchase invoices",
        )
    source_voucher_type = voucher_types.pop()
    direction = "inward" if source_voucher_type == "purchase" else "outward"
    if payload.direction != direction:
        raise HTTPException(
            status_code=400,
            detail=(
                f"These are {source_voucher_type} invoices, so this note must be "
                f"recorded as {direction}, not {payload.direction}"
            ),
        )

    if direction == "inward":
        # Recording the same supplier note twice reverses the input tax twice,
        # and nothing downstream would notice.
        supplier_number = payload.supplier_credit_note_number.strip()
        duplicate_query = (
            db.query(CreditNote.credit_note_number)
            .filter(
                CreditNote.ledger_id == payload.ledger_id,
                CreditNote.status == "active",
                func.upper(CreditNote.supplier_credit_note_number) == supplier_number.upper(),
            )
        )
        if company_id is not None:
            duplicate_query = duplicate_query.filter(
                company_scope(CreditNote.company_id, company_id)
            )
        duplicate = duplicate_query.first()
        if duplicate:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Supplier credit note {supplier_number} is already recorded "
                    f"for this ledger as {duplicate[0]}"
                ),
            )

    # One note carries one tax treatment, and GSTR-1 files it under one place of
    # supply, so it cannot span sales made to different states.
    places_of_supply = {
        inv.place_of_supply or default_place_of_supply(inv.company_gst, inv.ledger_gst)
        for inv in invoices
    }
    if len(places_of_supply) > 1:
        raise HTTPException(
            status_code=400,
            detail="A credit note cannot cover invoices with different places of supply",
        )

    # GSTR-1 files a note whole, under the table its invoices were filed in. A
    # company with no GSTIN files no GSTR-1, so it has no tables to keep apart.
    if direction == "outward" and any((inv.company_gst or "").strip() for inv in invoices):
        sections = {gstr1_section(inv, company_state_code(inv.company_gst)) for inv in invoices}
        if len(sections) > 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A credit note cannot cover invoices filed in different GSTR-1 tables "
                    f"({', '.join(sorted(sections))}). Raise one note for each."
                ),
            )

    # A date somebody chose has to make sense; the default needs no such check,
    # and a future-dated invoice can still take a note issued today.
    if payload.credit_note_date is not None:
        if payload.credit_note_date > india_today():
            raise HTTPException(status_code=400, detail="The credit note date cannot be in the future")
        too_late = [
            inv.invoice_number or f"#{inv.id}"
            for inv in invoices
            if inv.invoice_date and payload.credit_note_date < inv.invoice_date.date()
        ]
        if too_late:
            raise HTTPException(
                status_code=400,
                detail=f"The credit note date cannot be before the date of invoice {too_late[0]}",
            )

    invoice_map = {inv.id: inv for inv in invoices}

    # ── 3. Load invoice items and validate quantity limits ───────────────────
    item_ids = [it.invoice_item_id for it in payload.items]
    item_query = db.query(InvoiceItem).filter(InvoiceItem.id.in_(item_ids))
    if company_id is not None:
        # Another company's item is "not found", not "belongs to another invoice".
        item_query = item_query.join(Invoice, Invoice.id == InvoiceItem.invoice_id).filter(
            company_scope(Invoice.company_id, company_id)
        )
    invoice_items = item_query.all()
    invoice_item_map = {ii.id: ii for ii in invoice_items}

    missing_items = set(item_ids) - set(invoice_item_map)
    if missing_items:
        raise HTTPException(status_code=404, detail=f"Invoice items not found: {sorted(missing_items)}")

    # Verify each item belongs to the correct invoice
    for cn_item in payload.items:
        ii = invoice_item_map[cn_item.invoice_item_id]
        if ii.invoice_id != cn_item.invoice_id:
            raise HTTPException(
                status_code=400,
                detail=f"Invoice item {cn_item.invoice_item_id} does not belong to invoice {cn_item.invoice_id}",
            )
        if payload.credit_note_type != "discount" and cn_item.quantity > ii.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Credit quantity {cn_item.quantity} exceeds original quantity {ii.quantity} for item {cn_item.invoice_item_id}",
            )

    # Check cumulative credited quantities per invoice_item_id
    from src.models.credit_note import CreditNote as CN

    # Units earlier notes took back from each line. A discount note's quantity is
    # a placeholder, not units. A line can be listed twice in one request.
    returned_before: dict[int, Decimal] = {}
    if payload.credit_note_type != "discount":
        requested_qty: dict[int, int] = {}
        for cn_item in payload.items:
            item_id = cn_item.invoice_item_id
            if item_id not in returned_before:
                already_credited_query = (
                    db.query(func.sum(CreditNoteItem.quantity))
                    .join(CN, CN.id == CreditNoteItem.credit_note_id)
                    .filter(
                        CreditNoteItem.invoice_item_id == item_id,
                        CN.status == "active",
                        CN.credit_note_type != "discount",
                    )
                )
                if company_id is not None:
                    already_credited_query = already_credited_query.filter(company_scope(CN.company_id, company_id))
                returned_before[item_id] = Decimal(str(already_credited_query.scalar() or 0))

            requested_qty[item_id] = requested_qty.get(item_id, 0) + cn_item.quantity
            credited_after = returned_before[item_id] + requested_qty[item_id]
            original_qty = invoice_item_map[item_id].quantity
            if credited_after > Decimal(str(original_qty)):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Total credited quantity ({credited_after}) "
                        f"exceeds original quantity ({original_qty}) for item {item_id}"
                    ),
                )

    # Discount notes are capped by amount instead of quantity: the total
    # credited against a line -- existing active credit note items of any
    # type, plus this request -- must not exceed the line's total. Without
    # this, a discount note could credit more than the line was ever worth.
    if payload.credit_note_type == "discount":
        new_amounts: dict[int, Decimal] = {}
        for cn_item in payload.items:
            amount = Decimal(str(cn_item.discount_amount_inclusive or 0))
            new_amounts[cn_item.invoice_item_id] = (
                new_amounts.get(cn_item.invoice_item_id, Decimal("0")) + amount
            )
        for item_id, new_amount in new_amounts.items():
            ii = invoice_item_map[item_id]
            if ii.line_total is None:
                continue
            line_total = Decimal(str(ii.line_total))
            already_query = (
                db.query(func.sum(CreditNoteItem.line_total))
                .join(CN, CN.id == CreditNoteItem.credit_note_id)
                .filter(
                    CreditNoteItem.invoice_item_id == item_id,
                    CN.status == "active",
                )
            )
            if company_id is not None:
                already_query = already_query.filter(company_scope(CN.company_id, company_id))
            already = already_query.scalar()
            already_total = (
                Decimal(str(already)) if isinstance(already, (int, float, Decimal)) else Decimal("0")
            )
            if already_total + new_amount > line_total:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Credit for item {item_id} would exceed its line total "
                        f"of ₹{_money(line_total)}"
                    ),
                )

    # ── 4. Resolve financial year ────────────────────────────────────────────
    active_fy = get_active_fy(db, company_id=company_id)
    fy = active_fy
    cn_date = payload.credit_note_date or india_today()
    dated_fy = get_fy_for_date(db, cn_date, company_id=company_id)
    if dated_fy:
        fy = dated_fy
    fy_id = fy.id if fy else None

    # ── 5. Generate CN number ────────────────────────────────────────────────
    # An inward note numbers out of its own series: the outward one is declared
    # to the portal as a from/to range in GSTR-1 Table 13, and numbers spent on
    # documents we never issued would make that range wrong.
    cn_number = generate_next_number(
        db,
        "debit_note" if direction == "inward" else "credit_note",
        fy_id,
        cn_date,
        active_fy.id if active_fy else None,
        company_id=company_id,
    )

    # ── 6. Calculate totals ──────────────────────────────────────────────────
    # A note reverses the tax its invoice charged, so it follows that invoice.
    first_invoice = invoice_map[payload.invoice_ids[0]]
    interstate = invoice_is_interstate(first_invoice)

    taxable_total = Decimal("0")
    cgst_total = Decimal("0")
    sgst_total = Decimal("0")
    igst_total = Decimal("0")
    built_items = []
    new_credit: dict[int, Decimal] = {}

    for cn_item in payload.items:
        ii = invoice_item_map[cn_item.invoice_item_id]
        gst_rate = Decimal(str(ii.gst_rate or 0))
        if payload.credit_note_type == "discount":
            line_total = _money(Decimal(str(cn_item.discount_amount_inclusive or 0)))
            # Held to the amount asked for, which the even split below can pass by a paisa.
            new_credit[ii.id] = new_credit.get(ii.id, Decimal("0")) + line_total
            if gst_rate > 0:
                taxable = _money(line_total / (Decimal("1") + (gst_rate / Decimal("100"))))
                tax = _money(line_total - taxable)
            else:
                taxable = line_total
                tax = Decimal("0")
            unit_price = taxable
            quantity = 1
            half = _money(tax / Decimal("2"))
        else:
            # What the line charged, not its stored unit_price: on a tax-inclusive
            # invoice that price holds the tax, and it is always before discount.
            quantity = int(cn_item.quantity or 0)
            line_taxable = Decimal(str(ii.taxable_amount or 0))
            line_tax = Decimal(str(ii.tax_amount or 0))
            if not line_taxable and not line_tax:
                # Rows from before the tax columns carry only their total.
                line_taxable = Decimal(str(ii.line_total or 0))
            whole = Decimal(str(ii.quantity))
            before = returned_before[ii.id]
            taxable = _pro_rata(line_taxable, before, quantity, whole)
            tax = _pro_rata(line_tax, before, quantity, whole)
            half = _pro_rata(line_tax / Decimal("2"), before, quantity, whole)
            returned_before[ii.id] = before + quantity
            unit_price = _money(taxable / quantity)
            line_total = _money(taxable + tax)

        if interstate:
            igst = tax
            cgst = Decimal("0")
            sgst = Decimal("0")
        else:
            cgst = half
            sgst = half
            igst = Decimal("0")
            tax = _money(cgst + sgst)
            line_total = _money(taxable + tax)

        if payload.credit_note_type != "discount":
            new_credit[ii.id] = new_credit.get(ii.id, Decimal("0")) + line_total

        taxable_total += taxable
        cgst_total += cgst
        sgst_total += sgst
        igst_total += igst

        built_items.append({
            "invoice_id": cn_item.invoice_id,
            "invoice_item_id": cn_item.invoice_item_id,
            "product_id": ii.product_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "gst_rate": gst_rate,
            "taxable_amount": taxable,
            "tax_amount": tax,
            "line_total": line_total,
        })

    total = _money(taxable_total + cgst_total + sgst_total + igst_total)

    # A line can't be credited for more than it charged, across all its notes of
    # every type. A return can land a paisa over on an old line whose tax doesn't
    # halve evenly, which is rounding rather than an over-credit.
    tolerance = Decimal("0") if payload.credit_note_type == "discount" else Decimal("0.01")
    for item_id, credit in new_credit.items():
        credited_query = (
            db.query(func.sum(CreditNoteItem.line_total))
            .join(CN, CN.id == CreditNoteItem.credit_note_id)
            .filter(CreditNoteItem.invoice_item_id == item_id, CN.status == "active")
        )
        if company_id is not None:
            credited_query = credited_query.filter(company_scope(CN.company_id, company_id))
        credited = Decimal(str(credited_query.scalar() or 0))
        limit = _money(Decimal(str(invoice_item_map[item_id].line_total or 0)))
        if credited + credit > limit + tolerance:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Credit for item {item_id} would exceed its line total of {limit:.2f}: "
                    f"{credited:.2f} is already credited and this note adds {credit:.2f}."
                ),
            )

    # ── 7. Persist CreditNote ────────────────────────────────────────────────
    cn = CreditNote(
        credit_note_number=cn_number,
        ledger_id=payload.ledger_id,
        company_id=company_id,
        financial_year_id=fy_id,
        created_by=current_user_id,
        credit_note_type=payload.credit_note_type,
        direction=direction,
        supplier_credit_note_number=payload.supplier_credit_note_number,
        supplier_credit_note_date=payload.supplier_credit_note_date,
        credit_note_date=datetime.combine(cn_date, time.min),
        reason=payload.reason,
        status="active",
        taxable_amount=taxable_total,
        cgst_amount=cgst_total,
        sgst_amount=sgst_total,
        igst_amount=igst_total,
        total_amount=total,
    )
    db.add(cn)
    db.flush()  # get cn.id

    # ── 8. Persist invoice refs ──────────────────────────────────────────────
    for inv_id in payload.invoice_ids:
        db.add(CreditNoteInvoiceRef(credit_note_id=cn.id, invoice_id=inv_id))

    # ── 9. Persist items ─────────────────────────────────────────────────────
    for item_data in built_items:
        db.add(CreditNoteItem(credit_note_id=cn.id, company_id=company_id, **item_data))

    if payload.credit_note_type == "return":
        serials = SerialManager(db)
        # built_items is appended one-per-payload item, in order.
        for cn_item, item_data in zip(payload.items, built_items):
            product_query = db.query(Product).filter(Product.id == item_data["product_id"])
            if company_id is not None:
                product_query = product_query.filter(company_scope(Product.company_id, company_id))
            product = product_query.first()
            if not product:
                raise HTTPException(status_code=404, detail=f"Product {item_data['product_id']} not found")

            codes = SerialManager.normalize_codes(cn_item.serial_numbers)
            if getattr(product, "track_serials", False):
                if len(codes) != item_data["quantity"]:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"{product.name} is serial-tracked — provide "
                            f"{item_data['quantity']} serial "
                            f"number{'' if item_data['quantity'] == 1 else 's'} "
                            f"for this return ({len(codes)} provided)"
                        ),
                    )
                if direction == "inward":
                    serials.apply_credit_note_supplier_return(
                        codes,
                        product_id=product.id,
                        company_id=company_id,
                        invoice_id=item_data["invoice_id"],
                        note=_supplier_return_note(cn_number),
                    )
                else:
                    serials.apply_credit_note_return(
                        codes,
                        product_id=product.id,
                        company_id=company_id,
                        invoice_id=item_data["invoice_id"],
                        note=_return_note(cn_number),
                    )
            elif codes:
                raise HTTPException(
                    status_code=400,
                    detail=f"{product.name} is not serial-tracked — remove the serial numbers",
                )

            if not getattr(product, "maintain_inventory", True):
                continue

            kwargs = {"company_id": company_id} if company_id is not None else {}
            # A return undoes what its invoice did to stock: a sale took units
            # out so they come back, a purchase brought them in so they go out.
            _change_inventory_quantity(
                db,
                item_data["product_id"],
                -InventoryManager.effect_for_voucher_type(
                    item_data["quantity"], source_voucher_type
                ),
                context=(
                    f"returning stock to the supplier on credit note {cn.id}"
                    if direction == "inward"
                    else f"creating return credit note {cn.id}"
                ),
                **kwargs,
            )

    db.flush()

    # ── 10. Recompute credit_status for all referenced invoices ──────────────
    for inv_id in payload.invoice_ids:
        kwargs = {"company_id": company_id} if company_id is not None else {}
        _recompute_credit_status(inv_id, db, **kwargs)

    db.commit()
    db.refresh(cn)
    return cn


def cancel_credit_note(cn_id: int, db: Session, company_id: int | None = None) -> CreditNoteOut:
    query = db.query(CreditNote).filter(CreditNote.id == cn_id)
    if company_id is not None:
        query = query.filter(company_scope(CreditNote.company_id, company_id))
    cn = query.first()
    if not cn:
        raise HTTPException(status_code=404, detail="Credit note not found")

    was_active = cn.status == "active"

    # Collect invoice IDs before deletion so we can recompute status after
    affected_invoice_ids = list({item.invoice_id for item in cn.items if item.invoice_id})

    cn.status = "cancelled"
    cn.cancelled_at = datetime.utcnow()
    snapshot = CreditNoteOut.model_validate(cn)
    snapshot.invoice_ids = [ref.invoice_id for ref in cn.invoice_refs]

    # Rows written before the direction column existed are all outward.
    direction = cn.direction or "outward"
    source_voucher_type = "purchase" if direction == "inward" else "sales"

    if was_active and cn.credit_note_type == "return":
        serials = SerialManager(db)
        for item in cn.items:
            if item.product_id and item.quantity:
                product_query = db.query(Product).filter(Product.id == item.product_id)
                if company_id is not None:
                    product_query = product_query.filter(company_scope(Product.company_id, company_id))
                product = product_query.first()
                if not product:
                    raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

                if getattr(product, "track_serials", False):
                    if direction == "inward":
                        serials.reverse_credit_note_supplier_return(
                            product_id=product.id,
                            company_id=company_id,
                            invoice_id=item.invoice_id,
                            note=_supplier_return_note(cn.credit_note_number),
                            quantity=int(item.quantity),
                        )
                    else:
                        serials.reverse_credit_note_return(
                            product_id=product.id,
                            company_id=company_id,
                            invoice_id=item.invoice_id,
                            note=_return_note(cn.credit_note_number),
                            quantity=int(item.quantity),
                        )

                if not getattr(product, "maintain_inventory", True):
                    continue

                kwargs = {"company_id": company_id} if company_id is not None else {}
                # Creating the note negated the invoice's effect on stock, so
                # cancelling it simply applies that effect again.
                _change_inventory_quantity(
                    db,
                    item.product_id,
                    InventoryManager.effect_for_voucher_type(item.quantity, source_voucher_type),
                    context=f"cancelling return credit note {cn.id}",
                    **kwargs,
                )

    db.delete(cn)
    db.flush()

    for inv_id in affected_invoice_ids:
        kwargs = {"company_id": company_id} if company_id is not None else {}
        _recompute_credit_status(inv_id, db, **kwargs)

    db.commit()
    return snapshot
