"""What keeps a conversion honest: the date it carries, the version of the quote it was
drawn from, and what happens to a cancelled invoice once its quote has moved on."""

from datetime import date, datetime, timedelta, timezone

import pytest
from quotation_helpers import (
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
