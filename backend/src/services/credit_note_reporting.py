from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice


@dataclass
class CreditNoteLedgerEntry:
    entry_id: int
    date: datetime
    voucher_type: str
    credit_note_number: str | None  # The credit note number
    ledger_name: str
    particulars: str
    debit: float
    credit: float


@dataclass
class CreditNoteLedgerSummary:
    entries: list[CreditNoteLedgerEntry]
    sales_credit_total: float
    purchase_credit_total: float
    sales_credit_by_invoice: dict[int, float]


def get_credit_note_ledger_summary(
    db: Session,
    ledger_id: int | None = None,
    company_id: int | None = None,
    created_before: datetime | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> CreditNoteLedgerSummary:
    query = (
        db.query(CreditNote, CreditNoteItem, Invoice)
        .join(CreditNoteItem, CreditNoteItem.credit_note_id == CreditNote.id)
        .join(Invoice, Invoice.id == CreditNoteItem.invoice_id)
        .filter(CreditNote.status == "active")
    )

    if ledger_id is not None:
        query = query.filter(CreditNote.ledger_id == ledger_id)
    if company_id is not None:
        query = query.filter(or_(CreditNote.company_id == company_id, CreditNote.company_id.is_(None)))
    if created_before is not None:
        query = query.filter(CreditNote.created_at < created_before)
    if created_from is not None:
        query = query.filter(CreditNote.created_at >= created_from)
    if created_to is not None:
        query = query.filter(CreditNote.created_at <= created_to)

    rows = query.order_by(CreditNote.created_at.asc(), CreditNote.id.asc(), CreditNoteItem.id.asc()).all()

    entry_buckets: dict[int, dict] = {}
    entry_order: list[int] = []
    sales_credit_total = 0.0
    purchase_credit_total = 0.0
    sales_credit_by_invoice: defaultdict[int, float] = defaultdict(float)

    for credit_note, item, invoice in rows:
        if credit_note.id not in entry_buckets:
            entry_buckets[credit_note.id] = {
                "credit_note_number": credit_note.credit_note_number,
                "credit_note_type": credit_note.credit_note_type,
                "date": credit_note.created_at,
                "ledger_name": invoice.ledger_name or "Unknown ledger",
                "invoice_numbers": [],
                "seen_invoice_numbers": set(),
                "debit": 0.0,
                "credit": 0.0,
            }
            entry_order.append(credit_note.id)

        bucket = entry_buckets[credit_note.id]
        amount = float(item.line_total or 0)
        invoice_label = invoice.invoice_number or f"#{invoice.id}"

        if invoice_label not in bucket["seen_invoice_numbers"]:
            bucket["invoice_numbers"].append(invoice_label)
            bucket["seen_invoice_numbers"].add(invoice_label)

        if invoice.voucher_type == "purchase":
            bucket["debit"] += amount
            purchase_credit_total += amount
        else:
            bucket["credit"] += amount
            sales_credit_total += amount
            sales_credit_by_invoice[invoice.id] += amount

    entries: list[CreditNoteLedgerEntry] = []
    for credit_note_id in entry_order:
        bucket = entry_buckets[credit_note_id]
        invoice_numbers = bucket["invoice_numbers"]
        preview_numbers = ", ".join(invoice_numbers[:3])
        suffix = "" if len(invoice_numbers) <= 3 else " +"
        particulars = (
            f"{bucket['credit_note_number']} ({bucket['credit_note_type'].title()})"
            + (f" against {preview_numbers}{suffix}" if preview_numbers else "")
        )
        entries.append(
            CreditNoteLedgerEntry(
                entry_id=credit_note_id,
                date=bucket["date"],
                voucher_type="Credit Note",
                credit_note_number=bucket["credit_note_number"],
                ledger_name=bucket["ledger_name"],
                particulars=particulars,
                debit=bucket["debit"],
                credit=bucket["credit"],
            )
        )

    return CreditNoteLedgerSummary(
        entries=entries,
        sales_credit_total=sales_credit_total,
        purchase_credit_total=purchase_credit_total,
        sales_credit_by_invoice=dict(sales_credit_by_invoice),
    )