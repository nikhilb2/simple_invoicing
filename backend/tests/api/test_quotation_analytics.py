"""Quotation events fire from the backend, after commit, with no names or GSTINs."""

from datetime import date, timedelta

import pytest
from quotation_helpers import convert, create_ledger, create_product, create_quotation, ok, seed_company

from src.core import analytics


class RecordingClient:
    def __init__(self):
        self.captured = []

    def capture(self, event=None, distinct_id=None, properties=None, **_):
        self.captured.append((event, distinct_id, properties or {}))

    def capture_exception(self, *args, **kwargs):
        pass

    def shutdown(self):
        pass


@pytest.fixture
def events(monkeypatch):
    recorder = RecordingClient()
    monkeypatch.setattr(analytics, "_client", recorder)
    monkeypatch.setattr(analytics, "_init_attempted", True)
    yield recorder
    analytics.bind_request(None, "api")


@pytest.fixture
def setup(client):
    seed_company(client)
    return client, create_ledger(client), create_product(client)


def _find(events, name):
    return [props for event, _, props in events.captured if event == name]


def test_created(setup, events):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], document_type="proforma")
    (props,) = _find(events, "quotation_created")
    assert props["quotation_id"] == quote["id"]
    assert props["document_type"] == "proforma"
    assert props["line_item_count"] == 1
    assert props["total_amount"] == 236
    assert props["has_valid_until"] is True
    assert props["validity_days"] == 30


def test_updated_status_cancelled_and_pdf(setup, events):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(client.put(f"/api/quotations/{quote['id']}", json={
        "ledger_id": ledger["id"],
        "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 100}],
    }))
    (updated,) = _find(events, "quotation_updated")
    assert updated["quotation_id"] == quote["id"] and updated["total_amount"] == 118

    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "accepted"}))
    (status,) = _find(events, "quotation_status_changed")
    assert status["from_status"] == "open" and status["to_status"] == "accepted"

    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "open"}))
    ok(client.post(f"/api/quotations/{quote['id']}/cancel"))
    (cancelled,) = _find(events, "quotation_cancelled")
    assert cancelled == {
        **cancelled,
        "quotation_id": quote["id"],
        "document_type": "quotation",
    }

    assert client.get(f"/api/quotations/{quote['id']}/pdf").status_code == 200
    (pdf,) = _find(events, "quotation_pdf_downloaded")
    assert pdf["quotation_id"] == quote["id"]


def test_converted_fires_both_events(setup, events):
    client, ledger, product = setup
    past = date.today() - timedelta(days=40)
    quote = create_quotation(
        client, ledger["id"], product["id"],
        quotation_date=past.isoformat(),
        valid_until=(past + timedelta(days=30)).isoformat(),
    )
    invoice = ok(convert(client, quote["id"]))

    (created,) = _find(events, "invoice_created")
    assert created["source"] == "quotation"
    assert created["invoice_id"] == invoice["id"]

    (converted,) = _find(events, "quotation_converted")
    assert converted["quotation_id"] == quote["id"]
    assert converted["invoice_id"] == invoice["id"]
    assert converted["document_type"] == "quotation"
    assert converted["days_since_quote"] == 40
    assert converted["was_expired"] is True
    assert converted["total_changed"] is False
    assert converted["rate_changed"] is False


def test_converted_notices_a_rate_change(setup, events):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(client.put(f"/api/products/{product['id']}", json={**product, "gst_rate": 5}))
    ok(convert(client, quote["id"]))
    (converted,) = _find(events, "quotation_converted")
    assert converted["rate_changed"] is True
    assert converted["total_changed"] is True
    assert converted["was_expired"] is False


def test_an_ordinary_invoice_has_no_source(setup, events):
    client, ledger, product = setup
    ok(client.post("/api/invoices/", json={
        "ledger_id": ledger["id"],
        "voucher_type": "sales",
        "items": [{"product_id": product["id"], "quantity": 1}],
    }))
    (created,) = _find(events, "invoice_created")
    assert "source" not in created


def test_a_failed_conversion_reports_nothing(setup, events):
    client, ledger, _ = setup
    scarce = create_product(client, "SCARCE-1", initial_quantity=0)
    quote = create_quotation(client, ledger["id"], scarce["id"])
    assert convert(client, quote["id"]).status_code == 400
    assert _find(events, "quotation_converted") == []
    assert _find(events, "invoice_created") == []


def test_no_party_details_in_any_event(setup, events):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], reference_notes="SECRET-REF")
    ok(convert(client, quote["id"]))
    for event, _, props in events.captured:
        if event.startswith("quotation_"):
            text = repr(props)
            assert ledger["name"] not in text, event
            assert ledger["gst"] not in text, event
            assert "SECRET-REF" not in text, event
