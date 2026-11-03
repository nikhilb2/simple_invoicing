"""A GSTR-3B worksheet: an estimate from the user's own books, for cross-checking.

Pure calculation: documents in, worksheet out, no database and no FastAPI. It is
not a return and nothing here is uploadable. The portal fills 3.1 and 3.2 from
GSTR-1 and Table 4 from GSTR-2B, and those values take precedence over anything
computed here.

Where the mapping comes from, checked 2 Nov 2026:

* 3.1(a) from GSTR-1 Tables 4, 5, 6C, 7, 9, 10 and 11: GSTN advisory on
  auto-population, December 2020, para 7.
* Table 4 structure and 4(C) = 4(A) - 4(B): Circular 170/02/2022-GST, para 4.3.
* Supplier credit notes reduce 4(A), not 4(B)(2). The 2020 advisory put them in
  4(B)(2), but Notification 14/2022-CT moved them from the January 2023 period
  (GSTN advisory, February 2023), and the portal's current GSTR-3B guide says
  4(A) is "Net credit including impact of credit notes and their amendments".
* 4(C) below zero is a liability: 2020 advisory, para 9.
* 5.1 interest and late fee are computed by the portal: GSTR-3B user guide.

Rows that the books cannot support are present and marked ``not_tracked`` with
no figures, because a blank is honest and a zero would read as "you have none".
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from src.services.gst_returns.classification import (
    InvoiceDoc,
    NoteDoc,
    RateClass,
    Side,
    classify_invoice,
    classify_note,
    classify_note_line,
    classify_rate,
    gstin_problem,
    is_unregistered,
    note_line_exceeds_source,
    note_line_head_differs,
    note_line_overrides_direction,
    split_note_tax,
)
from src.services.gst_returns.setoff import HEADS, compute_setoff

FROM_BOOKS = "from_books"
NOT_TRACKED = "not_tracked"

TITLE = "GSTR-3B worksheet"
HEADLINE = "Worksheet, not a return"
DISCLAIMER = (
    "This is an estimate from your own books, for cross-checking only. It is not a filing "
    "and cannot be uploaded. Values auto-populated on the GST portal take precedence over "
    "anything shown here."
)
TABLE_5_1_NOTE = (
    "Table 5.1 (interest and late fee) comes from the GST portal, which computes it from "
    "your filing date and the due date. It is not estimated here."
)
TABLE_3_2_NOTE = (
    "Stays empty until place of supply is recorded on invoices. Inter-state supplies to "
    "unregistered persons, composition dealers and UIN holders cannot be identified today."
)

KNOWN_LIMITS: tuple[str, ...] = (
    "Every purchase counts as eligible input credit. Blocked credit under section 17(5) and "
    "reversals under rules 37, 38, 42 and 43 are not recorded, so the credit shown can be too high.",
    "Table 4 on the portal follows GSTR-2B: what your suppliers filed, in the period they filed it. "
    "These figures follow your purchase entries, by the date you booked them.",
    "Reverse charge, imports, ISD credit, exports, SEZ supplies and cess are not recorded.",
    "Place of supply is not recorded, so a sale to an unregistered buyer is always taxed as "
    "intra-state. If the buyer was in another state, the invoice itself has the wrong tax heads.",
    "Credit notes are placed in a period by when they were created in the app, in UTC, not by a "
    "date you chose. A note created between 00:00 and 05:30 IST can land on the previous day (#607). "
    "Invoices saved without a date, and duplicated invoices, are also stored in UTC and can land "
    "the same way. Documents in that window on the last day of the period are named in a warning.",
    "Table 6.1 uses only this period's figures. It leaves out credit already in your electronic "
    "credit ledger, negative liability carried in from earlier periods, interest and late fee.",
)

_TWO_PLACES = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


# --- period -----------------------------------------------------------------

class InvalidReturnPeriod(ValueError):
    """The dates are not exactly one calendar month or one GST quarter."""


@dataclass(frozen=True)
class ReturnPeriod:
    from_date: date
    to_date: date
    kind: str  # "month" or "quarter"
    label: str


_QUARTER_START_MONTHS = (1, 4, 7, 10)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def resolve_return_period(from_date: date, to_date: date) -> ReturnPeriod:
    """Accept exactly one month (monthly filers) or one quarter (QRMP filers).

    Quarters are the GST ones, Apr-Jun, Jul-Sep, Oct-Dec and Jan-Mar. A partial
    month is refused rather than computed: a worksheet for the 1st to the 20th
    would look like a return figure and be nothing of the kind.
    """
    message = (
        "GSTR-3B covers one calendar month or one quarter (Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar). "
        "Choose from_date as the first day and to_date as the last day of that period."
    )
    if from_date.day != 1 or from_date.year != to_date.year:
        raise InvalidReturnPeriod(message)
    if to_date == _month_end(from_date.year, from_date.month):
        return ReturnPeriod(from_date, to_date, "month", from_date.strftime("%B %Y"))
    if (
        from_date.month in _QUARTER_START_MONTHS
        and to_date == _month_end(from_date.year, from_date.month + 2)
    ):
        label = f"{from_date.strftime('%b')}-{to_date.strftime('%b')} {from_date.year}"
        return ReturnPeriod(from_date, to_date, "quarter", label)
    raise InvalidReturnPeriod(message)


# --- output shape -----------------------------------------------------------

@dataclass
class _Amounts:
    taxable_value: Decimal = Decimal("0")
    igst: Decimal = Decimal("0")
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")

    def add(self, *, taxable: Decimal, cgst: Decimal, sgst: Decimal, igst: Decimal) -> None:
        self.taxable_value += taxable
        self.cgst += cgst
        self.sgst += sgst
        self.igst += igst

    def minus(self, other: "_Amounts") -> "_Amounts":
        return _Amounts(
            taxable_value=self.taxable_value - other.taxable_value,
            igst=self.igst - other.igst,
            cgst=self.cgst - other.cgst,
            sgst=self.sgst - other.sgst,
        )


@dataclass(frozen=True)
class RowComponent:
    """One of the figures a row is the net of, shown so it can be checked by hand."""

    label: str
    taxable_value: Decimal | None
    igst: Decimal
    cgst: Decimal
    sgst: Decimal


@dataclass(frozen=True)
class WorksheetRow:
    key: str
    table: str
    label: str
    source: str
    note: str | None = None
    taxable_value: Decimal | None = None
    igst: Decimal | None = None
    cgst: Decimal | None = None
    sgst: Decimal | None = None
    components: tuple[RowComponent, ...] = ()


@dataclass(frozen=True)
class WorksheetSection:
    key: str
    title: str
    rows: tuple[WorksheetRow, ...]
    note: str | None = None


@dataclass(frozen=True)
class SetOffLine:
    head: str
    output_tax: Decimal
    input_credit: Decimal
    credit_used: Decimal
    payable: Decimal
    credit_carried_forward: Decimal


@dataclass(frozen=True)
class SetOffTable:
    source: str
    note: str
    lines: tuple[SetOffLine, ...]
    total_payable: Decimal
    total_credit_carried_forward: Decimal
    rows: tuple[WorksheetRow, ...]


@dataclass(frozen=True)
class WarningDocument:
    kind: str  # "invoice" or "credit_note"
    id: int
    number: str
    detail: str | None = None


@dataclass(frozen=True)
class WorksheetWarning:
    code: str
    severity: str  # "warning" or "info"
    title: str
    message: str
    documents: tuple[WarningDocument, ...] = ()


@dataclass(frozen=True)
class Gstr3bWorksheet:
    title: str
    headline: str
    disclaimer: str
    period: ReturnPeriod
    warnings: tuple[WorksheetWarning, ...]
    known_limits: tuple[str, ...]
    sections: tuple[WorksheetSection, ...]
    setoff: SetOffTable
    table_5_1_note: str

    @property
    def from_date(self) -> date:
        return self.period.from_date

    @property
    def to_date(self) -> date:
        return self.period.to_date

    @property
    def period_type(self) -> str:
        return self.period.kind

    @property
    def period_label(self) -> str:
        return self.period.label


# --- warnings ---------------------------------------------------------------

@dataclass(frozen=True)
class _WarningSpec:
    severity: str
    title: str
    message: str


# Ordered: the ones most likely to move the figure come first.
_WARNINGS: dict[str, _WarningSpec] = {
    "company_gstin": _WarningSpec(
        "warning",
        "Your company GSTIN needs attention",
        "Tax heads are decided by comparing state codes in GSTINs, so without a valid company "
        "GSTIN the split between IGST and CGST/SGST cannot be relied on. Fix it in company settings.",
    ),
    "note_on_cancelled_invoice": _WarningSpec(
        "warning",
        "Active credit notes against cancelled invoices",
        "The invoice was cancelled but the note was not (#602). These note lines are left out of "
        "this worksheet because the sale is already gone. The GSTR-1 export still includes "
        "outward ones, so 3.1(a) here is higher than the export by these amounts.",
    ),
    "note_direction_conflict": _WarningSpec(
        "warning",
        "Credit notes this worksheet cannot place",
        "The note has a direction or an invoice type this worksheet does not recognise. These "
        "lines are left out here. The GSTR-1 export goes by direction alone and may still "
        "include them.",
    ),
    "note_direction_overridden": _WarningSpec(
        "warning",
        "Credit notes whose direction disagrees with their invoice",
        "The note says one direction but the invoice it reverses is on the other side, for "
        "example an outward note against a purchase (older notes were all marked outward). This "
        "worksheet and the Tax Ledger follow the invoice, so these lines reduce input credit or "
        "output tax according to the invoice. The GSTR-1 export goes by the note's direction and "
        "subtracts an outward note from output tax even when its invoice is a purchase, and "
        "leaves an inward note out even when its invoice is a sale, so 3.1(a) there differs "
        "from here.",
    ),
    "note_head_mismatch": _WarningSpec(
        "warning",
        "Credit notes whose tax heads differ from their invoice line",
        "The note's tax heads (IGST or CGST/SGST) differ from the invoice line it reverses, "
        "usually because a party's GSTIN changed after the invoice. This worksheet follows the "
        "note's own heads, as the GSTR-1 export does. The Tax Ledger follows the invoice line, "
        "so its figures will differ from these.",
    ),
    "note_exceeds_source": _WarningSpec(
        "warning",
        "Credit notes larger than the invoice line they reverse",
        "The stored value is more than the share of the invoice line being reversed. Known causes: "
        "a return on a tax-inclusive invoice or a discounted line (#572), and a discount note "
        "bigger than its line (#603). The worksheet uses the stored value, as the GSTR-1 export "
        "does, so the reduction may be overstated. Check these notes.",
    ),
    "unregistered_supplier_gst": _WarningSpec(
        "warning",
        "GST on purchases from suppliers with no GSTIN",
        "An unregistered supplier cannot charge GST or pass on credit, and these would not appear "
        "in GSTR-2B, yet the tax is counted in 4(A)(5) here. Check the supplier's GSTIN, or whether "
        "this credit should be claimed at all.",
    ),
    "invalid_gstin": _WarningSpec(
        "warning",
        "Invalid GSTINs",
        "The portal would reject these. A wrong supplier GSTIN also means the credit will not "
        "match GSTR-2B, and a wrong buyer GSTIN can change which tax heads the invoice should use.",
    ),
    "invoice_level_discount": _WarningSpec(
        "warning",
        "Invoice-level discounts are not in the taxable value",
        "An invoice-level discount comes off the total after tax, so the stored taxable value and "
        "GST stay at their pre-discount amounts. This worksheet and the GSTR-1 export both report "
        "them that way, which can overstate both. Ask your accountant how these should be treated.",
    ),
    "unregistered_buyer": _WarningSpec(
        "warning",
        "Sales to unregistered buyers who may be inter-state",
        "Place of supply is not recorded, so these were taxed as intra-state (CGST and SGST). A "
        "buyer in another state should have been charged IGST and belongs in Table 3.2.",
    ),
    "zero_rate_sales": _WarningSpec(
        "warning",
        "Sales lines at 0%",
        "Nothing says whether these are nil rated, exempt, zero rated or non-GST, so they sit in "
        "the unclassified row and not in 3.1(a), (b), (c) or (e). Decide where each belongs.",
    ),
    "zero_rate_purchases": _WarningSpec(
        "info",
        "Purchase lines at 0%",
        "These add no input credit. If they are exempt, nil rated or non-GST inward supplies they "
        "belong in Table 5, which is not tracked here.",
    ),
    "utc_period_edge": _WarningSpec(
        "warning",
        "Documents near the end of the period, in UTC",
        "These were stored in the last 5.5 hours of the last day of the period, in UTC. If they "
        "were entered between 00:00 and 05:30 IST on the next day, they belong to the next period "
        "on the portal (#607). They are counted here to agree with the GSTR-1 export.",
    ),
    "tax_head_mismatch": _WarningSpec(
        "warning",
        "Line tax does not match its tax heads",
        "On these invoices a line's tax amount differs from its CGST, SGST and IGST added up. The "
        "tables use the heads. Check the invoice.",
    ),
    "inward_note_date_outside_period": _WarningSpec(
        "info",
        "Supplier credit notes dated outside this period",
        "Each is counted here because of when it was recorded, but the supplier's own date is in "
        "another period. GSTR-2B will follow when the supplier filed it.",
    ),
    "unknown_voucher_type": _WarningSpec(
        "warning",
        "Documents that are neither sales nor purchases",
        "These have a voucher type this worksheet does not recognise and are left out of every table.",
    ),
    "negative_output": _WarningSpec(
        "warning",
        "Credit notes exceed sales for a tax head",
        "Net output tax is below zero for at least one head. Table 6.1 treats the excess as credit "
        "this period, but the portal carries negative liability forward in its own statement "
        "instead, so the cash payable there can be higher.",
    ),
    "negative_itc": _WarningSpec(
        "info",
        "Supplier credit notes exceed purchases for a tax head",
        "Net input credit is below zero for at least one head. Table 6.1 adds that to what is "
        "payable, as the portal does with a negative 4(C).",
    ),
}


class _Warnings:
    def __init__(self) -> None:
        self._documents: dict[str, list[WarningDocument]] = {}
        self._raised: set[str] = set()

    def raise_(self, code: str) -> None:
        self._raised.add(code)

    def add(self, code: str, *, kind: str, doc_id: int, number: str, detail: str | None = None) -> None:
        self._raised.add(code)
        self._documents.setdefault(code, []).append(WarningDocument(kind, doc_id, number, detail))

    def build(self) -> tuple[WorksheetWarning, ...]:
        return tuple(
            WorksheetWarning(
                code=code,
                severity=spec.severity,
                title=spec.title,
                message=spec.message,
                documents=tuple(self._documents.get(code, ())),
            )
            for code, spec in _WARNINGS.items()
            if code in self._raised
        )


def _rupees(value: Decimal) -> str:
    return f"₹{_money(value):,.2f}"


# --- calculation ------------------------------------------------------------

@dataclass
class _Tally:
    sales: _Amounts = field(default_factory=_Amounts)
    sales_zero: _Amounts = field(default_factory=_Amounts)
    outward_notes: _Amounts = field(default_factory=_Amounts)
    outward_notes_zero: _Amounts = field(default_factory=_Amounts)
    purchases: _Amounts = field(default_factory=_Amounts)
    inward_notes: _Amounts = field(default_factory=_Amounts)


# 05:30 ahead of UTC: a stamp at or after 18:30 UTC is already the next day in IST.
_IST_NEXT_DAY_FROM = time(18, 30)


def _utc_edge_detail(stamp: datetime | None, period: ReturnPeriod) -> str | None:
    """Why a document stored late on the period's last day may belong to the next one."""
    if stamp is None or stamp.date() != period.to_date or stamp.time() < _IST_NEXT_DAY_FROM:
        return None
    return f"Stored {stamp:%d %b %Y %H:%M} UTC, which is the next day in IST"


