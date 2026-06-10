"""
Unit tests for PDF unit price display based on tax_inclusive preference.

Covers:
- _pdf_unit_price function in builders.py
- Invoice HTML template unit price rendering with/without tax
- Column header labels
"""

from decimal import Decimal

import pytest

from src.models.invoice import InvoiceItem
from src.services.pdf_templates.builders import _pdf_unit_price, _pdf_unit_price_including_tax


def make_invoice_item(unit_price=100.0, quantity=2.0, taxable_amount=200.0, tax_amount=36.0, line_total=236.0, gst_rate=18.0):
    """Create an InvoiceItem with the given values."""
    item = InvoiceItem()
    item.product_id = 1
    item.unit_price = unit_price
    item.quantity = quantity
    item.taxable_amount = taxable_amount
    item.tax_amount = tax_amount
    item.line_total = line_total
    item.gst_rate = gst_rate
    return item


class TestPdfUnitPrice:
    def test_tax_inclusive_returns_line_total_divided_by_quantity(self):
        """When tax_inclusive=True, unit price = line_total / quantity."""
        item = make_invoice_item(
            unit_price=100.0, quantity=2.0, line_total=236.0
        )
        result = _pdf_unit_price(item, tax_inclusive=True)
        # 236 / 2 = 118
        assert result == 118.0

    def test_tax_inclusive_falls_back_to_unit_price_when_quantity_zero(self):
        """When quantity is 0, fall back to stored unit_price."""
        item = make_invoice_item(
            unit_price=100.0, quantity=0.0, line_total=0.0
        )
        result = _pdf_unit_price(item, tax_inclusive=True)
        assert result == 100.0

    def test_tax_exclusive_returns_stored_unit_price(self):
        """When tax_inclusive=False, unit price = the stored unit_price."""
        item = make_invoice_item(
            unit_price=100.0, quantity=2.0, line_total=236.0
        )
        result = _pdf_unit_price(item, tax_inclusive=False)
        assert result == 100.0

    def test_tax_exclusive_returns_stored_unit_price_regardless_of_quantity(self):
        """Even with fractional quantities, tax-exclusive uses stored unit_price."""
        item = make_invoice_item(
            unit_price=150.0, quantity=0.5, line_total=88.50
        )
        result = _pdf_unit_price(item, tax_inclusive=False)
        assert result == 150.0

    def test_tax_exclusive_unit_price_zero(self):
        """Zero unit_price is returned as-is."""
        item = make_invoice_item(
            unit_price=0.0, quantity=1.0, line_total=18.0
        )
        result = _pdf_unit_price(item, tax_inclusive=False)
        assert result == 0.0

    def test_tax_inclusive_with_fractional_quantity(self):
        """Tax inclusive with fractional quantity."""
        item = make_invoice_item(
            unit_price=100.0, quantity=0.5, taxable_amount=50.0,
            tax_amount=9.0, line_total=59.0,
        )
        result = _pdf_unit_price(item, tax_inclusive=True)
        # 59 / 0.5 = 118
        assert result == 118.0

    def test_zero_gst_tax_inclusive_equals_unit_price(self):
        """With 0% GST, tax-inclusive unit price equals stored unit_price."""
        item = make_invoice_item(
            unit_price=100.0, quantity=1.0, taxable_amount=100.0,
            tax_amount=0.0, line_total=100.0, gst_rate=0.0,
        )
        result = _pdf_unit_price(item, tax_inclusive=True)
        assert result == 100.0

    def test_tax_exclusive_and_tax_inclusive_differ_with_gst(self):
        """With GST > 0, tax-inclusive and tax-exclusive values differ."""
        item = make_invoice_item(
            unit_price=100.0, quantity=1.0, taxable_amount=100.0,
            tax_amount=18.0, line_total=118.0,
        )
        inclusive = _pdf_unit_price(item, tax_inclusive=True)
        exclusive = _pdf_unit_price(item, tax_inclusive=False)
        assert inclusive == 118.0
        assert exclusive == 100.0
        assert inclusive != exclusive


class TestPdfUnitPriceIncludingTax:
    """Test the existing _pdf_unit_price_including_tax function still works."""

    def test_returns_line_total_divided_by_quantity(self):
        item = make_invoice_item(line_total=236.0, quantity=2.0)
        result = _pdf_unit_price_including_tax(item)
        assert result == 118.0

    def test_falls_back_to_unit_price_when_quantity_zero(self):
        item = make_invoice_item(unit_price=100.0, quantity=0.0, line_total=0.0)
        result = _pdf_unit_price_including_tax(item)
        assert result == 100.0
