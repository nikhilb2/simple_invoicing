"""Purchase invoice PDF must show discounts, like the sales template does.

Regression: PINV-2026-27-157 carried a 3% invoice-level discount that was
applied to the total but never rendered, so the totals did not add up.
"""

from datetime import datetime
from decimal import Decimal

from src.models.invoice import Invoice, InvoiceItem
from src.services.pdf_templates.purchase_template import _build_purchase_invoice_html


def make_purchase_invoice(*, discount_type=None, discount_value=None, item_discount_type=None, item_discount_value=None):
    item = InvoiceItem(
        product_id=1,
        quantity=Decimal("2"),
        unit_price=Decimal("100.00"),
        gst_rate=Decimal("18.00"),
        taxable_amount=Decimal("200.00"),
        tax_amount=Decimal("36.00"),
        igst_amount=Decimal("36.00"),
        line_total=Decimal("236.00"),
        discount_type=item_discount_type,
        discount_value=item_discount_value,
    )
    return Invoice(
        id=1,
        invoice_number="PINV-TEST-1",
        voucher_type="purchase",
        company_currency_code="INR",
        company_gst="07AAMPB1274B1Z8",
        ledger_gst="24AAHCD0395H1ZQ",
        invoice_date=datetime(2026, 9, 24),
        tax_inclusive=False,
        apply_round_off=False,
        round_off_amount=Decimal("0"),
        taxable_amount=Decimal("200.00"),
        total_tax_amount=Decimal("36.00"),
        igst_amount=Decimal("36.00"),
        total_amount=Decimal("228.92"),
        discount_type=discount_type,
        discount_value=discount_value,
        items=[item],
    )


def test_shows_percentage_invoice_discount():
    html = _build_purchase_invoice_html(make_purchase_invoice(discount_type="percentage", discount_value=Decimal("3.00")), [])
    assert "Discount: 3%" in html


def test_shows_net_invoice_discount():
    html = _build_purchase_invoice_html(make_purchase_invoice(discount_type="net", discount_value=Decimal("50.00")), [])
    assert "Discount: " in html and " off</p>" in html


def test_shows_item_discount():
    html = _build_purchase_invoice_html(make_purchase_invoice(item_discount_type="percentage", item_discount_value=Decimal("5.00")), [])
    assert "Disc: 5%" in html


def test_no_discount_line_without_discount():
    html = _build_purchase_invoice_html(make_purchase_invoice(), [])
    assert "Discount:" not in html
    assert "Disc:" not in html


def test_type_without_value_shows_nothing():
    # A line can keep discount_type with an empty value (seen in production).
    html = _build_purchase_invoice_html(make_purchase_invoice(item_discount_type="percentage"), [])
    assert "Disc:" not in html