def _read_invoices(
    invoices: list[InvoiceDoc], period: ReturnPeriod, tally: _Tally, warnings: _Warnings
) -> None:
    for invoice in invoices:
        side = classify_invoice(invoice.voucher_type, invoice.status)
        if side is Side.EXCLUDED:
            if invoice.status == "active":
                warnings.add(
                    "unknown_voucher_type",
                    kind="invoice",
                    doc_id=invoice.id,
                    number=invoice.number,
                    detail=f"Voucher type: {invoice.voucher_type}",
                )
            continue

        invoice_tax = Decimal("0")
        has_zero_line = False
        heads_mismatch = False
        for line in invoice.lines:
            invoice_tax += line.tax
            if abs(line.tax - (line.cgst + line.sgst + line.igst)) > Decimal("0.01"):
                heads_mismatch = True

            is_zero = classify_rate(line.gst_rate) is RateClass.UNCLASSIFIED_ZERO
            has_zero_line = has_zero_line or is_zero
            if side is Side.OUTWARD:
                bucket = tally.sales_zero if is_zero else tally.sales
            else:
                bucket = tally.purchases
            bucket.add(taxable=line.taxable, cgst=line.cgst, sgst=line.sgst, igst=line.igst)

        doc = {"kind": "invoice", "doc_id": invoice.id, "number": invoice.number}
        edge = _utc_edge_detail(invoice.invoice_date, period)
        if edge:
            warnings.add("utc_period_edge", **doc, detail=edge)
        problem = gstin_problem(invoice.ledger_gst)
        if problem:
            warnings.add(
                "invalid_gstin",
                **doc,
                detail=f"{(invoice.ledger_gst or '').strip()}: {problem}",
            )
        if has_zero_line:
            warnings.add("zero_rate_sales" if side is Side.OUTWARD else "zero_rate_purchases", **doc)
        if heads_mismatch:
            warnings.add("tax_head_mismatch", **doc)
        if invoice.invoice_discount > 0:
            warnings.add(
                "invoice_level_discount",
                **doc,
                detail=f"Discount {_rupees(invoice.invoice_discount)}",
            )
        if is_unregistered(invoice.ledger_gst):
            if side is Side.OUTWARD:
                warnings.add("unregistered_buyer", **doc)
            elif invoice_tax > 0:
                warnings.add(
                    "unregistered_supplier_gst",
                    **doc,
                    detail=f"GST {_rupees(invoice_tax)}",
                )


