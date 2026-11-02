"""Reads the documents a GSTR-3B worksheet needs into plain values.

The only part of the worksheet that touches the database. Everything is scoped
to one company, including the source invoices looked up for a credit note.

The period filters repeat what the GSTR-1 routes in ``api/routes/ledgers.py`` do
(``_gstr1_invoice_query`` and the ``created_at`` filter on notes), and a route
module is not something to import from. They should become one helper when the
GSTR-1 code moves out of that file.
"""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy.orm import Session, selectinload

from src.models.credit_note import CreditNote
from src.models.invoice import Invoice, InvoiceItem
from src.services.company_access import company_scope
from src.services.gst_returns.classification import (
    InvoiceDoc,
    InvoiceLine,
    NoteDoc,
    NoteLine,
    to_decimal,
)
from src.services.gst_returns.gstr3b import ReturnPeriod
from src.services.invoice_discounts import invoice_discount_amount


def _invoice_doc(invoice: Invoice) -> InvoiceDoc:
    has_discount = bool(invoice.discount_type) and to_decimal(invoice.discount_value) > 0
    return InvoiceDoc(
        id=invoice.id,
        number=invoice.invoice_number or f"INV-{invoice.id}",
        voucher_type=invoice.voucher_type,
        status=invoice.status,
        ledger_gst=invoice.ledger_gst,
        invoice_discount=invoice_discount_amount(invoice) if has_discount else to_decimal(0),
        lines=tuple(
            InvoiceLine(
                gst_rate=to_decimal(item.gst_rate),
                taxable=to_decimal(item.taxable_amount),
                tax=to_decimal(item.tax_amount),
                cgst=to_decimal(item.cgst_amount),
                sgst=to_decimal(item.sgst_amount),
                igst=to_decimal(item.igst_amount),
            )
            for item in invoice.items
        ),
    )


def load_invoices(db: Session, period: ReturnPeriod, company_id: int | None) -> list[InvoiceDoc]:
    invoices = (
        db.query(Invoice)
        .options(selectinload(Invoice.items))
        .filter(
            Invoice.status == "active",
            Invoice.invoice_date >= datetime.combine(period.from_date, time.min),
            Invoice.invoice_date <= datetime.combine(period.to_date, time.max),
            company_scope(Invoice.company_id, company_id),
        )
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        .all()
    )
    return [_invoice_doc(invoice) for invoice in invoices]


def load_notes(db: Session, period: ReturnPeriod, company_id: int | None) -> list[NoteDoc]:
    notes = (
        db.query(CreditNote)
        .options(selectinload(CreditNote.items))
        .filter(
            CreditNote.status == "active",
            CreditNote.created_at >= datetime.combine(period.from_date, time.min),
            CreditNote.created_at <= datetime.combine(period.to_date, time.max),
            company_scope(CreditNote.company_id, company_id),
        )
        .order_by(CreditNote.created_at.asc(), CreditNote.id.asc())
        .all()
    )

    invoice_ids = {item.invoice_id for note in notes for item in note.items if item.invoice_id}
    item_ids = {item.invoice_item_id for note in notes for item in note.items if item.invoice_item_id}

    # A note's own company_id says nothing about what its item ids point at, so
    # the lookups are scoped as well: another company's invoice reads as unknown.
    sources = {}
    source_lines = {}
    if invoice_ids:
        scope = company_scope(Invoice.company_id, company_id)
        sources = {
            row.id: row
            for row in db.query(Invoice.id, Invoice.invoice_number, Invoice.voucher_type, Invoice.status)
            .filter(Invoice.id.in_(invoice_ids), scope)
            .all()
        }
    if item_ids:
        source_lines = {
            row.id: row
            for row in db.query(InvoiceItem.id, InvoiceItem.taxable_amount, InvoiceItem.quantity)
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .filter(InvoiceItem.id.in_(item_ids), company_scope(Invoice.company_id, company_id))
            .all()
        }

    docs = []
    for note in notes:
        lines = []
        for item in note.items:
            source = sources.get(item.invoice_id)
            source_line = source_lines.get(item.invoice_item_id)
            lines.append(
                NoteLine(
                    gst_rate=to_decimal(item.gst_rate),
                    taxable=to_decimal(item.taxable_amount),
                    tax=to_decimal(item.tax_amount),
                    quantity=to_decimal(item.quantity),
                    source_invoice_number=(
                        (source.invoice_number or f"INV-{source.id}") if source is not None else None
                    ),
                    source_voucher_type=source.voucher_type if source is not None else None,
                    source_status=source.status if source is not None else None,
                    source_line_taxable=(
                        to_decimal(source_line.taxable_amount) if source_line is not None else None
                    ),
                    source_line_quantity=(
                        to_decimal(source_line.quantity) if source_line is not None else None
                    ),
                )
            )
        docs.append(
            NoteDoc(
                id=note.id,
                number=note.credit_note_number or f"CN-{note.id}",
                direction=note.direction,
                status=note.status,
                note_type=note.credit_note_type,
                igst_total=to_decimal(note.igst_amount),
                supplier_note_date=note.supplier_credit_note_date,
                lines=tuple(lines),
            )
        )
    return docs
