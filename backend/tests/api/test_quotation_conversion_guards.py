"""What keeps a conversion honest: the date it carries, the version of the quote it was
drawn from, and what happens to a cancelled invoice once its quote has moved on."""

from datetime import date, datetime, timedelta, timezone

import pytest
from quotation_helpers import (
    GST_KA,
    convert,
    create_ledger,
    create_product,
    create_quotation,
    ok,
    seed_company,
)

from src.models.invoice import Invoice
from src.services import gst_tax_service
from src.services import quotation as quotation_service


@pytest.fixture
def setup(client):
    seed_company(client)
    return client, create_ledger(client), create_product(client)


def _stock(client, product_id: int) -> float:
    rows = ok(client.get("/api/inventory/", params={"page_size": 500}))["items"]
    return next(row["quantity"] for row in rows if row["product_id"] == product_id)


def _draft(client, quote) -> dict:
    return ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]


def _warning_codes(client, quote) -> set[str]:
    warnings = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["warnings"]
    return {warning["code"] for warning in warnings}


def _edit(client, quote, ledger_id: int, product_id: int, quantity=9) -> dict:
    return ok(client.put(
        f"/api/quotations/{quote['id']}",
        json={"ledger_id": ledger_id, "items": [{"product_id": product_id, "quantity": quantity, "unit_price": 100}]},
    ))


# ---------------------------------------------------------------------------
# Restoring an invoice after its quotation was edited
# ---------------------------------------------------------------------------

def _reopened_and_edited(client, ledger, product):
    """Convert, cancel the invoice so the quote reopens, then change the quote."""
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    other = create_ledger(client, "Customer Two", gst=GST_KA)
    return _edit(client, quote, other["id"], product["id"]), invoice


def test_restoring_after_the_quote_was_edited_leaves_the_quote_alone(setup):
    client, ledger, product = setup
    quote, invoice = _reopened_and_edited(client, ledger, product)

    restored = ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert restored["status"] == "active"
    assert restored["source_quotation_number"] is None
    assert restored["ledger_id"] == ledger["id"]
    assert _stock(client, product["id"]) == 98

    after = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert after["status"] == "open"
    assert after["ledger_name"] == "Customer Two"
    assert after["total_amount"] == quote["total_amount"]
    assert after["converted_invoice_id"] is None
    assert after["invoices"] == []


def test_an_edited_quote_can_be_converted_while_its_old_invoice_is_live(setup):
    client, ledger, product = setup
    quote, old = _reopened_and_edited(client, ledger, product)
    ok(client.post(f"/api/invoices/{old['id']}/restore"))

    new = ok(convert(client, quote["id"]))
    assert new["id"] != old["id"]
    after = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert after["status"] == "converted"
    assert [row["id"] for row in after["invoices"]] == [new["id"]]


def test_editing_a_quote_unlinks_only_its_own_cancelled_invoices(setup, db_session):
    client, ledger, product = setup
    edited, invoice = _reopened_and_edited(client, ledger, product)
    assert db_session.query(Invoice).filter(Invoice.id == invoice["id"]).one().source_quotation_id is None

    other_quote = create_quotation(client, ledger["id"], product["id"])
    other_invoice = ok(convert(client, other_quote["id"]))
    ok(client.delete(f"/api/invoices/{other_invoice['id']}"))
    _edit(client, edited, ledger["id"], product["id"], quantity=1)

    db_session.expire_all()
    still_linked = db_session.query(Invoice).filter(Invoice.id == other_invoice["id"]).one()
    assert still_linked.source_quotation_id == other_quote["id"]


@pytest.mark.parametrize("moves", [["accepted"], ["declined"], ["accepted", "open"]])
def test_answering_the_quote_is_not_an_edit_so_a_restore_still_closes_it(setup, moves):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    for status in moves:
        ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": status}))

    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    after = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert after["status"] == "converted"
    assert after["converted_invoice_id"] == invoice["id"]


# ---------------------------------------------------------------------------
# Converting from a draft that has gone stale
# ---------------------------------------------------------------------------

def test_the_draft_says_which_version_of_the_quote_it_was_built_from(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    assert _draft(client, quote)["quotation_updated_at"] == quote["updated_at"]


def test_a_stale_draft_cannot_close_an_edited_quote(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    stale = _draft(client, quote)
    edited = _edit(client, quote, ledger["id"], product["id"], quantity=25)

    response = client.post(f"/api/quotations/{quote['id']}/convert", json=stale)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "quotation_changed"
    assert quote["quotation_number"] in detail["message"]
    after = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert after["status"] == "open"
    assert after["invoices"] == []
    assert _stock(client, product["id"]) == 100

    # A fresh draft carries the new figures and goes through.
    invoice = ok(convert(client, quote["id"]))
    assert invoice["total_amount"] == edited["total_amount"]


def test_a_draft_from_before_a_status_change_is_stale_too(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    stale = _draft(client, quote)
    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "accepted"}))
    response = client.post(f"/api/quotations/{quote['id']}/convert", json=stale)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "quotation_changed"


