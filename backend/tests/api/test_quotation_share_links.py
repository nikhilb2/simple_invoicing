"""Sharing a quotation by public link: the same document, the same note, no way to pay."""

from datetime import date, timedelta

import pytest
from quotation_helpers import (
    convert,
    create_ledger,
    create_product,
    create_quotation,
    ok,
    seed_company,
)

from src.api.routes.public_share import reset_rate_limits
from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.company_account import CompanyAccount


@pytest.fixture(autouse=True)
def _clean_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture(autouse=True)
def _share_on(monkeypatch):
    monkeypatch.setattr(settings, "SHARE_LINKS_ENABLED", True)


@pytest.fixture
def setup(client):
    seed_company(client)
    return client, create_ledger(client), create_product(client)


def _link(client, quote) -> dict:
    return ok(client.post("/api/share/", json={"resource_type": "quotation", "resource_id": quote["id"]}))


@pytest.mark.parametrize("document_type, title", [("quotation", "Quotation"), ("proforma", "Proforma Invoice")])
def test_page_names_the_document_and_carries_the_note(setup, document_type, title):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], document_type=document_type)
    token = _link(client, quote)["token"]

    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    assert f"{title} {quote['quotation_number']}" in page.text
    assert "This is not a tax invoice and cannot be used to claim input tax credit." in page.text
    assert "Quoted to" in page.text and "Quoted total" in page.text
    assert "Billed to" not in page.text


def test_pdf_and_document_routes_serve_the_quotation_template(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], document_type="proforma")
    token = _link(client, quote)["token"]

    pdf = client.get(f"/s/{token}/pdf?download=1")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert f"proforma_{quote['quotation_number']}.pdf" in pdf.headers["content-disposition"]

    document = client.get(f"/s/{token}/document.html")
    assert document.status_code == 200
    assert "Proforma Invoice" in document.text
    assert "This is not a tax invoice" in document.text
    assert "Tax Invoice" not in document.text


def test_no_upi_offer_even_when_the_company_has_one(setup, db_session):
    client, ledger, product = setup
    company = db_session.query(CompanyProfile).first()
    company.show_upi_pay_button = True
    company.show_pay_qr_on_invoice = True
    db_session.add(CompanyAccount(
        company_id=company.id,
        account_type="bank",
        display_name="Main",
        bank_name="State Bank",
        account_number="1234567890",
        ifsc_code="SBIN0001234",
        upi_vpa="acme@upi",
        is_active=True,
        created_by=1,
    ))
    db_session.commit()

    for document_type in ("quotation", "proforma"):
        quote = create_quotation(client, ledger["id"], product["id"], document_type=document_type)
        token = _link(client, quote)["token"]
        page = client.get(f"/s/{token}").text
        assert "acme@upi" not in page
        assert "upi://" not in page
        assert 'id="pay"' not in page
        document = client.get(f"/s/{token}/document.html").text
        assert "pay-qr__img" not in document
        assert "Scan to view" not in document


def test_cancelled_quotation_is_the_standard_dead_link(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    token = _link(client, quote)["token"]
    ok(client.post(f"/api/quotations/{quote['id']}/cancel"))

    page = client.get(f"/s/{token}")
    assert page.status_code == 404
    assert quote["quotation_number"] not in page.text
    assert client.get(f"/s/{token}/pdf").status_code == 404
    assert client.get(f"/s/{token}/document.html").status_code == 404


def test_cancelled_quotation_cannot_get_a_new_link(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(client.post(f"/api/quotations/{quote['id']}/cancel"))
    response = client.post("/api/share/", json={"resource_type": "quotation", "resource_id": quote["id"]})
    assert response.status_code == 404


def test_unknown_quotation_cannot_get_a_link(setup):
    client, _, _ = setup
    response = client.post("/api/share/", json={"resource_type": "quotation", "resource_id": 999})
    assert response.status_code == 404


def test_a_quotation_id_is_not_an_invoice_id(setup):
    """Same integer, different table: a link names its resource type, not just an id."""
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice_response = client.post("/api/share/", json={"resource_type": "invoice", "resource_id": quote["id"]})
    assert invoice_response.status_code == 404


def test_link_is_idempotent_and_counts_views(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    first = _link(client, quote)
    assert _link(client, quote)["token"] == first["token"]
    client.get(f"/s/{first['token']}")
    (listed,) = ok(client.get("/api/share/", params={"resource_type": "quotation", "resource_id": quote["id"]}))
    assert listed["view_count"] == 1


def test_page_says_valid_until_then_expired(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], valid_until=(date.today() + timedelta(days=3)).isoformat())
    token = _link(client, quote)["token"]
    assert f"Valid until {(date.today() + timedelta(days=3)):%d %b %Y}." in client.get(f"/s/{token}").text

    past = date.today() - timedelta(days=40)
    old = create_quotation(
        client, ledger["id"], product["id"],
        quotation_date=past.isoformat(),
        valid_until=(past + timedelta(days=30)).isoformat(),
    )
    token = _link(client, old)["token"]
    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    assert f"This quotation expired on {(past + timedelta(days=30)):%d %b %Y}." in page.text


def test_declined_is_not_shown_as_a_live_offer(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], valid_until=(date.today() + timedelta(days=3)).isoformat())
    token = _link(client, quote)["token"]
    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "declined"}))
    page = client.get(f"/s/{token}").text
    assert "This quotation was declined." in page
    assert "Valid until" not in page


def test_page_says_when_it_became_an_invoice(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    token = _link(client, quote)["token"]
    ok(convert(client, quote["id"]))
    assert "has been converted to an invoice" in client.get(f"/s/{token}").text
