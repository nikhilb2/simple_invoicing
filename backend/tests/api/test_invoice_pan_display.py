from datetime import datetime
from pathlib import Path
import os
import sys
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from src.services.pdf_templates.invoice_template import _build_invoice_html
from src.services.pdf_templates.purchase_template import _build_purchase_invoice_html, _extract_pan_from_gstin
from src.models.invoice import Invoice, InvoiceItem


def _invoice_base(voucher_type: str = "sales") -> Invoice:
    invoice = Invoice(
        id=1,
        invoice_number="INV-001",
        ledger_name="Buyer One",
        ledger_address="Buyer Address",
        company_name="Seller One",
        company_address="Seller Address",
        company_currency_code="INR",
        voucher_type=voucher_type,
        created_by=1,
        taxable_amount=0,
        total_tax_amount=0,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=0,
        total_amount=0,
        invoice_date=datetime(2026, 4, 15),
    )
    invoice.items = []
    return invoice


def _line_item(product_id: int = 1, quantity: float = 2):
    return InvoiceItem(
        product_id=product_id,
        hsn_sac="1234",
        quantity=quantity,
        unit_price=100,
        tax_amount=0,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=0,
        line_total=200,
        description=None,
    )


def test_extract_pan_from_gstin_returns_pan_for_valid_gstin():
    assert _extract_pan_from_gstin("07AAMPB1274B1Z8") == "AAMPB1274B"


def test_extract_pan_from_gstin_returns_none_for_missing_or_invalid_gstin():
    assert _extract_pan_from_gstin(None) is None
    assert _extract_pan_from_gstin("") is None
    assert _extract_pan_from_gstin("07AAMPB1274B1Z") is None


def test_sales_html_shows_pan_only_when_corresponding_gst_exists():
    invoice = _invoice_base("sales")
    invoice.company_gst = "07AAMPB1274B1Z8"
    invoice.ledger_gst = None

    html = _build_invoice_html(invoice, [])

    assert "GST: 07AAMPB1274B1Z8" in html
    assert "PAN: AAMPB1274B" in html
    assert "PAN:" not in html.split("Bill to", 1)[1]


def test_purchase_html_shows_supplier_and_company_pan_when_gst_present():
    invoice = _invoice_base("purchase")
    invoice.ledger_gst = "29ABCDE1234F1Z5"
    invoice.company_gst = "07AAMPB1274B1Z8"

    html = _build_purchase_invoice_html(invoice, [])

    assert "GST: 29ABCDE1234F1Z5" in html
    assert "PAN: ABCDE1234F" in html
    assert "GST: 07AAMPB1274B1Z8" in html
    assert "PAN: AAMPB1274B" in html


def test_sales_pdf_tax_breakup_shows_only_igst_for_interstate_case():
    invoice = _invoice_base("sales")
    invoice.taxable_amount = 100
    invoice.total_tax_amount = 18
    invoice.cgst_amount = 0
    invoice.sgst_amount = 0
    invoice.igst_amount = 18

    html = _build_invoice_html(invoice, [])

    assert "IGST:" in html
    assert "CGST:" not in html
    assert "SGST:" not in html


def test_purchase_pdf_tax_breakup_shows_only_cgst_sgst_for_intrastate_case():
    invoice = _invoice_base("purchase")
    invoice.taxable_amount = 100
    invoice.total_tax_amount = 18
    invoice.cgst_amount = 9
    invoice.sgst_amount = 9
    invoice.igst_amount = 0

    html = _build_purchase_invoice_html(invoice, [])

    assert "CGST:" in html
    assert "SGST:" in html
    assert "IGST:" not in html


def test_sales_pdf_shows_unit_column_and_abbreviates_pieces():
    invoice = _invoice_base("sales")
    invoice.items = [_line_item(product_id=11)]
    product = SimpleNamespace(id=11, name="Steel Rod", sku="ROD-1", hsn_sac="7214", unit="Pieces")

    html = _build_invoice_html(invoice, [product])

    assert "<th>Unit</th>" in html
    assert "<td>Pcs</td>" in html


def test_purchase_pdf_shows_unit_column_and_keeps_custom_unit():
    invoice = _invoice_base("purchase")
    invoice.items = [_line_item(product_id=12)]
    product = SimpleNamespace(id=12, name="Flour", sku="FLR-1", hsn_sac="1101", unit="Kg")

    html = _build_purchase_invoice_html(invoice, [product])

    assert "<th>Unit</th>" in html
    assert "<td>Kg</td>" in html


def test_pdf_quantity_hides_trailing_zeroes_for_whole_number_product():
    invoice = _invoice_base("sales")
    invoice.items = [_line_item(product_id=21, quantity=1)]
    product = SimpleNamespace(id=21, name="Whole Item", sku="W-1", hsn_sac="7214", unit="Pieces", allow_decimal=False)

    html = _build_invoice_html(invoice, [product])

    assert '<td class="right">1</td>' in html
    assert '<td class="right">1.000</td>' not in html


