"""Invoices stored with no due date, on Dues and the dashboard, on real Postgres.

The API, MCP, duplicating an invoice and marketplace posting can all store a NULL
due date. Those invoices count as due on their invoice date, on every Dues surface
and in the dashboard's overdue figures. The stored value stays NULL.

The dues query filters and orders on COALESCE(due_date, invoice_date) in SQL, so
these run on Postgres rather than the suite's SQLite. Skipped when DATABASE_URL is
not Postgres.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.core.config import settings
from src.db.session import get_db
from src.models.user import User, UserRole

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import test_tenant_isolation as iso  # noqa: E402
from quotation_helpers import seed_financial_year  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="the dues query is checked on the database production runs",
)

EMAIL = "owner@dues.example"


@pytest.fixture
def client(clean_rls_db, monkeypatch):
    """A signed-in owner of one company with a year wide enough for back-dated invoices."""
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")

    def _get_db():
        db = clean_rls_db.OwnerSession()
        try:
            yield db
        finally:
            db.close()

    def _current_user(db: Session = Depends(get_db)) -> User:
        return db.query(User).filter(User.email == EMAIL).one()

    previous_db = app.dependency_overrides.get(get_db)
    previous_user = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _current_user
    try:
        with clean_rls_db.OwnerSession() as owner:
            iso._user(owner, EMAIL, role=UserRole.admin)
        test_client = TestClient(app)
        iso._create_company(test_client, "Dues Traders")
        seed_financial_year(test_client)
        yield test_client
    finally:
        app.dependency_overrides[get_db] = previous_db
        app.dependency_overrides[get_current_user] = previous_user


@pytest.fixture
def customer(client):
    return iso._create_ledger(client, "Dues Customer")


@pytest.fixture
def product(client):
    return iso._create_product(client, "DUES-1")


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _invoice(client, ledger, product, *, invoice_date, due_date=None, voucher_type="sales"):
    """Create an invoice. With no due_date the key is left out, as an API caller would."""
    payload = {
        "ledger_id": ledger,
        "voucher_type": voucher_type,
        "invoice_date": invoice_date,
        "items": [{"product_id": product, "quantity": 1, "unit_price": 100}],
    }
    if due_date is not None:
        payload["due_date"] = due_date
    return iso._ok(client.post("/api/invoices/", json=payload))


def _receipt(client, ledger, invoice, amount):
    return iso._ok(client.post("/api/payments/", json={
        "ledger_id": ledger,
        "voucher_type": "receipt",
        "amount": amount,
        "date": datetime.now().isoformat(),
        "mode": "bank",
        "invoice_allocations": [{"invoice_id": invoice["id"], "allocated_amount": amount}],
    }))


def _dues(client, **params):
    return iso._ok(client.get("/api/invoices/dues", params=params))


def _ageing(client, **params):
    return iso._ok(client.get("/api/invoices/dues/ageing", params=params))


def _buckets(ageing):
    return {bucket["key"]: bucket for bucket in ageing["buckets"]}


def _receivables(client):
    return iso._ok(client.get("/api/dashboard/metrics"))["receivables"]


def _stored_due_date(db, invoice_id):
    with db.owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT due_date FROM invoices WHERE id = :id"), {"id": invoice_id}
        ).scalar()


def test_appears_on_dues_and_ageing_while_the_stored_date_stays_null(
    client, clean_rls_db, customer, product
):
    invoice = _invoice(client, customer, product, invoice_date=_days_ago(0))
    assert invoice["due_date"] is None

    dues = _dues(client)
    assert [item["id"] for item in dues["items"]] == [invoice["id"]]
    assert dues["total"] == 1
    item = dues["items"][0]
    assert item["due_date"] == item["invoice_date"]
    assert item["due_date"].startswith(_days_ago(0))
    assert item["due_in_days"] == 0

    ageing = _ageing(client)
    assert ageing["total_invoice_count"] == 1
    assert ageing["total_remaining"] == invoice["total_amount"]

    # Only Dues shows the effective date: the row and the invoice itself are unchanged.
    assert _stored_due_date(clean_rls_db, invoice["id"]) is None
    fetched = iso._ok(client.get(f"/api/invoices/{invoice['id']}"))
    assert fetched["due_date"] is None
    assert fetched["due_in_days"] is None


@pytest.mark.parametrize("days_ago,bucket", [
    (0, "not_yet_due"),
    (1, "1_30"),
    (30, "1_30"),
    (31, "31_60"),
    (40, "31_60"),
    (70, "61_90"),
    (100, "over_90"),
])
def test_ages_by_the_invoice_date(client, customer, product, days_ago, bucket):
    invoice = _invoice(client, customer, product, invoice_date=_days_ago(days_ago))

    item = _dues(client)["items"][0]
    assert item["due_date"].startswith(_days_ago(days_ago))
    assert item["due_in_days"] == -days_ago

    buckets = _buckets(_ageing(client))
    assert buckets[bucket]["invoice_count"] == 1
    assert buckets[bucket]["total_remaining"] == invoice["total_amount"]
    assert sum(entry["invoice_count"] for entry in buckets.values()) == 1


def test_a_part_payment_leaves_the_remainder_on_dues(client, customer, product):
    invoice = _invoice(client, customer, product, invoice_date=_days_ago(40))
    _receipt(client, customer, invoice, 50)

    remaining = invoice["total_amount"] - 50
    assert _dues(client)["items"][0]["outstanding_amount"] == remaining
    assert _buckets(_ageing(client))["31_60"]["total_remaining"] == remaining
    assert _receivables(client)["overdue_amount"] == remaining


@pytest.mark.parametrize("window,listed", [
    ({"due_date_from": _days_ago(11), "due_date_to": _days_ago(9)}, True),
    ({"due_date_from": _days_ago(10), "due_date_to": _days_ago(10)}, True),
    ({"due_date_from": _days_ago(10)}, True),
    ({"due_date_to": _days_ago(10)}, True),
    ({"due_date_from": _days_ago(9)}, False),
    ({"due_date_to": _days_ago(11)}, False),
])
def test_due_date_filters_use_the_invoice_date(client, customer, product, window, listed):
    invoice = _invoice(client, customer, product, invoice_date=_days_ago(10))

    assert [item["id"] for item in _dues(client, **window)["items"]] == ([invoice["id"]] if listed else [])
    assert _ageing(client, **window)["total_invoice_count"] == (1 if listed else 0)


def test_dashboard_overdue_counts_a_backdated_invoice_and_agrees_with_ageing(client, customer, product):
    backdated = _invoice(client, customer, product, invoice_date=_days_ago(40))
    today = _invoice(client, customer, product, invoice_date=_days_ago(0))

    receivables = _receivables(client)
    assert receivables["overdue_count"] == 1
    assert receivables["overdue_amount"] == backdated["total_amount"]
    assert receivables["outstanding_amount"] == backdated["total_amount"] + today["total_amount"]

    ageing = _ageing(client)
    overdue_tiles = [bucket for bucket in ageing["buckets"] if bucket["key"] != "not_yet_due"]
    assert sum(bucket["invoice_count"] for bucket in overdue_tiles) == receivables["overdue_count"]
    assert sum(bucket["total_remaining"] for bucket in overdue_tiles) == receivables["overdue_amount"]
    assert ageing["total_remaining"] == receivables["outstanding_amount"]


def test_cancelled_purchase_and_paid_invoices_stay_out(client, customer, product):
    cancelled = _invoice(client, customer, product, invoice_date=_days_ago(40))
    iso._ok(client.delete(f"/api/invoices/{cancelled['id']}"))

    # A separate supplier, so what is owed to them cannot offset the customer's dues.
    supplier = iso._create_ledger(client, "Dues Supplier")
    _invoice(client, supplier, product, invoice_date=_days_ago(40), voucher_type="purchase")

    paid = _invoice(client, customer, product, invoice_date=_days_ago(40))
    _receipt(client, customer, paid, paid["total_amount"])

    assert _dues(client)["items"] == []
    ageing = _ageing(client)
    assert ageing["total_invoice_count"] == 0
    assert ageing["total_remaining"] == 0
    receivables = _receivables(client)
    assert receivables["overdue_count"] == 0
    assert receivables["overdue_amount"] == 0


def test_a_duplicated_invoice_appears_on_dues(client, customer, product):
    original = _invoice(
        client, customer, product, invoice_date=_days_ago(5), due_date=_days_ago(0)
    )
    copy_id = iso._ok(client.post(f"/api/invoices/{original['id']}/duplicate"))["id"]
    copy = iso._ok(client.get(f"/api/invoices/{copy_id}"))
    assert copy["due_date"] is None

    items = {item["id"]: item for item in _dues(client)["items"]}
    assert set(items) == {original["id"], copy_id}
    assert items[copy_id]["due_date"] == copy["invoice_date"]


def test_real_due_dates_behave_as_before_and_mix_by_effective_date(client, customer, product):
    # The real due dates sit far from their invoice dates, to catch the wrong date being used.
    real_past = _invoice(client, customer, product, invoice_date=_days_ago(90), due_date=_days_ago(5))
    real_future = _invoice(
        client, customer, product, invoice_date=_days_ago(90),
        due_date=(date.today() + timedelta(days=5)).isoformat(),
    )
    no_date_old = _invoice(client, customer, product, invoice_date=_days_ago(10))
    no_date_today = _invoice(client, customer, product, invoice_date=_days_ago(0))
    expected = [no_date_old["id"], real_past["id"], no_date_today["id"], real_future["id"]]

    assert [item["id"] for item in _dues(client)["items"]] == expected
    assert [item["id"] for item in _dues(client, sort="due-date-asc")["items"]] == expected

    items = {item["id"]: item for item in _dues(client)["items"]}
    assert items[real_past["id"]]["due_date"].startswith(_days_ago(5))
    assert items[real_past["id"]]["due_in_days"] == -5
    assert items[real_future["id"]]["due_in_days"] == 5

    buckets = _buckets(_ageing(client))
    assert buckets["not_yet_due"]["invoice_count"] == 2
    assert buckets["1_30"]["invoice_count"] == 2
    assert buckets["61_90"]["invoice_count"] == 0

    # Filtering on the real due date, not the invoice date inside the same window.
    only_old_invoice_date = {"due_date_from": _days_ago(91), "due_date_to": _days_ago(89)}
    assert _dues(client, **only_old_invoice_date)["items"] == []
    receivables = _receivables(client)
    assert receivables["overdue_count"] == 2
