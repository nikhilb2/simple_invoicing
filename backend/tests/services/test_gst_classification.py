"""Which side of a return a document lands on. Pure rules, no database."""

from decimal import Decimal

import pytest

from src.services.gst_returns.classification import (
    NoteLine,
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
    to_decimal,
)


def _note_line(**overrides) -> NoteLine:
    values = {
        "gst_rate": Decimal("18"),
        "taxable": Decimal("100"),
        "tax": Decimal("18"),
        "quantity": Decimal("1"),
    }
    values.update(overrides)
    return NoteLine(**values)


@pytest.mark.parametrize(
    "voucher_type,status,expected",
    [
        ("sales", "active", Side.OUTWARD),
        ("purchase", "active", Side.INWARD),
        ("sales", "cancelled", Side.EXCLUDED),
        ("purchase", "cancelled", Side.EXCLUDED),
        # Other code in this repo treats "not sales" as purchase. Here it is neither.
        ("quotation", "active", Side.EXCLUDED),
        (None, "active", Side.EXCLUDED),
        ("sales", None, Side.EXCLUDED),
    ],
)
def test_invoice_sides_are_disjoint(voucher_type, status, expected):
    assert classify_invoice(voucher_type, status) is expected


@pytest.mark.parametrize(
    "direction,status,expected",
    [
        ("outward", "active", Side.OUTWARD),
        ("inward", "active", Side.INWARD),
        (None, "active", Side.OUTWARD),  # predates the direction column
        ("outward", "cancelled", Side.EXCLUDED),
        ("inward", "cancelled", Side.EXCLUDED),
        ("sideways", "active", Side.EXCLUDED),
    ],
)
def test_note_sides(direction, status, expected):
    assert classify_note(direction, status) is expected


def test_note_line_on_a_cancelled_invoice_is_excluded():
    line = _note_line(source_voucher_type="sales", source_status="cancelled")
    assert classify_note_line(Side.OUTWARD, line) is Side.EXCLUDED


def test_note_line_on_an_active_invoice_keeps_the_note_side():
    assert classify_note_line(Side.OUTWARD, _note_line(source_voucher_type="sales", source_status="active")) is Side.OUTWARD
    assert classify_note_line(Side.INWARD, _note_line(source_voucher_type="purchase", source_status="active")) is Side.INWARD


@pytest.mark.parametrize(
    "side,source,expected",
    [
        # Migration 20260904000001 stamped every older note outward, purchases included.
        (Side.OUTWARD, "purchase", Side.INWARD),
        (Side.INWARD, "sales", Side.OUTWARD),
        (Side.OUTWARD, "sales", Side.OUTWARD),
        (Side.INWARD, "purchase", Side.INWARD),
        (Side.OUTWARD, "quotation", Side.EXCLUDED),
        (Side.INWARD, "quotation", Side.EXCLUDED),
    ],
)
def test_note_line_side_follows_its_invoice_not_the_direction(side, source, expected):
    line = _note_line(source_voucher_type=source, source_status="active")
    assert classify_note_line(side, line) is expected


@pytest.mark.parametrize(
    "side,source,expected",
    [
        (Side.OUTWARD, "purchase", True),
        (Side.INWARD, "sales", True),
        (Side.OUTWARD, "sales", False),
        (Side.INWARD, "purchase", False),
        (Side.OUTWARD, "quotation", False),
        (Side.OUTWARD, None, False),
    ],
)
def test_direction_override_is_named_only_when_the_invoice_disagrees(side, source, expected):
    line = _note_line(source_voucher_type=source, source_status="active")
    assert note_line_overrides_direction(side, line) is expected