def test_pdf_quantity_keeps_decimal_for_decimal_enabled_product():
    invoice = _invoice_base("sales")
    invoice.items = [_line_item(product_id=22, quantity=1.5)]
    product = SimpleNamespace(id=22, name="Decimal Item", sku="D-1", hsn_sac="7214", unit="Kg", allow_decimal=True)

    html = _build_invoice_html(invoice, [product])

    assert '<td class="right">1.5</td>' in html


def test_sales_pdf_shows_unit_price_without_tax_when_tax_inclusive_false():
    """When tax_inclusive=False, the unit price column should show stored unit_price and label says (without tax)."""
    invoice = _invoice_base("sales")
    invoice.tax_inclusive = False
    item = InvoiceItem(
        product_id=1,
        hsn_sac="1234",
        quantity=2.0,
        unit_price=100.0,
        tax_amount=36.0,
        cgst_amount=18.0,
        sgst_amount=18.0,
        igst_amount=0.0,
        line_total=236.0,
        description=None,
    )
    invoice.items = [item]
    product = SimpleNamespace(id=1, name="Widget", sku="W-1", hsn_sac="1234", unit="Pieces", allow_decimal=False)

    html = _build_invoice_html(invoice, [product])

    assert "(without tax)" in html
    assert "₹100.00" in html  # unit price = stored unit_price (not with tax)


def test_sales_pdf_shows_unit_price_with_tax_when_tax_inclusive_true():
    """When tax_inclusive=True, the unit price column should show line_total/quantity and label says (with tax)."""
    invoice = _invoice_base("sales")
    invoice.tax_inclusive = True
    item = InvoiceItem(
        product_id=1,
        hsn_sac="1234",
        quantity=2.0,
        unit_price=100.0,
        tax_amount=36.0,
        cgst_amount=18.0,
        sgst_amount=18.0,
        igst_amount=0.0,
        line_total=236.0,
        description=None,
    )
    invoice.items = [item]
    product = SimpleNamespace(id=1, name="Widget", sku="W-1", hsn_sac="1234", unit="Pieces", allow_decimal=False)

    html = _build_invoice_html(invoice, [product])

    assert "(with tax)" in html
    assert "₹118.00" in html  # unit price = line_total / quantity = 236/2 = 118


def test_purchase_pdf_shows_unit_price_without_tax_when_tax_inclusive_false():
    """When tax_inclusive=False on a purchase invoice, unit price shows stored unit_price."""
    invoice = _invoice_base("purchase")
    invoice.tax_inclusive = False
    item = InvoiceItem(
        product_id=1,
        hsn_sac="1234",
        quantity=1.0,
        unit_price=500.0,
        tax_amount=90.0,
        cgst_amount=45.0,
        sgst_amount=45.0,
        igst_amount=0.0,
        line_total=590.0,
        description=None,
    )
    invoice.items = [item]
    product = SimpleNamespace(id=1, name="Widget", sku="W-1", hsn_sac="1234", unit="Pieces", allow_decimal=False)

    html = _build_purchase_invoice_html(invoice, [product])

    assert "(without tax)" in html
    assert "₹500.00" in html  # stored unit_price, not inclusive


def test_purchase_pdf_shows_unit_price_with_tax_when_tax_inclusive_true():
    """When tax_inclusive=True on a purchase invoice, unit price shows line_total/quantity."""
    invoice = _invoice_base("purchase")
    invoice.tax_inclusive = True
    item = InvoiceItem(
        product_id=1,
        hsn_sac="1234",
        quantity=1.0,
        unit_price=500.0,
        tax_amount=90.0,
        cgst_amount=45.0,
        sgst_amount=45.0,
        igst_amount=0.0,
        line_total=590.0,
        description=None,
    )
    invoice.items = [item]
    product = SimpleNamespace(id=1, name="Widget", sku="W-1", hsn_sac="1234", unit="Pieces", allow_decimal=False)

    html = _build_purchase_invoice_html(invoice, [product])

    assert "(with tax)" in html
    assert "₹590.00" in html  # line_total / quantity = 590/1 = 590


def test_sales_pdf_defaults_to_without_tax_when_tax_inclusive_not_set():
    """When tax_inclusive is not explicitly set (defaults to False/None), show without tax."""
    invoice = _invoice_base("sales")
    # tax_inclusive defaults to False on the model
    item = InvoiceItem(
        product_id=1,
        hsn_sac="1234",
        quantity=1.0,
        unit_price=100.0,
        tax_amount=18.0,
        cgst_amount=9.0,
        sgst_amount=9.0,
        igst_amount=0.0,
        line_total=118.0,
        description=None,
    )
    invoice.items = [item]
    product = SimpleNamespace(id=1, name="Widget", sku="W-1", hsn_sac="1234", unit="Pieces", allow_decimal=False)

    html = _build_invoice_html(invoice, [product])

    assert "(without tax)" in html
    assert "₹100.00" in html
