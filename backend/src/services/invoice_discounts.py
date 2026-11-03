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


def item_discount_amount(item: InvoiceItem, *, tax_inclusive: bool) -> Decimal:
    """Recover one line's discount amount from its stored taxable amount."""
    discount = _pre_discount_taxable(item, tax_inclusive=tax_inclusive) - _dec(item.taxable_amount)
    # A stored taxable above the reconstruction would mean the write path
    # changed shape; clamp rather than report a negative discount.
    if discount <= 0:
        return Decimal("0.00")
    return _money(discount)


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
        discount = item_discount_amount(item, tax_inclusive=tax_inclusive)
        if discount <= 0:
            continue
        totals[item.invoice_id] = totals.get(item.invoice_id, Decimal("0")) + discount

    return {invoice_id: _money(total) for invoice_id, total in totals.items()}


def invoice_discount_amount(invoice: Invoice) -> Decimal:
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


def apportion_invoice_discount(
    line_taxables: list[Decimal],
    *,
    invoice_discount: Decimal,
    invoice_tax: Decimal,
) -> list[Decimal]:
    """Split an invoice-level discount into each line's ex-GST share.

    Item ``taxable_amount`` already nets off *line* discounts but never the
    invoice-level one: ``InvoiceProcessor._apply_totals`` subtracts that from
    ``raw_total`` (taxable + GST) after line and tax totals are fixed, so no
    stored line or tax figure ever reflects it. A per-product revenue or spend
    figure built from line ``taxable_amount`` therefore overstates by the
    invoice discount unless it is apportioned back onto the lines.

    GST treatment: the discount is taken off the GST-*inclusive* raw total, so
    only part of it is a reduction in the ex-GST value of the goods. That part
    is ``invoice_discount * taxable / (taxable + tax)``, where ``taxable`` is
    the sum of ``line_taxables`` and ``tax`` is the invoice's stored total GST.
    The remainder corresponds to GST that was nominally charged but not
    collected; it is not revenue, so it is dropped here (the stored GST figures
    are left as the processor wrote them). This holds for tax-inclusive
    invoices too, since their line ``taxable_amount`` is already ex-GST.

    The ex-GST share is then split across lines pro-rata by line
    ``taxable_amount``. Each share is rounded to paise and the rounding residue
    lands on the largest line, so the shares always sum exactly to the ex-GST
    share and a report's total never drifts from the invoice by a paisa.

    Returns one non-negative Decimal per input line, in the same order.
    """
    taxables = [_dec(value) for value in line_taxables]
    taxable_total = sum(taxables, Decimal("0"))
    discount = _dec(invoice_discount)
    gross = taxable_total + _dec(invoice_tax)

    if discount <= 0 or taxable_total <= 0 or gross <= 0:
        return [Decimal("0.00") for _ in taxables]

    ex_gst_share = _money(min(discount, gross) * taxable_total / gross)
    shares = [_money(ex_gst_share * taxable / taxable_total) for taxable in taxables]

    residue = ex_gst_share - sum(shares, Decimal("0"))
    if residue:
        largest = max(range(len(taxables)), key=lambda index: taxables[index])
        shares[largest] = _money(shares[largest] + residue)

    return shares


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
        invoice_discount = invoice_discount_amount(invoice)
        summaries[invoice.id] = InvoiceDiscountSummary(
            invoice_id=invoice.id,
            item_discount_total=item_total,
            invoice_discount_amount=invoice_discount,
            total_discount=_money(item_total + invoice_discount),
        )

    return summaries