def _read_notes(notes: list[NoteDoc], period: ReturnPeriod, tally: _Tally, warnings: _Warnings) -> None:
    for note in notes:
        note_side = classify_note(note.direction, note.status)
        if note_side is Side.EXCLUDED:
            if note.status == "active":
                warnings.add(
                    "note_direction_conflict",
                    kind="credit_note",
                    doc_id=note.id,
                    number=note.number,
                    detail=f"Direction: {note.direction}",
                )
            continue

        doc = {"kind": "credit_note", "doc_id": note.id, "number": note.number}
        exceeds_source = False
        for line in note.lines:
            line_side = classify_note_line(note_side, line)
            if line_side is Side.EXCLUDED:
                source = line.source_invoice_number or "its invoice"
                detail = f"{_rupees(line.taxable)} taxable, {_rupees(line.tax)} GST against {source}"
                if line.source_status is not None and line.source_status != "active":
                    warnings.add("note_on_cancelled_invoice", **doc, detail=detail)
                else:
                    warnings.add("note_direction_conflict", **doc, detail=detail)
                continue

            if note_line_overrides_direction(note_side, line):
                source = line.source_invoice_number or "its invoice"
                warnings.add(
                    "note_direction_overridden",
                    **doc,
                    detail=(
                        f"{_rupees(line.taxable)} taxable, {_rupees(line.tax)} GST against "
                        f"{source}, counted as {line_side.value} (note says {note_side.value})"
                    ),
                )

            if note_line_head_differs(note.igst_total, line):
                source = line.source_invoice_number or "its invoice"
                warnings.add(
                    "note_head_mismatch",
                    **doc,
                    detail=(
                        f"{_rupees(line.tax)} GST on "
                        f"{'IGST' if note.igst_total > 0 else 'CGST/SGST'}, "
                        f"{source} has {'CGST/SGST' if note.igst_total > 0 else 'IGST'}"
                    ),
                )
            exceeds_source = exceeds_source or note_line_exceeds_source(note.note_type, line)
            cgst, sgst, igst = split_note_tax(line.tax, note.igst_total)
            if line_side is Side.OUTWARD:
                is_zero = classify_rate(line.gst_rate) is RateClass.UNCLASSIFIED_ZERO
                bucket = tally.outward_notes_zero if is_zero else tally.outward_notes
            else:
                bucket = tally.inward_notes
            bucket.add(taxable=line.taxable, cgst=cgst, sgst=sgst, igst=igst)

        if exceeds_source:
            warnings.add("note_exceeds_source", **doc)
        edge = _utc_edge_detail(note.created_at, period)
        if edge:
            warnings.add("utc_period_edge", **doc, detail=edge)
        if (
            note_side is Side.INWARD
            and note.supplier_note_date is not None
            and not period.from_date <= note.supplier_note_date <= period.to_date
        ):
            warnings.add(
                "inward_note_date_outside_period",
                **doc,
                detail=f"Supplier's date: {note.supplier_note_date.isoformat()}",
            )