@pytest.mark.parametrize(
    "note_igst,source_is_igst,tax,expected",
    [
        (Decimal("18"), False, Decimal("18"), True),
        (Decimal("0"), True, Decimal("18"), True),
        (Decimal("18"), True, Decimal("18"), False),
        (Decimal("0"), False, Decimal("18"), False),
        (Decimal("0"), None, Decimal("18"), False),
        (Decimal("18"), False, Decimal("0"), False),
    ],
)
def test_note_head_differs_from_the_source_line(note_igst, source_is_igst, tax, expected):
    line = _note_line(tax=tax, source_line_is_igst=source_is_igst)
    assert note_line_head_differs(note_igst, line) is expected


def test_note_line_with_no_source_invoice_goes_by_direction():
    assert classify_note_line(Side.OUTWARD, _note_line()) is Side.OUTWARD


def test_a_cancelled_note_stays_excluded_whatever_its_lines_say():
    line = _note_line(source_voucher_type="sales", source_status="active")
    assert classify_note_line(Side.EXCLUDED, line) is Side.EXCLUDED


@pytest.mark.parametrize(
    "rate,expected",
    [
        (Decimal("0"), RateClass.UNCLASSIFIED_ZERO),
        (Decimal("0.00"), RateClass.UNCLASSIFIED_ZERO),
        (Decimal("0.1"), RateClass.TAXED),
        (Decimal("18"), RateClass.TAXED),
    ],
)
def test_rate_classes(rate, expected):
    assert classify_rate(rate) is expected


def test_inter_state_note_tax_is_all_igst():
    assert split_note_tax(Decimal("18.00"), Decimal("18.00")) == (Decimal("0"), Decimal("0"), Decimal("18.00"))


def test_intra_state_note_tax_halves_add_back_up_exactly():
    cgst, sgst, igst = split_note_tax(Decimal("0.03"), Decimal("0"))
    assert igst == 0
    assert cgst + sgst == Decimal("0.03")


@pytest.mark.parametrize(
    "gstin,expected_fragment",
    [
        ("27AAPFU0939F1ZV", None),
        (" 27aapfu0939f1zv ", None),
        (None, None),
        ("", None),
        ("   ", None),
        ("27AAPFU0939F1ZX", "check digit"),
        ("not-a-gstin", "15-character"),
        ("27AAPFU0939F1Z", "15-character"),
        ("88AAPFU0939F1ZV", "state code"),
    ],
)
def test_gstin_problem(gstin, expected_fragment):
    problem = gstin_problem(gstin)
    if expected_fragment is None:
        assert problem is None
    else:
        assert expected_fragment in problem


def test_is_unregistered_means_no_gstin_at_all():
    assert is_unregistered(None) and is_unregistered("") and is_unregistered("  ")
    # A bad GSTIN is a different problem and gets its own warning.
    assert not is_unregistered("not-a-gstin")


def test_full_return_on_a_tax_inclusive_line_is_flagged():
    # Two at 118 inclusive of 18%: the line's taxable is 200. Returning one
    # stores 118 taxable (#572), when its share of the line is 100.
    line = _note_line(
        taxable=Decimal("118"),
        quantity=Decimal("1"),
        source_line_taxable=Decimal("200"),
        source_line_quantity=Decimal("2"),
    )
    assert note_line_exceeds_source("return", line)


def test_return_at_its_share_of_the_line_is_not_flagged():
    line = _note_line(
        taxable=Decimal("100"),
        quantity=Decimal("1"),
        source_line_taxable=Decimal("200"),
        source_line_quantity=Decimal("2"),
    )
    assert not note_line_exceeds_source("return", line)


def test_discount_note_is_measured_against_the_whole_line():
    within = _note_line(taxable=Decimal("150"), source_line_taxable=Decimal("200"), source_line_quantity=Decimal("2"))
    over = _note_line(taxable=Decimal("250"), source_line_taxable=Decimal("200"), source_line_quantity=Decimal("2"))
    assert not note_line_exceeds_source("discount", within)
    assert note_line_exceeds_source("discount", over)


def test_to_decimal_does_not_carry_float_noise():
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(None) == Decimal("0")
