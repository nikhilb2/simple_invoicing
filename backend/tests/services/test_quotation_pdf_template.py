"""What a quotation and a proforma invoice print, and what they must never print.

The wording is the compliance position: a buyer holding one of these must not be able
to mistake it for a tax invoice. A CA should review the note before release.
"""

import re
from datetime import date, datetime

import pytest

from src.models.company_account import CompanyAccount
from src.models.product import Product
from src.models.quotation import Quotation, QuotationItem
from src.services.pdf_templates import _build_quotation_html
from src.services.pdf_templates.quotation_template import NOT_A_TAX_INVOICE_NOTE

TODAY = date(2026, 6, 15)

# Each of these appears on, or is implied by, the invoice template.
BANNED = [
    "Tax Invoice",
    "Sales Invoice",
    "Bill of Supply",
    "Original",
    "Duplicate",
    "Triplicate",
    "ORIGINAL FOR",
    "Billed by",
    "Bill to",
    "Due",
    "Balance",
    "Paid",
    "Amount payable",
    "GST charged",
    "Tax collected",
    "UPI",
    "Pay online",
    "pay-qr",
    "Scan to",
    "Reverse charge",
    "IRN",
    "E-way",
]


def make_quotation(*, document_type="quotation", buyer_gst="27BBBBB0000B1ZT", status="open", valid_until=date(2026, 7, 15), **overrides):
    item = QuotationItem(
        product_id=5,
        hsn_sac="84713010",
        quantity=2,
        unit_price=100,
        gst_rate=18,
        taxable_amount=200,
        tax_amount=36,
        cgst_amount=18,
        sgst_amount=18,
        igst_amount=0,
        line_total=236,
    )
    fields = dict(
        id=1,
        document_type=document_type,
        quotation_number="PI-2026-007" if document_type == "proforma" else "QT-2026-007",
        status=status,
        quotation_date=date(2026, 6, 1),
        valid_until=valid_until,
        company_name="Mofna Traders",
        company_address="1 Market Road",
        company_gst="27AAAAA0000A1Z2",
        company_phone="9000000000",
        company_currency_code="INR",
        ledger_name="Acme & Sons",
        ledger_address="9 Buyer Lane",
        ledger_gst=buyer_gst,
        taxable_amount=200,
        total_tax_amount=36,
        cgst_amount=18,
        sgst_amount=18,
        igst_amount=0,
        total_amount=236,
        round_off_amount=0,
        apply_round_off=False,
        tax_inclusive=False,
        items=[item],
    )
    fields.update(overrides)
    return Quotation(**fields)


PRODUCT = Product(id=5, name="Widget", sku="WID-1", hsn_sac="84713010", price=100, gst_rate=18)
ACCOUNT = CompanyAccount(
    bank_name="State Bank",
    branch_name="Fort",
    account_name="Mofna Traders",
    account_number="1234567890",
    ifsc_code="SBIN0001234",
)


def render(quotation, accounts=None, **kwargs) -> str:
    return _build_quotation_html(quotation, [PRODUCT], accounts or [], today=TODAY, **kwargs)


def visible_text(html: str) -> str:
    """What the reader sees: the stylesheet's class names are not on the page."""
    return re.sub(r"<[^>]+>", " ", html.split("</head>")[1])


@pytest.mark.parametrize("document_type, title", [("quotation", "Quotation"), ("proforma", "Proforma Invoice")])
def test_title_and_fixed_note_print_on_both(document_type, title):
    html = render(make_quotation(document_type=document_type))
    # text-transform prints these in capitals; the source is the title-case form.
    assert f'<div class="sheet__title">{title}</div>' in html
    assert ".sheet__title {\n    text-align: center;" in html and "text-transform: uppercase" in html
    assert "This is not a tax invoice</div>" in html
    assert NOT_A_TAX_INVOICE_NOTE in html
    assert NOT_A_TAX_INVOICE_NOTE == (
        "This is not a tax invoice and cannot be used to claim input tax credit. "
        "GST shown is an estimate. A tax invoice will be issued at the time of supply."
    )


@pytest.mark.parametrize("document_type", ["quotation", "proforma"])
@pytest.mark.parametrize("buyer_gst", ["27BBBBB0000B1ZT", None])
@pytest.mark.parametrize("accounts", [[], [ACCOUNT]])
def test_never_prints_a_banned_word(document_type, buyer_gst, accounts):
    """With and without a GSTIN: the invoice template's title turns on exactly that."""
    text = visible_text(render(make_quotation(document_type=document_type, buyer_gst=buyer_gst), accounts))
    for word in BANNED:
        assert word not in text, word


def test_proforma_keeps_its_full_name_and_never_abbreviates():
    html = render(make_quotation(document_type="proforma"))
    # The number prefix may say PI; the heading never does.
    assert '<div class="sheet__title">Proforma Invoice</div>' in html
    assert "white-space: nowrap" in html
    assert "Proforma for" in html
    assert "Quotation for" not in html


