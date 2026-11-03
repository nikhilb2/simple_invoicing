"""Cancelling and restoring an invoice under real row locks, on real Postgres.

The routes read the invoice, then wait for a lock. Whoever waited must act on what is
true after the wait, not on the "active" it read before it. SQLite ignores FOR UPDATE
and serialises writers, so none of this can show on the suite's normal database.

Every test holds a row with a separate connection so that the requests pile up behind
it, whatever order the threads run in. Skipped when DATABASE_URL is not Postgres.
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app_main import app
from src.core.config import settings
# Fixtures, imported by name so pytest finds them here too.
from test_quotation_convert_postgres import (  # noqa: F401
    _create_quote,
    _invoices_for,
    _seed_company,
    _status_of,
    _stock,
    app_db,
    deployment,
    signed_in,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import test_tenant_isolation as iso  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="row locks need Postgres",
)


def _quoted_invoice(client, tenant: dict) -> tuple[dict, dict]:
    quote = _create_quote(client, tenant)
    draft = iso._ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    return quote, iso._ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft))


def _pile_up_behind_a_lock(db, lock_sql: str, row_id: int, requests: list, *, while_held=None) -> list:
    """Hold a row, start every request, let them all reach the lock, then let go."""
    owner = db.owner_engine.connect()
    holding = owner.begin()
    owner.execute(text(lock_sql), {"id": row_id})
    try:
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(request) for request in requests]
            time.sleep(1)
            assert not any(future.done() for future in futures), "a request went straight past a held row lock"
            if while_held is not None:
                while_held(owner)
            holding.commit()
            return [future.result(timeout=30) for future in futures]
    finally:
        owner.close()


LOCK_QUOTATION = "SELECT id FROM quotations WHERE id = :id FOR UPDATE"
LOCK_INVOICE = "SELECT id FROM invoices WHERE id = :id FOR UPDATE"


def _call(method: str, url: str, **kwargs):
    return lambda: TestClient(app).request(method, url, **kwargs)


def test_two_cancels_of_a_converted_invoice_move_stock_once(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote, invoice = _quoted_invoice(client, tenant)
    stock_before = _stock(app_db, tenant["product"])

    url = f"/api/invoices/{invoice['id']}"
    responses = _pile_up_behind_a_lock(app_db, LOCK_QUOTATION, quote["id"], [_call("DELETE", url), _call("DELETE", url)])

    assert sorted(r.status_code for r in responses) == [200, 400], [r.text[:200] for r in responses]
    assert _stock(app_db, tenant["product"]) == stock_before + 2
    assert _invoices_for(app_db, quote["id"]) == ["cancelled"]
    assert _status_of(app_db, quote["id"]) == "open"


def test_two_restores_of_a_converted_invoice_move_stock_once(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote, invoice = _quoted_invoice(client, tenant)
    iso._ok(client.delete(f"/api/invoices/{invoice['id']}"))
    stock_before = _stock(app_db, tenant["product"])

    url = f"/api/invoices/{invoice['id']}/restore"
    responses = _pile_up_behind_a_lock(app_db, LOCK_QUOTATION, quote["id"], [_call("POST", url), _call("POST", url)])

    assert sorted(r.status_code for r in responses) == [200, 400], [r.text[:200] for r in responses]
    assert _stock(app_db, tenant["product"]) == stock_before - 2
    assert _invoices_for(app_db, quote["id"]) == ["active"]
    assert _status_of(app_db, quote["id"]) == "converted"


def test_two_cancels_of_an_ordinary_invoice_move_stock_once(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    invoice = iso._create_invoice(client, tenant["ledger"], tenant["product"])
    stock_before = _stock(app_db, tenant["product"])

    url = f"/api/invoices/{invoice['id']}"
    responses = _pile_up_behind_a_lock(app_db, LOCK_INVOICE, invoice["id"], [_call("DELETE", url), _call("DELETE", url)])

    assert sorted(r.status_code for r in responses) == [200, 400], [r.text[:200] for r in responses]
    assert _stock(app_db, tenant["product"]) == stock_before + 2


def test_two_restores_of_an_ordinary_invoice_move_stock_once(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    invoice = iso._create_invoice(client, tenant["ledger"], tenant["product"])
    iso._ok(client.delete(f"/api/invoices/{invoice['id']}"))
    stock_before = _stock(app_db, tenant["product"])

    url = f"/api/invoices/{invoice['id']}/restore"
    responses = _pile_up_behind_a_lock(app_db, LOCK_INVOICE, invoice["id"], [_call("POST", url), _call("POST", url)])

    assert sorted(r.status_code for r in responses) == [200, 400], [r.text[:200] for r in responses]
    assert _stock(app_db, tenant["product"]) == stock_before - 2


def test_a_cancelled_invoice_cannot_be_edited_by_a_request_that_waited(app_db, signed_in):
    """The edit read "active" before the cancel committed, then found it cancelled."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    invoice = iso._create_invoice(client, tenant["ledger"], tenant["product"])
    stock_before = _stock(app_db, tenant["product"])

    def cancel_while_holding(owner):
        owner.execute(text("UPDATE invoices SET status = 'cancelled' WHERE id = :id"), {"id": invoice["id"]})

    payload = iso._invoice_payload(tenant["ledger"], tenant["product"])
    payload["items"][0]["quantity"] = 5
    [edit] = _pile_up_behind_a_lock(
        app_db,
        LOCK_INVOICE,
        invoice["id"],
        [_call("PUT", f"/api/invoices/{invoice['id']}", json=payload)],
        while_held=cancel_while_holding,
    )

    assert edit.status_code == 400, edit.text[:300]
    assert _stock(app_db, tenant["product"]) == stock_before