def _not_tracked(key: str, table: str, label: str, note: str | None = None) -> WorksheetRow:
    return WorksheetRow(key=key, table=table, label=label, source=NOT_TRACKED, note=note)


def _from_books(
    key: str,
    table: str,
    label: str,
    amounts: _Amounts,
    *,
    note: str,
    components: tuple[RowComponent, ...] = (),
    with_taxable: bool = True,
) -> WorksheetRow:
    return WorksheetRow(
        key=key,
        table=table,
        label=label,
        source=FROM_BOOKS,
        note=note,
        taxable_value=_money(amounts.taxable_value) if with_taxable else None,
        igst=_money(amounts.igst),
        cgst=_money(amounts.cgst),
        sgst=_money(amounts.sgst),
        components=components,
    )


def _component(label: str, amounts: _Amounts, *, with_taxable: bool = True) -> RowComponent:
    return RowComponent(
        label=label,
        taxable_value=_money(amounts.taxable_value) if with_taxable else None,
        igst=_money(amounts.igst),
        cgst=_money(amounts.cgst),
        sgst=_money(amounts.sgst),
    )


def _section_3_1(tally: _Tally, net_taxed: _Amounts, net_zero: _Amounts) -> WorksheetSection:
    return WorksheetSection(
        key="3.1",
        title="3.1 Outward supplies and inward supplies liable to reverse charge",
        rows=(
            _from_books(
                "3.1a",
                "3.1(a)",
                "Outward taxable supplies (other than zero rated, nil rated and exempted)",
                net_taxed,
                note="Sales lines above 0%, less credit notes you issued. Purchases and supplier notes never reach this row.",
                components=(
                    _component("Sales invoices", tally.sales),
                    _component("Less: credit notes issued", tally.outward_notes),
                ),
            ),
            _from_books(
                "3.1-unclassified",
                "3.1 unclassified",
                "Unclassified 0% outward supplies",
                net_zero,
                note="Sales lines at 0%, less their credit notes. Could belong in 3.1(a), (b), (c) or (e); your books do not say which.",
                components=(
                    _component("Sales invoices at 0%", tally.sales_zero),
                    _component("Less: credit notes issued at 0%", tally.outward_notes_zero),
                ),
            ),
            _not_tracked("3.1b", "3.1(b)", "Outward taxable supplies (zero rated)", "Exports and SEZ supplies are not recorded."),
            _not_tracked("3.1c", "3.1(c)", "Other outward supplies (nil rated, exempted)", "Nil rated and exempt supplies are not told apart."),
            _not_tracked("3.1d", "3.1(d)", "Inward supplies liable to reverse charge", "Reverse charge is not recorded."),
            _not_tracked("3.1e", "3.1(e)", "Non-GST outward supplies", "Non-GST supplies are not recorded."),
            _not_tracked("3.1.1i", "3.1.1(i)", "Supplies on which an e-commerce operator pays tax under section 9(5)"),
            _not_tracked("3.1.1ii", "3.1.1(ii)", "Supplies made through an e-commerce operator who pays tax under section 9(5)"),
            _not_tracked("cess", "Cess", "Cess, in every table", "Cess is not recorded on invoices."),
        ),
    )