def test_quotation_party_label():
    html = render(make_quotation())
    assert "Quotation for" in html
    assert "Proforma for" not in html
    assert ">From<" in html


def test_valid_until_prints_and_quotation_states_its_prices():
    quotation_html = render(make_quotation())
    assert "Valid until: 15 Jul 2026" in quotation_html
    assert "Prices are valid until 15 Jul 2026." in quotation_html

    proforma_html = render(make_quotation(document_type="proforma"))
    assert "Valid until: 15 Jul 2026" in proforma_html
    assert "Prices are valid" not in proforma_html


def test_blank_validity_prints_no_date():
    html = render(make_quotation(valid_until=None))
    assert "Valid until" not in html
    assert "Prices are valid" not in html
    assert "Expired" not in html


@pytest.mark.parametrize("document_type", ["quotation", "proforma"])
def test_expired_mark_is_derived_from_the_date(document_type):
    past = make_quotation(document_type=document_type, valid_until=date(2026, 6, 14))
    assert '<div class="sheet__mark">Expired on 14 Jun 2026</div>' in render(past)

    last_day = make_quotation(document_type=document_type, valid_until=TODAY)
    assert "sheet__mark\">" not in render(last_day)


def test_expired_quotation_speaks_in_the_past_tense():
    html = render(make_quotation(valid_until=date(2026, 6, 14)))
    assert "Prices were valid until 14 Jun 2026." in html


@pytest.mark.parametrize("status", ["declined", "converted", "cancelled"])
def test_only_a_live_document_shows_expired(status):
    html = render(make_quotation(status=status, valid_until=date(2026, 6, 14), cancelled_at=datetime(2026, 6, 10)))
    assert "Expired on" not in html


def test_cancelled_is_marked():
    html = render(make_quotation(status="cancelled", cancelled_at=datetime(2026, 6, 10)))
    assert '<div class="sheet__mark">Cancelled on 10 Jun 2026</div>' in html


def test_bank_details_on_proforma_only():
    proforma = render(make_quotation(document_type="proforma"), [ACCOUNT])
    assert "Bank details" in proforma
    assert "State Bank" in proforma
    assert "SBIN0001234" in proforma

    quotation = render(make_quotation(), [ACCOUNT])
    assert "Bank details" not in quotation
    assert "State Bank" not in quotation
    assert "1234567890" not in quotation


def test_quotation_never_prints_the_snapshot_bank_either():
    snapshot = {"company_bank_name": "Snapshot Bank", "company_account_number": "999"}
    assert "Snapshot Bank" not in render(make_quotation(**snapshot))
    # A proforma falls back to it when no account is marked to print.
    assert "Snapshot Bank" in render(make_quotation(document_type="proforma", **snapshot))


def test_proforma_with_no_bank_details_prints_no_section():
    html = render(make_quotation(document_type="proforma"))
    assert "Bank details" not in html
    # The invoice helper would have said this; a proforma has no account to apologise for.
    assert "No bank account marked" not in html


def test_gst_is_labelled_an_estimate():
    html = render(make_quotation())
    assert "Estimated tax" in html
    assert "Total estimated GST" in html
    assert "Quotation total" in html
    assert "Total due" not in html


def test_gst_split_follows_the_gstins():
    intra = render(make_quotation())
    assert "CGST" in intra and "SGST" in intra
    inter = render(make_quotation(
        buyer_gst="29BBBBB0000B1ZT", cgst_amount=0, sgst_amount=0, igst_amount=36,
    ))
    assert "IGST" in inter


def test_company_terms_print():
    html = render(make_quotation(company_terms_text="1. No return\n2. Goods once sold"))
    assert "1. No return" in html
    assert "2. Goods once sold" in html


def test_user_text_is_escaped():
    html = render(make_quotation(ledger_name="<script>alert(1)</script>", reference_notes="A & B"))
    assert "<script>alert(1)" not in html
    assert "A &amp; B" in html
    assert "Acme &amp; Sons" in render(make_quotation())


def test_hsn_never_wraps():
    # The fix from #661: an 8-digit code must not break across two lines.
    assert 'class="nowrap">84713010</td>' in render(make_quotation())


def test_show_sku_setting_is_respected():
    assert "WID-1" in render(make_quotation(), show_sku=True)
    assert "WID-1" not in render(make_quotation(), show_sku=False)


def test_shipping_address_prints_when_set():
    html = render(make_quotation(shipping_address="9 Dock Road", shipping_address_label="Warehouse"))
    assert "Ship to" in html and "9 Dock Road" in html and "Warehouse" in html


def test_renders_to_a_real_pdf():
    import weasyprint

    from src.services.pdf_render import safe_url_fetcher

    pdf = weasyprint.HTML(string=render(make_quotation()), url_fetcher=safe_url_fetcher).write_pdf()
    assert pdf.startswith(b"%PDF")
