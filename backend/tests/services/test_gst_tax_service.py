"""Database-free regression coverage for GST helper calculations."""

from decimal import Decimal

import pytest

from src.models.invoice import Invoice, InvoiceItem
from src.services.gst_tax_service import (
    assign_invoice_tax_totals,
    assign_item_tax_split,
    calculate_tax_totals,
    is_interstate_supply,
    money,
)


def make_item(
    *,
    taxable_amount="100.00",
    tax_amount="18.00",
    gst_rate="18.00",
    cgst_amount="0",
    sgst_amount="0",
    igst_amount="0",
):
    """Construct an unsaved invoice item; no database fixture is required."""
    def amount(value):
        return None if value is None else Decimal(value)

    return InvoiceItem(
        invoice_id=1,
        product_id=1,
        quantity=Decimal("1"),
        unit_price=Decimal("100"),
        taxable_amount=amount(taxable_amount),
        tax_amount=amount(tax_amount),
        gst_rate=amount(gst_rate),
        cgst_amount=amount(cgst_amount),
        sgst_amount=amount(sgst_amount),
        igst_amount=amount(igst_amount),
        line_total=Decimal("118"),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2.675", "2.68"),
        ("-2.675", "-2.68"),
        ("2.674", "2.67"),
        ("0", "0.00"),
    ],
)
def test_money_rounds_half_up(value, expected):
    assert money(Decimal(value)) == Decimal(expected)


@pytest.mark.parametrize(
    ("company_gst", "ledger_gst", "expected"),
    [
        ("07AAAA", "07BBBB", False),
        ("07AAAA", "29BBBB", True),
        (None, "29BBBB", False),
        ("", "29BBBB", False),
        ("0", "29BBBB", False),
        ("07AAAA", None, False),
        ("07AAAA", "", False),
        ("07AAAA", "2", False),
        (None, None, False),
    ],
)
def test_is_interstate_supply_checks_both_gstins(company_gst, ledger_gst, expected):
    assert is_interstate_supply(company_gst, ledger_gst) is expected


def test_calculate_tax_totals_rounds_each_item_before_adding():
    items = [
        make_item(cgst_amount="1.005", sgst_amount="0.335", igst_amount="1.335"),
        make_item(cgst_amount="2.005", sgst_amount="0.335", igst_amount="2.335"),
    ]

    assert calculate_tax_totals(items) == (
        Decimal("3.02"), Decimal("0.68"), Decimal("3.68")
    )


def test_calculate_tax_totals_treats_none_as_zero():
    items = [
        make_item(cgst_amount=None, sgst_amount="1.25", igst_amount=None),
        make_item(cgst_amount="2.50", sgst_amount=None, igst_amount="3.75"),
    ]

    assert calculate_tax_totals(items) == (
        Decimal("2.50"), Decimal("1.25"), Decimal("3.75")
    )


def test_calculate_tax_totals_accepts_no_items():
    assert calculate_tax_totals([]) == (
        Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
    )


def test_assign_item_tax_split_intrastate_uses_equal_rounded_halves():
    item = make_item(taxable_amount="100.10", gst_rate="18", tax_amount="18.02")

    assign_item_tax_split([item], interstate_supply=False)

    assert Decimal(str(item.cgst_amount)) == Decimal("9.01")
    assert Decimal(str(item.sgst_amount)) == Decimal("9.01")
    assert Decimal(str(item.igst_amount)) == Decimal("0.0")
    assert Decimal(str(item.tax_amount)) == Decimal("18.02")
    assert Decimal(str(item.line_total)) == Decimal("118.12")


def test_assign_item_tax_split_interstate_uses_full_igst():
    item = make_item(taxable_amount="100.005", tax_amount="18.005")

    assign_item_tax_split([item], interstate_supply=True)

    assert Decimal(str(item.cgst_amount)) == Decimal("0.0")
    assert Decimal(str(item.sgst_amount)) == Decimal("0.0")
    assert Decimal(str(item.igst_amount)) == Decimal("18.01")
    assert Decimal(str(item.tax_amount)) == Decimal("18.01")
    assert Decimal(str(item.line_total)) == Decimal("118.02")


def test_assign_item_tax_split_handles_empty_items():
    assert assign_item_tax_split([], interstate_supply=True) is None
    assert assign_item_tax_split([], interstate_supply=False) is None


@pytest.mark.parametrize(
    ("interstate", "cgst", "sgst", "igst"),
    [
        (False, "1.25", "1.25", "0"),
        (True, "0", "0", "2.50"),
    ],
)
def test_assign_invoice_tax_totals_updates_unsaved_invoice(interstate, cgst, sgst, igst):
    invoice = Invoice(created_by=1, total_amount=Decimal("0"))
    item = make_item(cgst_amount=cgst, sgst_amount=sgst, igst_amount=igst)

    total = assign_invoice_tax_totals(invoice, [item], interstate_supply=interstate)

    assert total == Decimal("2.50")
    assert Decimal(str(invoice.cgst_amount)) == Decimal(cgst)
    assert Decimal(str(invoice.sgst_amount)) == Decimal(sgst)
    assert Decimal(str(invoice.igst_amount)) == Decimal(igst)
    assert Decimal(str(invoice.total_tax_amount)) == Decimal("2.50")