def _section_3_2() -> WorksheetSection:
    return WorksheetSection(
        key="3.2",
        title="3.2 Inter-state supplies, of those shown in 3.1",
        note=TABLE_3_2_NOTE,
        rows=(
            _not_tracked("3.2-unregistered", "3.2", "Supplies made to unregistered persons"),
            _not_tracked("3.2-composition", "3.2", "Supplies made to composition taxable persons"),
            _not_tracked("3.2-uin", "3.2", "Supplies made to UIN holders"),
        ),
    )


def _section_4(tally: _Tally, net_itc: _Amounts) -> WorksheetSection:
    return WorksheetSection(
        key="4",
        title="4 Eligible input tax credit",
        rows=(
            _not_tracked("4a1", "4(A)(1)", "Import of goods"),
            _not_tracked("4a2", "4(A)(2)", "Import of services"),
            _not_tracked("4a3", "4(A)(3)", "Inward supplies liable to reverse charge"),
            _not_tracked("4a4", "4(A)(4)", "Inward supplies from ISD"),
            _from_books(
                "4a5",
                "4(A)(5)",
                "All other ITC",
                net_itc,
                with_taxable=False,
                note="GST on purchases, less supplier credit notes, which reduce 4(A) on the portal. Sales never reach this row. Every purchase is counted as eligible.",
                components=(
                    _component("GST on purchases", tally.purchases, with_taxable=False),
                    _component("Less: supplier credit notes", tally.inward_notes, with_taxable=False),
                ),
            ),
            _not_tracked("4b1", "4(B)(1)", "ITC reversed: rules 38, 42, 43 and blocked credit under section 17(5)"),
            _not_tracked(
                "4b2",
                "4(B)(2)",
                "ITC reversed: others",
                "Reclaimable reversals, such as rule 37, are not recorded. Supplier credit notes are not here: they have reduced 4(A) since the January 2023 period.",
            ),
            _from_books(
                "4c",
                "4(C)",
                "Net ITC available",
                net_itc,
                with_taxable=False,
                note="Worked out from the rows above that come from your books, which today means 4(A)(5) alone.",
            ),
            _not_tracked("4d1", "4(D)(1)", "ITC reclaimed which was reversed in an earlier period"),
            _not_tracked("4d2", "4(D)(2)", "Ineligible ITC: section 16(4) and place of supply"),
        ),
    )


