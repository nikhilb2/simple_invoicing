"""Discount amount derivation for reporting.

Invoices do not store discount *amounts* — :mod:`src.services.invoice_processor`
computes them at write time and persists only ``discount_type`` and
``discount_value``, with ``taxable_amount`` already net of any line discount.
Reports that need a "Discount Given" figure therefore have to recover it.

This module recovers it by *inverting* the write path's algebra rather than
re-running its arithmetic.  That matters: re-running would have to reproduce
both of the processor's clamps (``min(discount, taxable)`` on net line
discounts, ``min(discount, raw_total)`` on invoice discounts) and would
accumulate its own rounding.  Subtracting stored values gets both for free and
is exact.

The derivation is coupled to ``InvoiceProcessor.calculate_totals`` and
``InvoiceProcessor._apply_totals``.  If the discount write path changes, the
figures here go silently wrong — see ``tests/services/test_invoice_discounts.py``,
which round-trips against the processor to catch exactly that.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from src.models.invoice import Invoice, InvoiceItem
from src.services.gst_tax_service import money as _money


@dataclass
class InvoiceDiscountSummary:
    """Discount amounts for one invoice, all positive Decimals.

    Amounts stay ``Decimal`` rather than ``float`` (unlike
    :class:`~src.services.invoice_payments.InvoicePaymentSummary`) because
    reports sum these across every invoice in a period; float accumulation
    drifts. Convert at the schema boundary.
    """

    invoice_id: int
    item_discount_total: Decimal
    invoice_discount_amount: Decimal
    total_discount: Decimal


def _dec(value) -> Decimal:
    """Coerce a DB value to Decimal.

    Numeric columns come back as Decimal on Postgres but float on SQLite (the
    test engine), so route through ``str`` to avoid binary float artefacts.
    """
    return Decimal(str(value or 0))


def _pre_discount_taxable(item: InvoiceItem, *, tax_inclusive: bool) -> Decimal:
    """Reconstruct a line's taxable amount *before* its discount was applied.

    Mirrors ``InvoiceProcessor.calculate_totals`` exactly, including its
    intermediate rounding — the tax-inclusive branch rounds ``line_total``
    first and *then* divides, so collapsing the two steps would drift a paisa.
    """
    quantity = _dec(item.quantity)
    unit_price = _dec(item.unit_price)
    gst_rate = _dec(item.gst_rate)

    if tax_inclusive:
        line_total = _money(unit_price * quantity)
        return _money(line_total / (1 + gst_rate / Decimal("100")))
    return _money(unit_price * quantity)


def _item_discount_totals(db: Session, invoice_ids: list[int], tax_inclusive_by_invoice: dict[int, bool]) -> dict[int, Decimal]:
    """Sum per-line discounts for each invoice.

    Only lines carrying a ``discount_type`` are fetched: an undiscounted line
    stores its pre-discount taxable unchanged, so it contributes exactly zero
    and reconstructing it would be pure rounding risk for no gain.
    """
    if not invoice_ids:
        return {}

    items = (
        db.query(InvoiceItem)
        .filter(
            InvoiceItem.invoice_id.in_(invoice_ids),
            InvoiceItem.discount_type.isnot(None),
        )
        .all()
    )

    totals: dict[int, Decimal] = {}
    for item in items:
        tax_inclusive = tax_inclusive_by_invoice.get(item.invoice_id, False)
        discount = _pre_discount_taxable(item, tax_inclusive=tax_inclusive) - _dec(item.taxable_amount)
        # A stored taxable above the reconstruction would mean the write path
        # changed shape; clamp rather than report a negative discount.
        if discount <= 0:
            continue
        totals[item.invoice_id] = totals.get(item.invoice_id, Decimal("0")) + discount

    return {invoice_id: _money(total) for invoice_id, total in totals.items()}


def _invoice_discount_amount(invoice: Invoice) -> Decimal:
    """Recover the invoice-level discount by inverting the processor's totals.

    ``_apply_totals`` ends with ``total_amount = raw_total + round_off`` in both
    the round-off and non-round-off branches (``round_off`` being 0 in the
    latter), where ``raw_total`` is already net of the invoice discount and
    ``raw_total`` before the discount is ``taxable_amount + total_tax_amount``.
    Rearranged, the discount falls straight out.
    """
    discount = (
        _dec(invoice.taxable_amount)
        + _dec(invoice.total_tax_amount)
        + _dec(invoice.round_off_amount)
        - _dec(invoice.total_amount)
    )
    if discount <= 0:
        return Decimal("0.00")
    return _money(discount)


def build_invoice_discount_totals(
    db: Session,
    invoices: list[Invoice],
) -> dict[int, InvoiceDiscountSummary]:
    """Derive discount amounts for a batch of invoices, keyed by invoice id.

    Batch-shaped like
    :func:`~src.services.invoice_payments.build_invoice_payment_summaries`: one
    grouped query for the whole set rather than per-invoice lookups.
    """
    if not invoices:
        return {}

    invoice_ids = [invoice.id for invoice in invoices]
    tax_inclusive_by_invoice = {invoice.id: bool(invoice.tax_inclusive) for invoice in invoices}
    item_totals = _item_discount_totals(db, invoice_ids, tax_inclusive_by_invoice)

    summaries: dict[int, InvoiceDiscountSummary] = {}
    for invoice in invoices:
        item_total = item_totals.get(invoice.id, Decimal("0.00"))
        invoice_discount = _invoice_discount_amount(invoice)
        summaries[invoice.id] = InvoiceDiscountSummary(
            invoice_id=invoice.id,
            item_discount_total=item_total,
            invoice_discount_amount=invoice_discount,
            total_discount=_money(item_total + invoice_discount),
        )

    return summaries