def test_changing_the_invoice_in_the_composer_is_not_staleness(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    payload = _draft(client, quote)
    payload["items"][0]["unit_price"] = 90
    invoice = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=payload))
    assert invoice["items"][0]["unit_price"] == 90


def test_a_caller_who_leaves_the_version_out_is_not_checked(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    payload = _draft(client, quote)
    del payload["quotation_updated_at"]
    _edit(client, quote, ledger["id"], product["id"], quantity=3)
    ok(client.post(f"/api/quotations/{quote['id']}/convert", json=payload))


@pytest.mark.parametrize("suffix", ["Z", "+00:00"])
def test_the_version_can_be_sent_with_a_utc_marker(setup, suffix):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    payload = _draft(client, quote)
    payload["quotation_updated_at"] += suffix
    ok(client.post(f"/api/quotations/{quote['id']}/convert", json=payload))


def test_a_version_in_another_timezone_is_compared_as_the_same_instant(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    payload = _draft(client, quote)
    seen = datetime.fromisoformat(payload["quotation_updated_at"])
    payload["quotation_updated_at"] = (seen + timedelta(hours=5, minutes=30)).isoformat() + "+05:30"
    ok(client.post(f"/api/quotations/{quote['id']}/convert", json=payload))


def test_a_second_conversion_with_an_old_draft_still_names_the_invoice(setup):
    """"Already converted" says more than "changed", so it is checked first."""
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    stale = _draft(client, quote)
    invoice = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=stale))

    response = client.post(f"/api/quotations/{quote['id']}/convert", json=stale)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "quotation_already_converted"
    assert response.json()["detail"]["invoice_id"] == invoice["id"]


# ---------------------------------------------------------------------------
# The date in India, not on the server
# ---------------------------------------------------------------------------

def test_india_today_turns_over_at_midnight_in_india(monkeypatch):
    moment = {"utc": datetime(2027, 3, 31, 18, 29, tzinfo=timezone.utc)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment["utc"].astimezone(tz)

    monkeypatch.setattr(gst_tax_service, "datetime", Frozen)
    assert gst_tax_service.india_today() == date(2027, 3, 31)
    moment["utc"] = datetime(2027, 3, 31, 18, 30, tzinfo=timezone.utc)
    assert gst_tax_service.india_today() == date(2027, 4, 1)


@pytest.fixture
def india_is_a_day_ahead(monkeypatch):
    """Just after midnight in India, on a server still on yesterday's date."""
    ahead = date.today() + timedelta(days=1)
    monkeypatch.setattr(quotation_service, "india_today", lambda: ahead)
    return ahead


def test_a_default_quotation_date_is_the_date_in_india(setup, india_is_a_day_ahead):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    assert quote["quotation_date"] == india_is_a_day_ahead.isoformat()
    assert quote["valid_until"] == (india_is_a_day_ahead + timedelta(days=30)).isoformat()


def test_a_duplicate_is_dated_in_india(setup, india_is_a_day_ahead):
    client, ledger, product = setup
    span = timedelta(days=10)
    original = create_quotation(
        client,
        ledger["id"],
        product["id"],
        quotation_date=(india_is_a_day_ahead - timedelta(days=5)).isoformat(),
        valid_until=(india_is_a_day_ahead - timedelta(days=5) + span).isoformat(),
    )
    copy = ok(client.post(f"/api/quotations/{original['id']}/duplicate"))
    assert copy["quotation_date"] == india_is_a_day_ahead.isoformat()
    assert copy["valid_until"] == (india_is_a_day_ahead + span).isoformat()


def test_a_conversion_draft_is_dated_in_india(setup, india_is_a_day_ahead):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    assert _draft(client, quote)["invoice_date"] == india_is_a_day_ahead.isoformat()


def test_an_invoice_date_sent_with_the_conversion_is_the_one_used(setup):
    """What the composer does: it sends the browser's date, as for any other invoice."""
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    chosen = (date.today() + timedelta(days=2)).isoformat()
    invoice = ok(convert(client, quote["id"], invoice_date=chosen))
    assert invoice["invoice_date"].startswith(chosen)