def _section_5() -> WorksheetSection:
    return WorksheetSection(
        key="5",
        title="5 Exempt, nil rated and non-GST inward supplies",
        note=TABLE_5_1_NOTE,
        rows=(
            _not_tracked("5-exempt", "5", "From a composition supplier, exempt and nil rated supplies"),
            _not_tracked("5-nongst", "5", "Non-GST supplies"),
        ),
    )


def _setoff_table(net_taxed: _Amounts, net_zero: _Amounts, net_itc: _Amounts, warnings: _Warnings) -> SetOffTable:
    # Decimal up to here; compute_setoff is float arithmetic, so convert at this
    # edge and bring the result straight back to paise.
    output = {h: _money(getattr(net_taxed, h) + getattr(net_zero, h)) for h in HEADS}
    credit = {h: _money(getattr(net_itc, h)) for h in HEADS}
    result = compute_setoff(
        {h: float(v) for h, v in output.items()},
        {h: float(v) for h, v in credit.items()},
    )

    if any(v < 0 for v in output.values()):
        warnings.raise_("negative_output")
    if any(v < 0 for v in credit.values()):
        warnings.raise_("negative_itc")

    lines = []
    for head in ("igst", "cgst", "sgst"):
        outcome = getattr(result, head)
        lines.append(
            SetOffLine(
                head=head,
                output_tax=output[head],
                input_credit=credit[head],
                credit_used=_money(Decimal(str(outcome.credit_used))),
                payable=_money(Decimal(str(outcome.payable))),
                credit_carried_forward=_money(Decimal(str(outcome.credit_carried_forward))),
            )
        )

    return SetOffTable(
        source=FROM_BOOKS,
        note=(
            "Estimated from the rows above, using this period's figures only. It leaves out credit "
            "already in your electronic credit ledger. What you actually pay is what the portal shows."
        ),
        lines=tuple(lines),
        total_payable=sum((line.payable for line in lines), Decimal("0.00")),
        total_credit_carried_forward=sum((line.credit_carried_forward for line in lines), Decimal("0.00")),
        rows=(
            _not_tracked("6.1-rcm", "6.1", "Tax on reverse charge, which is paid in cash only"),
            _not_tracked("6.1-cess", "6.1", "Cess"),
        ),
    )


