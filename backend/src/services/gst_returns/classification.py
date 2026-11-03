"""Which side of a GST return a document belongs on.

Pure rules over plain values: no database, no FastAPI. The worksheet's accuracy
rules live here so they can be tested on their own:

* A sale is outward and a purchase is inward. Anything else is neither, so a
  voucher type this module has not heard of never lands in a tax figure.
* A cancelled document counts for nothing.
* An outward note reverses a sale. An inward note is the supplier's own credit
  note against a purchase: it reduces input credit and never output tax.

These are the plain-value documents the worksheet reads. They are built from the
models by :mod:`src.services.gst_returns.gstr3b_data` and carry amounts as stored,
so ``taxable`` is already ex-GST on a tax-inclusive invoice and already net of
any line discount. ``line_total`` is deliberately not carried at all: it mixes
tax into the value, and summing it is how a return ends up overstated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from src.core.validation import GSTIN_REGEX, is_valid_gstin_checksum

ZERO = Decimal("0")


class Side(str, Enum):
    OUTWARD = "outward"
    INWARD = "inward"
    EXCLUDED = "excluded"


class RateClass(str, Enum):
    TAXED = "taxed"
    # 0% could be nil rated, exempt, zero rated or non-GST. Nothing on the line
    # says which, so it is not ours to guess.
    UNCLASSIFIED_ZERO = "unclassified_zero"


def to_decimal(value: object) -> Decimal:
    """Coerce a stored amount to Decimal, through str to avoid float artefacts."""
    return Decimal(str(value if value is not None else 0))


@dataclass(frozen=True)
class InvoiceLine:
    gst_rate: Decimal
    taxable: Decimal
    tax: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal


@dataclass(frozen=True)
class InvoiceDoc:
    id: int
    number: str
    voucher_type: str
    status: str
    ledger_gst: str | None
    lines: tuple[InvoiceLine, ...]
    # The invoice-level discount, taken off the GST-inclusive total. It is on no
    # stored line or tax head (see services/invoice_discounts.py), so it is held
    # here only so the worksheet can say so.
    invoice_discount: Decimal = ZERO
    # When the invoice was stored. Naive, and UTC unless the user chose a date.
    invoice_date: datetime | None = None
    # Null on sales from before the column, whose tax the two GSTINs decided.
    place_of_supply: str | None = None


@dataclass(frozen=True)
class NoteLine:
    gst_rate: Decimal
    taxable: Decimal
    tax: Decimal
    quantity: Decimal
    source_invoice_number: str | None = None
    source_voucher_type: str | None = None
    source_status: str | None = None
    source_line_taxable: Decimal | None = None
    source_line_quantity: Decimal | None = None
    # Whether the source line was taxed as IGST. None when the line is unknown.
    source_line_is_igst: bool | None = None


@dataclass(frozen=True)
class NoteDoc:
    id: int
    number: str
    direction: str | None
    status: str
    note_type: str
    igst_total: Decimal
    lines: tuple[NoteLine, ...]
    supplier_note_date: date | None = None


def classify_invoice(voucher_type: str | None, status: str | None) -> Side:
    if status != "active":
        return Side.EXCLUDED
    if voucher_type == "sales":
        return Side.OUTWARD
    if voucher_type == "purchase":
        return Side.INWARD
    return Side.EXCLUDED


def classify_note(direction: str | None, status: str | None) -> Side:
    """Rows predating the direction column carry NULL, and those are all outward."""
    if status != "active":
        return Side.EXCLUDED
    resolved = direction or "outward"
    if resolved == "outward":
        return Side.OUTWARD
    if resolved == "inward":
        return Side.INWARD
    return Side.EXCLUDED


def classify_note_line(note_side: Side, line: NoteLine) -> Side:
    """A note line counts only if the invoice it reverses still counts, on that side.

    Cancelling an invoice does not touch the notes raised against it (#602), so
    an active note can point at a cancelled invoice. The sale is already gone
    from the figures; taking the note off as well would count the reversal twice.

    A line whose source invoice is unknown keeps the note's side: the note's own
    direction is the only evidence left, and that is what GSTR-1 goes by.

    When the source invoice is known its voucher type decides the side, as it does
    on the Tax Ledger: a note against a purchase reduces input credit and a note
    against a sale reduces output tax, whatever the note's own direction says.
    Migration 20260904000001 stamped every older note ``outward``, including those
    written against purchases. See :func:`note_line_overrides_direction`.
    """
    if note_side is Side.EXCLUDED:
        return Side.EXCLUDED
    if line.source_status is not None and line.source_status != "active":
        return Side.EXCLUDED
    if line.source_voucher_type is not None:
        return {"sales": Side.OUTWARD, "purchase": Side.INWARD}.get(line.source_voucher_type, Side.EXCLUDED)
    return note_side


def note_line_overrides_direction(note_side: Side, line: NoteLine) -> bool:
    """Whether the source invoice put this line on the other side from the note's direction."""
    if line.source_voucher_type is None:
        return False
    expected = {"sales": Side.OUTWARD, "purchase": Side.INWARD}.get(line.source_voucher_type)
    return expected is not None and expected is not note_side


def note_line_head_differs(note_igst_total: Decimal, line: NoteLine) -> bool:
    """Whether the note puts this line's tax on a different head from its invoice line.

    The note's heads follow its own header (see :func:`split_note_tax`); the Tax
    Ledger follows the source line. They differ only if the parties' states
    changed in between, for example a corrected GSTIN. A line with no tax has no
    head to differ on.
    """
    if line.source_line_is_igst is None or line.tax == 0:
        return False
    return (note_igst_total > 0) != line.source_line_is_igst


def classify_rate(gst_rate: Decimal) -> RateClass:
    return RateClass.UNCLASSIFIED_ZERO if gst_rate == 0 else RateClass.TAXED


def split_note_tax(tax: Decimal, note_igst_total: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """(cgst, sgst, igst) for one note line, which stores a single tax amount.

    The heads follow the note's own header, as the GSTR-1 export does. The two
    halves are made to add back up to ``tax`` exactly rather than each rounding
    the same way, so no paisa appears from nowhere on an odd legacy amount.
    """
    if note_igst_total > 0:
        return ZERO, ZERO, tax
    cgst = (tax / 2).quantize(Decimal("0.01"))
    return cgst, tax - cgst, ZERO


def gstin_problem(gstin: str | None) -> str | None:
    """Why a stored GSTIN would be rejected, or None if it is fine or absent.

    Reads rather than normalises: legacy rows predate the checks a new ledger is
    held to, and this has to report on them instead of raising.
    """
    value = (gstin or "").strip().upper()
    if not value:
        return None
    if not GSTIN_REGEX.fullmatch(value):
        return "not a valid 15-character GSTIN"
    state_code = int(value[:2])
    if not (1 <= state_code <= 38 or state_code in (97, 99)):
        return f"state code {value[:2]} does not exist"
    if not is_valid_gstin_checksum(value):
        return "check digit is wrong"
    return None


def is_unregistered(gstin: str | None) -> bool:
    return not (gstin or "").strip()


def note_line_exceeds_source(note_type: str, line: NoteLine) -> bool:
    """Whether a note line's stored value is more than the invoice line it reverses.

    A return or adjustment is measured against the quantity's share of the line;
    a discount note has no quantity of its own, so against the whole line.
    """
    if line.source_line_taxable is None:
        return False
    limit = line.source_line_taxable
    if note_type != "discount" and line.source_line_quantity:
        limit = limit * line.quantity / line.source_line_quantity
    return line.taxable - limit > Decimal("0.01")
