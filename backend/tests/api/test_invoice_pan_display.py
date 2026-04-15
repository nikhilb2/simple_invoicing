from datetime import datetime
from pathlib import Path
import os
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from src.api.routes.invoices import _build_invoice_html, _build_purchase_invoice_html, _extract_pan_from_gstin
from src.models.invoice import Invoice


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
