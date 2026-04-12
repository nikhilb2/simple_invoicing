from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.models.buyer import Buyer as Ledger
from src.models.credit_note import CreditNote, CreditNoteInvoiceRef, CreditNoteItem
from src.models.invoice import Invoice, InvoiceItem
from src.schemas.credit_note import CreditNoteCreate
from src.services.financial_year import get_active_fy, get_fy_for_date
from src.services.series import generate_next_number


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_interstate(company_gst: Optional[str], ledger_gst: Optional[str]) -> bool:
    if not company_gst or not ledger_gst:
        return False
    if len(company_gst) < 2 or len(ledger_gst) < 2:
        return False
    return company_gst[:2] != ledger_gst[:2]


def _recompute_credit_status(invoice_id: int, db: Session) -> None:
    """Recalculate and persist credit_status for a single invoice."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        return

    # Sum line_total of active CN items targeting this invoice
    from sqlalchemy import func
    from src.models.credit_note import CreditNoteItem as CNItem, CreditNote as CN

    result = (
        db.query(func.sum(CNItem.line_total))
        .join(CN, CN.id == CNItem.credit_note_id)
        .filter(
            CNItem.invoice_id == invoice_id,
            CN.status == "active",
        )
        .scalar()
    )
    credited_total = Decimal(str(result or 0))
    invoice_total = Decimal(str(invoice.taxable_amount or 0))

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
) -> CreditNote:
    # ── 1. Validate ledger ───────────────────────────────────────────────────
    ledger = db.query(Ledger).filter(Ledger.id == payload.ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {payload.ledger_id} not found")

    # ── 2. Validate all invoices belong to this ledger ───────────────────────
    invoices = (
        db.query(Invoice)
        .filter(Invoice.id.in_(payload.invoice_ids))
        .all()
    )
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

    invoice_map = {inv.id: inv for inv in invoices}

    # ── 3. Load invoice items and validate quantity limits ───────────────────
    item_ids = [it.invoice_item_id for it in payload.items]
    invoice_items = (
        db.query(InvoiceItem)
        .filter(InvoiceItem.id.in_(item_ids))
        .all()
    )
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
        if cn_item.quantity > ii.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Credit quantity {cn_item.quantity} exceeds original quantity {ii.quantity} for item {cn_item.invoice_item_id}",
            )

    # Check cumulative credited quantities per invoice_item_id
    from sqlalchemy import func
    from src.models.credit_note import CreditNote as CN

    for cn_item in payload.items:
        already_credited = (
            db.query(func.sum(CreditNoteItem.quantity))
            .join(CN, CN.id == CreditNoteItem.credit_note_id)
            .filter(
                CreditNoteItem.invoice_item_id == cn_item.invoice_item_id,
                CN.status == "active",
            )
            .scalar()
        ) or 0

        original_qty = invoice_item_map[cn_item.invoice_item_id].quantity
        if already_credited + cn_item.quantity > original_qty:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Total credited quantity ({already_credited + cn_item.quantity}) "
                    f"exceeds original quantity ({original_qty}) for item {cn_item.invoice_item_id}"
                ),
            )

    # ── 4. Resolve financial year ────────────────────────────────────────────
    active_fy = get_active_fy(db)
    fy = active_fy
    cn_date = datetime.utcnow().date()
    dated_fy = get_fy_for_date(db, cn_date)
    if dated_fy:
        fy = dated_fy
    fy_id = fy.id if fy else None

    # ── 5. Generate CN number ────────────────────────────────────────────────
    cn_number = generate_next_number(
        db,
        "credit_note",
        fy_id,
        cn_date,
        active_fy.id if active_fy else None,
    )

    # ── 6. Calculate totals ──────────────────────────────────────────────────
    # Determine interstate supply from first invoice's company/ledger GST
    first_invoice = invoice_map[payload.invoice_ids[0]]
    interstate = _is_interstate(first_invoice.company_gst, ledger.gst)

    taxable_total = Decimal("0")
    cgst_total = Decimal("0")
    sgst_total = Decimal("0")
    igst_total = Decimal("0")
    built_items = []

    for cn_item in payload.items:
        ii = invoice_item_map[cn_item.invoice_item_id]
        gst_rate = Decimal(str(ii.gst_rate or 0))
        unit_price = Decimal(str(ii.unit_price))
        taxable = _money(unit_price * cn_item.quantity)
        tax = _money(taxable * gst_rate / Decimal("100"))
        line_total = _money(taxable + tax)

        if interstate:
            igst = tax
            cgst = Decimal("0")
            sgst = Decimal("0")
        else:
            half = _money(tax / Decimal("2"))
            cgst = half
            sgst = _money(tax - half)
            igst = Decimal("0")

        taxable_total += taxable
        cgst_total += cgst
        sgst_total += sgst
        igst_total += igst

        built_items.append({
            "invoice_id": cn_item.invoice_id,
            "invoice_item_id": cn_item.invoice_item_id,
            "product_id": ii.product_id,
            "quantity": cn_item.quantity,
            "unit_price": unit_price,
            "gst_rate": gst_rate,
            "taxable_amount": taxable,
            "tax_amount": tax,
            "line_total": line_total,
        })

    total = _money(taxable_total + cgst_total + sgst_total + igst_total)

    # ── 7. Persist CreditNote ────────────────────────────────────────────────
    cn = CreditNote(
        credit_note_number=cn_number,
        ledger_id=payload.ledger_id,
        financial_year_id=fy_id,
        created_by=current_user_id,
        credit_note_type=payload.credit_note_type,
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
        db.add(CreditNoteItem(credit_note_id=cn.id, **item_data))

    db.flush()

    # ── 10. Recompute credit_status for all referenced invoices ──────────────
    for inv_id in payload.invoice_ids:
        _recompute_credit_status(inv_id, db)

    db.commit()
    db.refresh(cn)
    return cn


def cancel_credit_note(cn_id: int, db: Session) -> CreditNote:
    cn = db.query(CreditNote).filter(CreditNote.id == cn_id).first()
    if not cn:
        raise HTTPException(status_code=404, detail="Credit note not found")
    if cn.status == "cancelled":
        raise HTTPException(status_code=400, detail="Credit note is already cancelled")

    # Collect invoice IDs before cancellation so we can recompute status after
    affected_invoice_ids = list({item.invoice_id for item in cn.items if item.invoice_id})

    cn.status = "cancelled"
    cn.cancelled_at = datetime.utcnow()
    db.flush()

    for inv_id in affected_invoice_ids:
        _recompute_credit_status(inv_id, db)

    db.commit()
    db.refresh(cn)
    return cn
