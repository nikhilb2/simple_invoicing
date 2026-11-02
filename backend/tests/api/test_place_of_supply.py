"""Place of supply on a sale, and the date on a credit note, through the API."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.core.validation import is_valid_gstin_checksum
from src.models.company import CompanyProfile
from src.services.gst_tax_service import india_today
from src.services.pdf_templates.invoice_template import _build_invoice_html
from tests.api.test_product_performance import _create_ledger, _create_product, _line

HOME = "29AAAAA0000A1Z5"
MAHARASHTRA_BUYER = "27AAPFU0939F1ZV"


@pytest.fixture
def seller(client, db_session):
    """A Karnataka seller, set directly because the check digit is not under test."""
    assert client.get("/api/company/").status_code == 200
    company = db_session.query(CompanyProfile).first()
    company.gst = HOME
    db_session.commit()
    return company


def _ledger_with_gst(client, name, gst):
    response = client.post(
        "/api/ledgers/",
        json={"name": name, "address": "1 Market St", "phone_number": "1234567890", "gst": gst},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _invoice_payload(ledger_id, product_id, **extra):
    return {
        "voucher_type": "sales",
        "ledger_id": ledger_id,
        "invoice_date": (india_today() - timedelta(days=5)).isoformat(),
        "items": [_line(product_id, 1, 1000)],
        **extra,
    }


def _post_invoice(client, *args, **extra):
    response = client.post("/api/invoices/", json=_invoice_payload(*args, **extra))
    assert response.status_code == 200, response.text
    return response.json()


def _note_payload(invoices, **extra):
    return {
        "ledger_id": invoices[0]["ledger_id"],
        "invoice_ids": [inv["id"] for inv in invoices],
        "credit_note_type": "return",
        "direction": "outward",
        "items": [
            {"invoice_id": inv["id"], "invoice_item_id": inv["items"][0]["id"], "quantity": 1}
            for inv in invoices
        ],
        **extra,
    }


def test_interstate_sale_to_an_unregistered_buyer_charges_igst(client, seller):
    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"), place_of_supply="10")

    assert invoice["place_of_supply"] == "10"
    assert (invoice["igst_amount"], invoice["cgst_amount"], invoice["sgst_amount"]) == (180, 0, 0)
    assert invoice["items"][0]["igst_amount"] == 180


def test_unregistered_buyer_defaults_to_the_sellers_state(client, seller):
    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"))

    assert invoice["place_of_supply"] == "29"
    assert (invoice["igst_amount"], invoice["cgst_amount"], invoice["sgst_amount"]) == (0, 90, 90)


def test_registered_buyer_defaults_to_the_state_on_their_gstin(client, seller):
    ledger = _ledger_with_gst(client, "Buyer", MAHARASHTRA_BUYER)
    invoice = _post_invoice(client, ledger, _create_product(client, "S-1", "Widget"))

    assert invoice["place_of_supply"] == "27"
    assert invoice["igst_amount"] == 180


def test_registered_buyer_can_take_delivery_in_the_sellers_state(client, seller):
    ledger = _ledger_with_gst(client, "Buyer", MAHARASHTRA_BUYER)
    invoice = _post_invoice(client, ledger, _create_product(client, "S-1", "Widget"), place_of_supply="29")

    assert invoice["place_of_supply"] == "29"
    assert (invoice["igst_amount"], invoice["cgst_amount"]) == (0, 90)


@pytest.mark.parametrize("code", ["00", "39", "99", "AB", "1", "027"])
def test_place_of_supply_must_be_a_state_code(client, seller, code):
    response = client.post(
        "/api/invoices/",
        json=_invoice_payload(_create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"), place_of_supply=code),
    )
    assert response.status_code == 422


def test_edit_that_omits_place_of_supply_keeps_it(client, seller):
    ledger, product = _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget")
    invoice = _post_invoice(client, ledger, product, place_of_supply="10")

    response = client.put(f"/api/invoices/{invoice['id']}", json=_invoice_payload(ledger, product))

    assert response.status_code == 200, response.text
    assert response.json()["place_of_supply"] == "10"
    assert response.json()["igst_amount"] == 180


def test_edit_that_changes_the_ledger_takes_the_new_buyers_state(client, seller):
    product = _create_product(client, "S-1", "Widget")
    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), product, place_of_supply="10")

    other = _ledger_with_gst(client, "Buyer", MAHARASHTRA_BUYER)
    response = client.put(f"/api/invoices/{invoice['id']}", json=_invoice_payload(other, product))

    assert response.status_code == 200, response.text
    assert response.json()["place_of_supply"] == "27"


def test_purchase_ignores_place_of_supply(client, seller):
    ledger = _ledger_with_gst(client, "Supplier", MAHARASHTRA_BUYER)
    payload = _invoice_payload(ledger, _create_product(client, "S-1", "Widget"), place_of_supply="29", voucher_type="purchase")
    response = client.post("/api/invoices/", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["place_of_supply"] is None
    assert response.json()["igst_amount"] == 180


def test_invoice_pdf_uses_igst_columns_and_prints_the_place_of_supply(client, seller, db_session):
    from src.models.invoice import Invoice

    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"), place_of_supply="10")
    row = db_session.query(Invoice).filter(Invoice.id == invoice["id"]).first()

    html = _build_invoice_html(row, [SimpleNamespace(id=row.items[0].product_id, name="Widget", sku="S-1", hsn_sac=None)])

    assert "Place of supply: Bihar (10)" in html
    assert "IGST" in html


def test_credit_note_reverses_the_igst_its_invoice_charged(client, seller):
    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"), place_of_supply="10")

    response = client.post("/api/credit-notes/", json=_note_payload([invoice]))

    assert response.status_code == 201, response.text
    assert (response.json()["igst_amount"], response.json()["cgst_amount"]) == (180, 0)


def test_credit_note_cannot_span_two_places_of_supply(client, seller):
    ledger, product = _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget")
    bihar = _post_invoice(client, ledger, product, place_of_supply="10")
    home = _post_invoice(client, ledger, product)

    response = client.post("/api/credit-notes/", json=_note_payload([bihar, home]))

    assert response.status_code == 400
    assert "different places of supply" in response.json()["detail"]


def test_credit_note_defaults_to_today_in_india(client, seller):
    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"))

    response = client.post("/api/credit-notes/", json=_note_payload([invoice]))

    assert response.json()["credit_note_date"].startswith(india_today().isoformat())


def test_credit_note_can_carry_an_earlier_date(client, seller):
    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"))
    chosen = india_today() - timedelta(days=2)

    response = client.post("/api/credit-notes/", json=_note_payload([invoice], credit_note_date=chosen.isoformat()))

    assert response.status_code == 201, response.text
    assert response.json()["credit_note_date"].startswith(chosen.isoformat())

    listed = client.get("/api/credit-notes/", params={"date_from": chosen.isoformat(), "date_to": chosen.isoformat()})
    assert listed.json()["total"] == 1


def test_credit_note_date_cannot_be_in_the_future(client, seller):
    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"))

    response = client.post(
        "/api/credit-notes/",
        json=_note_payload([invoice], credit_note_date=(india_today() + timedelta(days=1)).isoformat()),
    )

    assert response.status_code == 400
    assert "future" in response.json()["detail"]


def test_credit_note_date_cannot_be_before_its_invoice(client, seller):
    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"))

    response = client.post(
        "/api/credit-notes/",
        json=_note_payload([invoice], credit_note_date=(india_today() - timedelta(days=30)).isoformat()),
    )

    assert response.status_code == 400
    assert "before the date of invoice" in response.json()["detail"]


def test_duplicate_keeps_the_place_of_supply_its_tax_was_charged_for(client, seller, db_session):
    from src.models.invoice import Invoice

    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"), place_of_supply="10")

    response = client.post(f"/api/invoices/{invoice['id']}/duplicate")

    assert response.status_code in (200, 201), response.text
    copy = db_session.query(Invoice).filter(Invoice.id != invoice["id"]).one()
    assert copy.place_of_supply == "10"
    assert float(copy.igst_amount) == 180


def test_buyer_gstin_starting_99_has_no_default_state_and_keeps_its_old_tax(client, seller):
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    gstin = next(g for g in (f"99AAAAA0000A1Z{c}" for c in alphabet) if is_valid_gstin_checksum(g))

    invoice = _post_invoice(client, _ledger_with_gst(client, "UN Body", gstin), _create_product(client, "S-1", "Widget"))

    assert invoice["place_of_supply"] is None
    assert invoice["igst_amount"] == 180


def test_seller_with_no_gstin_stores_no_place_of_supply(client, seller, db_session):
    seller.gst = None
    db_session.commit()

    invoice = _post_invoice(client, _create_ledger(client, "Walk-in"), _create_product(client, "S-1", "Widget"), place_of_supply="10")

    assert invoice["place_of_supply"] is None
    assert invoice["igst_amount"] == 0


def test_credit_note_follows_the_invoice_when_the_ledger_gains_a_gstin_later(client, seller, db_session):
    from src.models.buyer import Buyer

    ledger = _create_ledger(client, "Walk-in")
    invoice = _post_invoice(client, ledger, _create_product(client, "S-1", "Widget"))
    db_session.get(Buyer, ledger).gst = MAHARASHTRA_BUYER
    db_session.commit()

    response = client.post("/api/credit-notes/", json=_note_payload([invoice]))

    assert (response.json()["cgst_amount"], response.json()["igst_amount"]) == (90, 0)


def test_credit_note_cannot_span_b2cl_and_b2cs(client, seller):
    ledger = _create_ledger(client, "Walk-in")
    cheap = _create_product(client, "S-1", "Widget")
    costly = _create_product(client, "S-2", "Machine", price=200000)
    small = _post_invoice(client, ledger, cheap, place_of_supply="10")
    large_payload = _invoice_payload(ledger, costly, place_of_supply="10")
    large_payload["items"] = [_line(costly, 1, 200000)]
    large = client.post("/api/invoices/", json=large_payload).json()

    response = client.post("/api/credit-notes/", json=_note_payload([small, large]))

    assert response.status_code == 400
    assert "different GSTR-1 tables" in response.json()["detail"]


def test_new_financial_year_label_is_held_to_the_number_rule(client, seller, db_session):
    from src.models.financial_year import FinancialYear
    from src.models.invoice_series import InvoiceSeries

    created = client.post("/api/financial-years/", json={"label": "2030-31", "start_date": "2030-04-01", "end_date": "2031-03-31"})
    assert created.status_code in (200, 201), created.text
    db_session.query(FinancialYear).update({FinancialYear.is_active: False})
    db_session.get(FinancialYear, created.json()["id"]).is_active = True
    for series in db_session.query(InvoiceSeries).filter(InvoiceSeries.financial_year_id == created.json()["id"]):
        series.year_format = "FY"
    db_session.commit()

    long_label = client.post(
        "/api/financial-years/",
        json={"label": "A VERY LONG LABEL 2031-32", "start_date": "2031-04-01", "end_date": "2032-03-31"},
    )
    assert long_label.status_code == 400
    assert "GSTR-1" in long_label.json()["detail"]

    short_label = client.post(
        "/api/financial-years/",
        json={"label": "2031-32", "start_date": "2031-04-01", "end_date": "2032-03-31"},
    )
    assert short_label.status_code in (200, 201), short_label.text