def build_worksheet(
    period: ReturnPeriod,
    invoices: list[InvoiceDoc],
    notes: list[NoteDoc],
    *,
    company_gstin: str | None = None,
) -> Gstr3bWorksheet:
    """Build the worksheet for documents already selected for ``period``.

    The caller decides which documents fall in the period; this decides what
    each one counts as. Cancelled ones are refused here as well as by the query,
    so a slip in one place cannot put a cancelled document in a tax figure.
    """
    warnings = _Warnings()
    if not (company_gstin or "").strip() or gstin_problem(company_gstin):
        warnings.raise_("company_gstin")

    tally = _Tally()
    _read_invoices(invoices, period, tally, warnings)
    _read_notes(notes, period, tally, warnings)

    net_taxed = tally.sales.minus(tally.outward_notes)
    net_zero = tally.sales_zero.minus(tally.outward_notes_zero)
    net_itc = tally.purchases.minus(tally.inward_notes)

    setoff = _setoff_table(net_taxed, net_zero, net_itc, warnings)

    return Gstr3bWorksheet(
        title=TITLE,
        headline=HEADLINE,
        disclaimer=DISCLAIMER,
        period=period,
        warnings=warnings.build(),
        known_limits=KNOWN_LIMITS,
        sections=(
            _section_3_1(tally, net_taxed, net_zero),
            _section_3_2(),
            _section_4(tally, net_itc),
            _section_5(),
        ),
        setoff=setoff,
        table_5_1_note=TABLE_5_1_NOTE,
    )