@pytest.mark.parametrize("attempt", range(3))
def test_editing_and_cancelling_one_invoice_cannot_deadlock(app_db, signed_in, attempt):
    """Both take the invoice before the stock, so one simply waits for the other."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    stock_before = _stock(app_db, tenant["product"])
    invoice = iso._create_invoice(client, tenant["ledger"], tenant["product"])

    payload = iso._invoice_payload(tenant["ledger"], tenant["product"])
    payload["items"][0]["quantity"] = 3
    url = f"/api/invoices/{invoice['id']}"
    edit, cancel = _pile_up_behind_a_lock(
        app_db, LOCK_INVOICE, invoice["id"], [_call("PUT", url, json=payload), _call("DELETE", url)]
    )

    assert cancel.status_code == 200, cancel.text[:300]
    assert edit.status_code in (200, 400), edit.text[:300]
    # Cancelled either way, so the stock is back where it started.
    assert _stock(app_db, tenant["product"]) == stock_before


def test_editing_a_reopened_quote_unlinks_its_cancelled_invoice_under_rls(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote, invoice = _quoted_invoice(client, tenant)
    iso._ok(client.delete(f"/api/invoices/{invoice['id']}"))

    iso._ok(client.put(f"/api/quotations/{quote['id']}", json={
        "ledger_id": tenant["ledger"],
        "items": [{"product_id": tenant["product"], "quantity": 5, "unit_price": 100}],
    }))
    assert _invoices_for(app_db, quote["id"]) == []

    iso._ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _status_of(app_db, quote["id"]) == "open"


def test_a_restore_that_waited_through_an_edit_leaves_the_quote_alone(app_db, signed_in):
    """The edit unlinked the invoice while the restore was queued behind the lock."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote, invoice = _quoted_invoice(client, tenant)
    iso._ok(client.delete(f"/api/invoices/{invoice['id']}"))
    stock_before = _stock(app_db, tenant["product"])

    def unlink_while_holding(owner):
        owner.execute(text("UPDATE invoices SET source_quotation_id = NULL WHERE id = :id"), {"id": invoice["id"]})

    [restore] = _pile_up_behind_a_lock(
        app_db,
        LOCK_QUOTATION,
        quote["id"],
        [_call("POST", f"/api/invoices/{invoice['id']}/restore")],
        while_held=unlink_while_holding,
    )

    assert restore.status_code == 200, restore.text[:300]
    assert _stock(app_db, tenant["product"]) == stock_before - 2
    assert _status_of(app_db, quote["id"]) == "open"
