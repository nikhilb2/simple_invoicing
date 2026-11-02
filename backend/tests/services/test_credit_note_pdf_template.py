"""The credit note PDF a customer receives.

Regression: credit notes had no document at all, so there was nothing to send
the customer from either the ledger or the credit notes page.
"""

from datetime import datetime
from decimal import Decimal

from src.models.buyer import Buyer
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.services.pdf_templates import _build_credit_note_html


def make_note(*, buyer_gst="27BBBBB0000B1ZT", status="active", credit_note_type="return"):
    invoice_item = InvoiceItem(id=11, product_id=5, hsn_sac="8471")
    invoice = Invoice(
        id=3,
        invoice_number="INV-0042",
        invoice_date=datetime(2026, 6, 1),
        company_name="Mofna Traders",
        company_gst="27AAAAA0000A1Z2",
        company_currency_code="INR",
        ledger_name="Acme & Sons",
        ledger_address="9 Buyer Lane",
        ledger_gst=buyer_gst,
    )
    item = CreditNoteItem(
        invoice_id=3,
        invoice_item_id=11,
        product_id=5,
        quantity=2,
        unit_price=Decimal("100.00"),
        gst_rate=Decimal("18.00"),
        taxable_amount=Decimal("200.00"),
        tax_amount=Decimal("36.00"),
        line_total=Decimal("236.00"),
    )
    item.invoice_item = invoice_item
    note = CreditNote(
        credit_note_number="CN/26/0007",
        credit_note_type=credit_note_type,
        direction="outward",
        reason="Damaged in transit",
        status=status,
        taxable_amount=Decimal("200.00"),
        cgst_amount=Decimal("18.00"),
        sgst_amount=Decimal("18.00"),
        igst_amount=Decimal("0"),
        total_amount=Decimal("236.00"),
        created_at=datetime(2026, 6, 5),
        cancelled_at=datetime(2026, 6, 6) if status == "cancelled" else None,
        items=[item],
    )
    ledger = Buyer(name="Acme & Sons", address="9 Buyer Lane", gst=buyer_gst, phone_number="9")
    product = Product(id=5, name="Laptop", sku="LP-1")
    return note, [invoice], [product], ledger


def render(**kwargs):
    note, invoices, products, ledger = make_note(**kwargs)
    return _build_credit_note_html(note, invoices, products, None, ledger)


def test_cites_the_note_and_the_invoice_it_reverses():
    html = render()
    assert "Credit Note CN/26/0007" in html
    assert "INV-0042 (01 Jun 2026)" in html
    assert "Mofna Traders" in html
    # Party names are escaped, not injected.
    assert "Acme &amp; Sons" in html
    assert "Laptop" in html
    assert "8471" in html
    assert "Damaged in transit" in html
    assert "₹236.00" in html


def test_intrastate_note_splits_cgst_and_sgst():
    html = render()
    assert "CGST: ₹18.00" in html
    assert "SGST: ₹18.00" in html
    assert "IGST" not in html


def test_interstate_note_shows_igst():
    note, invoices, products, ledger = make_note(buyer_gst="24BBBBB0000B1ZZ")
    note.cgst_amount = note.sgst_amount = Decimal("0")
    note.igst_amount = Decimal("36.00")
    html = _build_credit_note_html(note, invoices, products, None, ledger)
    assert "IGST: ₹36.00" in html
    assert "CGST" not in html


def test_discount_note_names_the_line_as_a_discount():
    assert "Discount on Laptop" in render(credit_note_type="discount")


def test_cancelled_note_says_so():
    html = render(status="cancelled")
    assert "Cancelled on 06 Jun 2026" in html
    assert "Cancelled on" not in render()
