"""The worksheet calculation, with plain documents and no database.

Circular 170/02/2022's Annexure is deliberately not a golden case here. Its worked
Table 4 needs 4(A)(1) to (4), 4(B)(1), 4(B)(2) and 4(D)(2) as inputs, and in this
phase those rows are not_tracked with nowhere to put a figure. It should become one
when manual rows arrive; see test_table_4_rows_the_circular_needs_are_not_inputs.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.schemas.gstr3b import Gstr3bWorksheetOut
from src.services.gst_returns.classification import InvoiceDoc, InvoiceLine, NoteDoc, NoteLine
from src.services.gst_returns.gstr3b import (
    DISCLAIMER,
    FROM_BOOKS,
    NOT_TRACKED,
    InvalidReturnPeriod,
    build_worksheet,
    resolve_return_period,
)
from src.services.gst_returns.setoff import compute_setoff

JUNE = resolve_return_period(date(2026, 6, 1), date(2026, 6, 30))
VALID_GSTIN = "27AAPFU0939F1ZV"


def _d(value) -> Decimal:
    return Decimal(str(value))


def _line(taxable, rate=18, *, inter=False, tax=None) -> InvoiceLine:
    taxable = _d(taxable)
    rate = _d(rate)
    tax = _d(tax) if tax is not None else (taxable * rate / 100).quantize(Decimal("0.01"))
    if inter:
        cgst, sgst, igst = Decimal("0"), Decimal("0"), tax
    else:
        cgst = sgst = (tax / 2).quantize(Decimal("0.01"))
        igst = Decimal("0")
    return InvoiceLine(gst_rate=rate, taxable=taxable, tax=tax, cgst=cgst, sgst=sgst, igst=igst)


def _invoice(*lines, voucher="sales", status="active", gst=VALID_GSTIN, number="INV-1", doc_id=1, discount=0) -> InvoiceDoc:
    return InvoiceDoc(
        id=doc_id,
        number=number,
        voucher_type=voucher,
        status=status,
        ledger_gst=gst,
        lines=tuple(lines),
        invoice_discount=_d(discount),
    )


def _note(*lines, direction="outward", status="active", igst=0, note_type="return", number="CN-1", doc_id=10, supplier_date=None) -> NoteDoc:
    return NoteDoc(
        id=doc_id,
        number=number,
        direction=direction,
        status=status,
        note_type=note_type,
        igst_total=_d(igst),
        lines=tuple(lines),
        supplier_note_date=supplier_date,
    )


def _note_line(taxable, rate=18, source_voucher=None, source_status=None, **extra) -> NoteLine:
    taxable = _d(taxable)
    rate = _d(rate)
    return NoteLine(
        gst_rate=rate,
        taxable=taxable,
        tax=(taxable * rate / 100).quantize(Decimal("0.01")),
        quantity=Decimal("1"),
        source_voucher_type=source_voucher,
        source_status=source_status,
        **extra,
    )


def _sheet(invoices=(), notes=(), gstin=VALID_GSTIN):
    return build_worksheet(JUNE, list(invoices), list(notes), company_gstin=gstin)


def _row(sheet, key):
    for section in sheet.sections:
        for row in section.rows:
            if row.key == key:
                return row
    raise AssertionError(f"no row {key}")


def _head(sheet, head):
    return next(line for line in sheet.setoff.lines if line.head == head)


def _warning(sheet, code):
    return next((warning for warning in sheet.warnings if warning.code == code), None)


# --- period rules -----------------------------------------------------------

@pytest.mark.parametrize(
    "start,end,kind,label",
    [
        (date(2026, 6, 1), date(2026, 6, 30), "month", "June 2026"),
        (date(2024, 2, 1), date(2024, 2, 29), "month", "February 2024"),
        (date(2026, 2, 1), date(2026, 2, 28), "month", "February 2026"),
        (date(2026, 4, 1), date(2026, 6, 30), "quarter", "Apr-Jun 2026"),
        (date(2026, 7, 1), date(2026, 9, 30), "quarter", "Jul-Sep 2026"),
        (date(2026, 10, 1), date(2026, 12, 31), "quarter", "Oct-Dec 2026"),
        (date(2027, 1, 1), date(2027, 3, 31), "quarter", "Jan-Mar 2027"),
    ],
)
def test_one_month_or_one_gst_quarter_is_accepted(start, end, kind, label):
    period = resolve_return_period(start, end)
    assert (period.kind, period.label) == (kind, label)


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 6, 1), date(2026, 6, 29)),  # short of the month
        (date(2026, 6, 2), date(2026, 6, 30)),  # starts late
        (date(2026, 2, 1), date(2026, 3, 1)),  # one day past the month
        (date(2026, 5, 1), date(2026, 7, 31)),  # three months, but not a GST quarter
        (date(2026, 4, 1), date(2026, 5, 31)),  # two months
        (date(2026, 4, 1), date(2027, 3, 31)),  # a financial year
        (date(2026, 12, 1), date(2027, 2, 28)),  # crosses the calendar year
        (date(2026, 6, 30), date(2026, 6, 1)),  # backwards
        (date(2026, 6, 15), date(2026, 6, 15)),  # one day
    ],
)
def test_anything_else_is_refused(start, end):
    with pytest.raises(InvalidReturnPeriod):
        resolve_return_period(start, end)


# --- which side a document lands on -----------------------------------------

def test_sales_reach_3_1a_and_never_table_4():
    sheet = _sheet([_invoice(_line(1000))])
    row = _row(sheet, "3.1a")
    assert (row.taxable_value, row.cgst, row.sgst, row.igst) == (_d("1000.00"), _d("90.00"), _d("90.00"), _d("0.00"))
    itc = _row(sheet, "4a5")
    assert (itc.cgst, itc.sgst, itc.igst) == (_d("0.00"), _d("0.00"), _d("0.00"))


def test_purchases_reach_4a5_and_never_3_1():
    sheet = _sheet([_invoice(_line(1000, inter=True), voucher="purchase")])
    itc = _row(sheet, "4a5")
    assert (itc.igst, itc.cgst, itc.sgst) == (_d("180.00"), _d("0.00"), _d("0.00"))
    # Table 4 holds tax only, so a purchase's value has nowhere to appear.
    assert itc.taxable_value is None
    for key in ("3.1a", "3.1-unclassified"):
        row = _row(sheet, key)
        assert (row.taxable_value, row.igst, row.cgst, row.sgst) == (_d("0.00"),) * 4


def test_outward_note_reduces_3_1a():
    sheet = _sheet([_invoice(_line(1000))], [_note(_note_line(100, source_voucher="sales", source_status="active"))])
    row = _row(sheet, "3.1a")
    assert (row.taxable_value, row.cgst, row.sgst) == (_d("900.00"), _d("81.00"), _d("81.00"))
    assert [c.label for c in row.components] == ["Sales invoices", "Less: credit notes issued"]
    assert row.components[1].taxable_value == _d("100.00")


def test_inward_note_stays_out_of_3_1_and_reduces_4a5():
    sheet = _sheet(
        [_invoice(_line(1000)), _invoice(_line(500), voucher="purchase", doc_id=2)],
        [_note(_note_line(100, source_voucher="purchase", source_status="active"), direction="inward", number="DN-1")],
    )
    row = _row(sheet, "3.1a")
    assert (row.taxable_value, row.cgst, row.sgst) == (_d("1000.00"), _d("90.00"), _d("90.00"))
    itc = _row(sheet, "4a5")
    assert (itc.cgst, itc.sgst) == (_d("36.00"), _d("36.00"))
    assert itc.components[1].label == "Less: supplier credit notes"


def test_supplier_notes_do_not_go_to_4b2():
    # The 2020 advisory put them in 4(B)(2). From the January 2023 period they
    # net into 4(A). Doing both would take them off twice.
    sheet = _sheet(
        [_invoice(_line(500), voucher="purchase")],
        [_note(_note_line(100, source_voucher="purchase", source_status="active"), direction="inward")],
    )
    assert _row(sheet, "4b2").source == NOT_TRACKED
    assert _row(sheet, "4b2").cgst is None
    assert (_row(sheet, "4c").cgst, _row(sheet, "4c").sgst) == (_d("36.00"), _d("36.00"))


def test_outward_note_against_a_purchase_cannot_reach_3_1():
    sheet = _sheet(
        [_invoice(_line(1000))],
        [_note(_note_line(100, source_voucher="purchase", source_status="active"), direction="outward")],
    )
    assert _row(sheet, "3.1a").taxable_value == _d("1000.00")
    assert _warning(sheet, "note_direction_conflict") is not None


def test_unknown_voucher_type_reaches_neither_side_and_is_reported():
    sheet = _sheet([_invoice(_line(1000), voucher="quotation")])
    assert _row(sheet, "3.1a").taxable_value == _d("0.00")
    assert _row(sheet, "4a5").cgst == _d("0.00")
    assert _warning(sheet, "unknown_voucher_type").documents[0].number == "INV-1"


# --- cancelled documents ----------------------------------------------------

def test_cancelled_invoices_count_for_nothing():
    sheet = _sheet([
        _invoice(_line(1000), status="cancelled"),
        _invoice(_line(1000), voucher="purchase", status="cancelled", doc_id=2),
    ])
    assert _row(sheet, "3.1a").taxable_value == _d("0.00")
    assert _row(sheet, "4a5").cgst == _d("0.00")


def test_cancelled_notes_count_for_nothing():
    sheet = _sheet([_invoice(_line(1000))], [_note(_note_line(100), status="cancelled")])
    assert _row(sheet, "3.1a").taxable_value == _d("1000.00")
    assert _warning(sheet, "note_direction_conflict") is None


def test_active_note_on_a_cancelled_invoice_is_left_out_and_named():
    sheet = _sheet(
        [_invoice(_line(1000))],
        [_note(_note_line(100, source_voucher="sales", source_status="cancelled", source_invoice_number="INV-9"), number="CN-7")],
    )
    assert _row(sheet, "3.1a").taxable_value == _d("1000.00")
    warning = _warning(sheet, "note_on_cancelled_invoice")
    assert warning.documents[0].number == "CN-7"
    assert "₹100.00 taxable" in warning.documents[0].detail
    assert "INV-9" in warning.documents[0].detail


def test_a_note_spanning_two_invoices_loses_only_the_cancelled_line():
    sheet = _sheet(
        [_invoice(_line(1000))],
        [_note(
            _note_line(100, source_voucher="sales", source_status="active"),
            _note_line(50, source_voucher="sales", source_status="cancelled"),
        )],
    )
    assert _row(sheet, "3.1a").taxable_value == _d("900.00")


# --- amounts ----------------------------------------------------------------

def test_tax_inclusive_lines_use_the_stored_ex_gst_value():
    # 118 inclusive of 18%: what the invoice processor stores is 100 and 18.
    sheet = _sheet([_invoice(InvoiceLine(
        gst_rate=_d(18), taxable=_d(100), tax=_d(18), cgst=_d(9), sgst=_d(9), igst=_d(0),
    ))])
    row = _row(sheet, "3.1a")
    assert (row.taxable_value, row.cgst, row.sgst) == (_d("100.00"), _d("9.00"), _d("9.00"))


def test_line_total_is_not_an_input():
    assert not hasattr(_line(100), "line_total")
    assert not hasattr(_note_line(100), "line_total")


def test_invoice_level_discount_stays_out_of_the_figures_and_is_named():
    sheet = _sheet([_invoice(_line(1000), discount=118)])
    row = _row(sheet, "3.1a")
    assert (row.taxable_value, row.cgst, row.sgst) == (_d("1000.00"), _d("90.00"), _d("90.00"))
    warning = _warning(sheet, "invoice_level_discount")
    assert warning.documents[0].detail == "Discount ₹118.00"


def test_decimal_sums_do_not_drift():
    # 0.1 added ten thousand times as a float comes to 1000.0000000001588.
    invoices = [_invoice(_line("0.10", tax="0.02"), doc_id=i) for i in range(10000)]
    assert _row(_sheet(invoices), "3.1a").taxable_value == _d("1000.00")


def test_tax_heads_differing_from_line_tax_are_reported():
    line = InvoiceLine(gst_rate=_d(18), taxable=_d(100), tax=_d(18), cgst=_d(0), sgst=_d(0), igst=_d(0))
    assert _warning(_sheet([_invoice(line)]), "tax_head_mismatch") is not None


# --- the zero-rate row ------------------------------------------------------

def test_zero_rate_sales_go_to_their_own_row_not_3_1a():
    sheet = _sheet([_invoice(_line(1000), _line(500, rate=0))])
    assert _row(sheet, "3.1a").taxable_value == _d("1000.00")
    row = _row(sheet, "3.1-unclassified")
    assert row.source == FROM_BOOKS
    assert row.taxable_value == _d("500.00")
    assert "Unclassified" in row.label
    assert _warning(sheet, "zero_rate_sales") is not None


def test_zero_rate_notes_reduce_the_zero_rate_row():
    sheet = _sheet(
        [_invoice(_line(500, rate=0))],
        [_note(_note_line(100, rate=0, source_voucher="sales", source_status="active"))],
    )
    assert _row(sheet, "3.1-unclassified").taxable_value == _d("400.00")
    assert _row(sheet, "3.1a").taxable_value == _d("0.00")


def test_zero_rate_purchases_add_no_credit_and_are_reported():
    sheet = _sheet([_invoice(_line(500, rate=0), voucher="purchase")])
    assert _row(sheet, "4a5").cgst == _d("0.00")
    assert _warning(sheet, "zero_rate_purchases").severity == "info"
    assert _warning(sheet, "zero_rate_sales") is None


# --- rows that are not tracked ----------------------------------------------

NOT_TRACKED_KEYS = [
    "3.1b", "3.1c", "3.1d", "3.1e", "3.1.1i", "3.1.1ii", "cess",
    "3.2-unregistered", "3.2-composition", "3.2-uin",
    "4a1", "4a2", "4a3", "4a4", "4b1", "4b2", "4d1", "4d2",
    "5-exempt", "5-nongst",
]


@pytest.mark.parametrize("key", NOT_TRACKED_KEYS)
def test_unsupported_rows_are_present_with_no_figures(key):
    row = _row(_sheet([_invoice(_line(1000))]), key)
    assert row.source == NOT_TRACKED
    # Null rather than zero: zero would read as "you have none".
    assert (row.taxable_value, row.igst, row.cgst, row.sgst) == (None, None, None, None)


def test_every_row_says_where_it_came_from():
    sheet = _sheet()
    sources = {row.source for section in sheet.sections for row in section.rows}
    assert sources == {FROM_BOOKS, NOT_TRACKED}
    assert sheet.setoff.source == FROM_BOOKS


def test_only_the_agreed_rows_come_from_books():
    sheet = _sheet()
    keys = {row.key for section in sheet.sections for row in section.rows if row.source == FROM_BOOKS}
    assert keys == {"3.1a", "3.1-unclassified", "4a5", "4c"}


def test_sections_are_in_the_order_of_the_page():
    assert [section.key for section in _sheet().sections] == ["3.1", "3.2", "4", "5"]


def test_table_3_2_says_why_it_is_empty():
    section = next(section for section in _sheet().sections if section.key == "3.2")
    assert "place of supply" in section.note


def test_table_5_1_is_a_fixed_note_about_the_portal():
    note = _sheet().table_5_1_note
    assert "5.1" in note and "portal" in note


def test_table_4_rows_the_circular_needs_are_not_inputs():
    # What stops Circular 170's Annexure being a golden case in this phase. If
    # build_worksheet ever grows these, replace this with the Annexure's figures:
    # 4(C) = 2,64,500 IGST, 1,22,500 CGST, 1,22,500 SGST.
    sheet = _sheet([_invoice(_line(1000), voucher="purchase")])
    for key in ("4a1", "4a2", "4a3", "4a4", "4b1", "4b2", "4d2"):
        assert _row(sheet, key).source == NOT_TRACKED


# --- 6.1 --------------------------------------------------------------------

def test_setoff_is_compute_setoff_on_the_net_figures():
    sheet = _sheet(
        [
            _invoice(_line(1000)),
            _invoice(_line(2000, inter=True), doc_id=2),
            _invoice(_line(500, inter=True), voucher="purchase", doc_id=3),
        ],
    )
    expected = compute_setoff({"cgst": 90, "sgst": 90, "igst": 360}, {"igst": 90})
    for head in ("cgst", "sgst", "igst"):
        line = _head(sheet, head)
        outcome = getattr(expected, head)
        assert float(line.output_tax) == outcome.output_tax
        assert float(line.input_credit) == outcome.input_credit
        assert float(line.credit_used) == outcome.credit_used
        assert float(line.payable) == outcome.payable
        assert float(line.credit_carried_forward) == outcome.credit_carried_forward


def test_igst_credit_is_set_off_in_the_order_that_leaves_least_to_pay():
    # The case #673 fixes, reaching the worksheet through compute_setoff.
    sheet = _sheet([
        _invoice(_line(1000, rate=20)),  # CGST 100, SGST 100
        _invoice(_line(100, rate=100, inter=True), voucher="purchase", doc_id=2),  # IGST 100
        _invoice(_line(1000, rate=10, tax=100), voucher="purchase", doc_id=3),
    ])
    assert sheet.setoff.total_payable == _d("0.00")


def test_zero_rate_row_tax_still_reaches_the_setoff():
    line = InvoiceLine(gst_rate=_d(0), taxable=_d(100), tax=_d(18), cgst=_d(9), sgst=_d(9), igst=_d(0))
    assert _head(_sheet([_invoice(line)]), "cgst").output_tax == _d("9.00")


def test_notes_above_sales_are_reported_and_handled_as_setoff_defines():
    sheet = _sheet(
        [_invoice(_line(100))],
        [_note(_note_line(1000, source_voucher="sales", source_status="active"))],
    )
    assert _head(sheet, "cgst").output_tax == _d("-81.00")
    assert _head(sheet, "cgst").payable == _d("0.00")
    assert _warning(sheet, "negative_output") is not None


def test_supplier_notes_above_purchases_become_liability():
    sheet = _sheet(
        [_invoice(_line(100), voucher="purchase")],
        [_note(_note_line(1000, source_voucher="purchase", source_status="active"), direction="inward")],
    )
    assert _head(sheet, "cgst").payable == _d("81.00")
    assert _warning(sheet, "negative_itc") is not None


def test_setoff_totals_add_up():
    sheet = _sheet([_invoice(_line(1000)), _invoice(_line(100, inter=True), voucher="purchase", doc_id=2)])
    assert sheet.setoff.total_payable == sum(line.payable for line in sheet.setoff.lines)
    assert sheet.setoff.total_credit_carried_forward == sum(line.credit_carried_forward for line in sheet.setoff.lines)


# --- warnings ---------------------------------------------------------------

def test_gst_from_an_unregistered_supplier_is_reported_with_its_tax():
    sheet = _sheet([_invoice(_line(1000), voucher="purchase", gst=None)])
    warning = _warning(sheet, "unregistered_supplier_gst")
    assert warning.documents[0].number == "INV-1"
    assert warning.documents[0].detail == "GST ₹180.00"
    # It is still counted, and the warning is what says so.
    assert _row(sheet, "4a5").cgst == _d("90.00")


def test_zero_rate_purchase_from_an_unregistered_supplier_is_not_that_warning():
    assert _warning(_sheet([_invoice(_line(500, rate=0), voucher="purchase", gst="")]), "unregistered_supplier_gst") is None


def test_invalid_gstin_is_reported_on_both_sides():
    sheet = _sheet([
        _invoice(_line(100), gst="27AAPFU0939F1ZX", number="S-1"),
        _invoice(_line(100), voucher="purchase", gst="nonsense", number="P-1", doc_id=2),
    ])
    documents = _warning(sheet, "invalid_gstin").documents
    assert [(d.number, d.kind) for d in documents] == [("S-1", "invoice"), ("P-1", "invoice")]
    assert "check digit" in documents[0].detail


def test_unregistered_buyer_is_reported_as_possibly_inter_state():
    sheet = _sheet([_invoice(_line(100), gst=None)])
    warning = _warning(sheet, "unregistered_buyer")
    assert "inter-state" in warning.title
    assert warning.documents[0].kind == "invoice"
    # Not the supplier warning: the two sides are told apart.
    assert _warning(sheet, "unregistered_supplier_gst") is None


def test_registered_documents_raise_no_gstin_warnings():
    sheet = _sheet([_invoice(_line(100)), _invoice(_line(100), voucher="purchase", doc_id=2)])
    assert {w.code for w in sheet.warnings} == set()


def test_company_gstin_problems_are_reported():
    assert _warning(_sheet(gstin=None), "company_gstin") is not None
    assert _warning(_sheet(gstin="29BAD"), "company_gstin") is not None
    assert _warning(_sheet(gstin=VALID_GSTIN), "company_gstin") is None


def test_oversized_note_is_flagged_but_used_as_stored():
    sheet = _sheet(
        [_invoice(_line(1000))],
        [_note(_note_line(
            118, source_voucher="sales", source_status="active",
            source_line_taxable=_d(200), source_line_quantity=_d(2),
        ))],
    )
    assert _row(sheet, "3.1a").taxable_value == _d("882.00")
    assert "#572" in _warning(sheet, "note_exceeds_source").message


def test_supplier_note_dated_outside_the_period_is_reported():
    inside = _note(_note_line(1), direction="inward", supplier_date=date(2026, 6, 30))
    outside = _note(_note_line(1), direction="inward", supplier_date=date(2026, 5, 31), number="DN-2", doc_id=11)
    warning = _warning(_sheet(notes=[inside, outside]), "inward_note_date_outside_period")
    assert [d.number for d in warning.documents] == ["DN-2"]


def test_known_limits_are_always_stated():
    limits = " ".join(_sheet().known_limits)
    for phrase in ("eligible input credit", "GSTR-2B", "Reverse charge", "Place of supply", "#607", "electronic credit ledger"):
        assert phrase in limits


# --- labelling and the wire format ------------------------------------------

def test_it_says_what_it_is():
    sheet = _sheet()
    assert sheet.headline == "Worksheet, not a return"
    for phrase in ("estimate", "your own books", "cross-checking", "not a filing", "take precedence"):
        assert phrase in DISCLAIMER


def test_converts_to_floats_and_nulls_at_the_edge():
    out = Gstr3bWorksheetOut.model_validate(_sheet([_invoice(_line(1000))]))
    payload = out.model_dump(mode="json")
    assert payload["period_type"] == "month"
    assert payload["from_date"] == "2026-06-01"
    row = next(r for s in payload["sections"] for r in s["rows"] if r["key"] == "3.1a")
    assert row["taxable_value"] == 1000.0
    untracked = next(r for s in payload["sections"] for r in s["rows"] if r["key"] == "3.1b")
    assert untracked["taxable_value"] is None
    assert payload["setoff"]["total_payable"] == 180.0
