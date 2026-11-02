"""Conversion under real concurrency, on real Postgres, as the restricted role.

SQLite ignores FOR UPDATE and serialises every writer, so none of this can be proven
on the suite's normal database. Two threads convert one quotation through the real
app: one must win, the other gets a 409, and stock and the invoice number move once.

Also the piece the design leaned on without proof: that FOR UPDATE works under the
RLS policies for the app role, sees only its own company, and is really held.

Skipped when DATABASE_URL is not Postgres.
"""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.core.config import settings
from src.db.session import get_db
from src.db.tenant_context import set_tenant_context
from src.models.invoice import Invoice
from src.models.quotation import Quotation
from src.models.user import User, UserRole

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import test_tenant_isolation as iso  # noqa: E402
from quotation_helpers import seed_financial_year  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="row locks and partial indexes need Postgres",
)


@pytest.fixture(params=["shared_hosting", "single_tenant"])
def deployment(request, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", request.param)
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", 3)
    return request.param


@pytest.fixture
def app_db(clean_rls_db, deployment):
    """Each request on its own connection: the app role in shared hosting, else the owner."""
    factory = clean_rls_db.AppSession if deployment == "shared_hosting" else clean_rls_db.OwnerSession

    def _get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db
    try:
        yield clean_rls_db
    finally:
        app.dependency_overrides[get_db] = previous


@pytest.fixture
def signed_in():
    holder = {"email": None}

    def _current_user(db: Session = Depends(get_db)) -> User:
        return db.query(User).filter(User.email == holder["email"]).one()

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _current_user

    def switch(email: str) -> None:
        holder["email"] = email

    try:
        yield switch
    finally:
        app.dependency_overrides[get_current_user] = previous


def _seed_user(db, email: str) -> None:
    with db.OwnerSession() as owner:
        iso._user(owner, email, role=UserRole.admin)


def _seed_company(client, signed_in, db, email: str, name: str, sku: str) -> dict:
    _seed_user(db, email)
    signed_in(email)
    company = iso._create_company(client, name)
    # Shared hosting seeds a year with each company; single tenant sets one up by hand.
    if not iso._ok(client.get("/api/financial-years/")):
        seed_financial_year(client)
    ledger = iso._create_ledger(client, f"{name} Customer")
    product = iso._create_product(client, sku)
    return {"company": company, "ledger": ledger, "product": product, "email": email}


def _create_quote(client, tenant: dict, quantity: int = 2) -> dict:
    return iso._ok(client.post("/api/quotations/", json={
        "ledger_id": tenant["ledger"],
        "items": [{"product_id": tenant["product"], "quantity": quantity, "unit_price": 100}],
    }))


def _stock(db, product_id: int) -> float:
    with db.owner_engine.connect() as conn:
        return float(conn.execute(text("SELECT quantity FROM inventory WHERE product_id = :p"), {"p": product_id}).scalar())


def _sales_counter(db, company_id: int) -> int:
    with db.owner_engine.connect() as conn:
        return conn.execute(text(
            "SELECT next_sequence FROM invoice_series WHERE voucher_type = 'sales' AND company_id = :c"
        ), {"c": company_id}).scalar()


def _invoices_for(db, quotation_id: int) -> list[str]:
    with db.owner_engine.connect() as conn:
        return [row[0] for row in conn.execute(text(
            "SELECT status FROM invoices WHERE source_quotation_id = :q"
        ), {"q": quotation_id})]


def _status_of(db, quotation_id: int) -> str:
    with db.owner_engine.connect() as conn:
        return conn.execute(text("SELECT status FROM quotations WHERE id = :q"), {"q": quotation_id}).scalar()


@pytest.mark.parametrize("attempt", range(5))
def test_two_threads_convert_one_quotation(app_db, signed_in, attempt):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote = _create_quote(client, tenant)
    draft = iso._ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    stock_before = _stock(app_db, tenant["product"])
    counter_before = _sales_counter(app_db, tenant["company"])

    start = threading.Barrier(2)

    def convert():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.post(f"/api/quotations/{quote['id']}/convert", json=draft)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result(timeout=30) for future in [pool.submit(convert), pool.submit(convert)]]

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 409], [response.text[:300] for response in responses]
    winner = next(response.json() for response in responses if response.status_code == 200)
    loser = next(response.json() for response in responses if response.status_code == 409)

    assert loser["detail"]["code"] == "quotation_already_converted"
    assert loser["detail"]["invoice_id"] == winner["id"]
    assert loser["detail"]["invoice_number"] == winner["invoice_number"]

    assert _invoices_for(app_db, quote["id"]) == ["active"]
    assert _stock(app_db, tenant["product"]) == stock_before - 2
    assert _sales_counter(app_db, tenant["company"]) == counter_before + 1
    assert _status_of(app_db, quote["id"]) == "converted"


def test_second_converter_really_waits_on_the_row_lock(app_db, signed_in):
    """Deterministic: while a transaction holds the lock, a conversion cannot get past it."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote = _create_quote(client, tenant)
    draft = iso._ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]

    owner = app_db.owner_engine.connect()
    holding = owner.begin()
    owner.execute(text("SELECT id FROM quotations WHERE id = :q FOR UPDATE"), {"q": quote["id"]})
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: TestClient(app).post(f"/api/quotations/{quote['id']}/convert", json=draft))
            time.sleep(1)
            assert not future.done(), "conversion went straight past a held row lock"
            assert _invoices_for(app_db, quote["id"]) == []
            # Whoever holds the lock declines it; the waiter must see that, not its stale read.
            owner.execute(text("UPDATE quotations SET status = 'declined' WHERE id = :q"), {"q": quote["id"]})
            holding.commit()
            response = future.result(timeout=30)
    finally:
        owner.close()

    assert response.status_code == 400
    assert "Reopen" in response.text
    assert _invoices_for(app_db, quote["id"]) == []


def test_the_partial_index_holds_when_the_lock_is_bypassed(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote = _create_quote(client, tenant)
    first = iso._ok(client.post(f"/api/quotations/{quote['id']}/convert", json=iso._ok(
        client.get(f"/api/quotations/{quote['id']}/conversion-draft")
    )["invoice"]))
    other = iso._create_invoice(client, tenant["ledger"], tenant["product"])

    with app_db.OwnerSession() as owner:
        row = owner.query(Invoice).filter(Invoice.id == other["id"]).one()
        row.source_quotation_id = quote["id"]
        with pytest.raises(IntegrityError) as caught:
            owner.commit()
        assert "ux_invoices_active_source_quotation" in str(caught.value)
        owner.rollback()

    # Cancelled ones fall out of it, so a re-conversion is allowed.
    iso._ok(client.delete(f"/api/invoices/{first['id']}"))
    draft = iso._ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    second = iso._ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft))
    assert sorted(_invoices_for(app_db, quote["id"])) == ["active", "cancelled"]
    # And restoring the old one is refused while the new one is live.
    restored = client.post(f"/api/invoices/{first['id']}/restore")
    assert restored.status_code == 409
    assert second["invoice_number"] in restored.text


def test_failed_conversion_rolls_back_the_number_and_stock(app_db, signed_in):
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote = _create_quote(client, tenant, quantity=500)  # Stock is 100.
    counter_before = _sales_counter(app_db, tenant["company"])
    stock_before = _stock(app_db, tenant["product"])

    draft = iso._ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    assert "stock_shortfall" in {warning["code"] for warning in draft["warnings"]}
    response = client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"])
    assert response.status_code == 400

    assert _status_of(app_db, quote["id"]) == "open"
    assert _sales_counter(app_db, tenant["company"]) == counter_before
    assert _stock(app_db, tenant["product"]) == stock_before
    assert _invoices_for(app_db, quote["id"]) == []


def test_a_lost_race_on_the_index_is_a_409_not_a_500(app_db, signed_in, monkeypatch):
    """Skip the status check, as an unforeseen path would, and the index still decides."""
    from src.services import quotation as quotation_service

    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote = _create_quote(client, tenant)
    draft = iso._ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    first = iso._ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft))

    monkeypatch.setattr(quotation_service, "_require_convertible", lambda db, quotation: None)
    response = client.post(f"/api/quotations/{quote['id']}/convert", json=draft)
    assert response.status_code == 409
    assert response.json()["detail"]["invoice_id"] == first["id"]
    assert _invoices_for(app_db, quote["id"]) == ["active"]


def test_cancelling_the_invoice_while_a_conversion_runs_cannot_deadlock(app_db, signed_in):
    """Both orders take the quotation first, so one simply waits for the other."""
    client = TestClient(app)
    tenant = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    quote = _create_quote(client, tenant)
    draft = iso._ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    invoice = iso._ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft))

    start = threading.Barrier(2)

    def cancel():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.delete(f"/api/invoices/{invoice['id']}")

    def convert():
        thread_client = TestClient(app)
        start.wait()
        return thread_client.post(f"/api/quotations/{quote['id']}/convert", json=draft)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled, converted = [future.result(timeout=30) for future in [pool.submit(cancel), pool.submit(convert)]]

    assert cancelled.status_code == 200, cancelled.text
    # Depending on who got the lock first: refused, or a clean re-conversion.
    assert converted.status_code in (200, 409), converted.text
    expected = ["active", "cancelled"] if converted.status_code == 200 else ["cancelled"]
    assert sorted(_invoices_for(app_db, quote["id"])) == expected
    assert _status_of(app_db, quote["id"]) == ("converted" if converted.status_code == 200 else "open")


# ---------------------------------------------------------------------------
# FOR UPDATE under the restricted role
# ---------------------------------------------------------------------------

@pytest.fixture
def shared_only(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", 3)


@pytest.fixture
def two_tenant_quotes(clean_rls_db, shared_only, signed_in):
    db = clean_rls_db

    def _get_db():
        session = db.AppSession()
        try:
            yield session
        finally:
            session.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db
    try:
        client = TestClient(app)
        a = _seed_company(client, signed_in, db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
        a["quote"] = _create_quote(client, a)
        b = _seed_company(client, signed_in, db, "bob@beta.example", "Beta Stores", "BETA-1")
        b["quote"] = _create_quote(client, b)
        yield db, a, b
    finally:
        app.dependency_overrides[get_db] = previous


def test_for_update_finds_and_locks_own_row_as_the_app_role(two_tenant_quotes):
    db, a, _ = two_tenant_quotes
    session = db.AppSession()
    try:
        assert session.execute(text("SELECT current_user")).scalar() == db.role
        set_tenant_context(session, company_id=a["company"])
        row = (
            session.query(Quotation)
            .filter(Quotation.id == a["quote"]["id"])
            .with_for_update()
            .first()
        )
        assert row is not None and row.id == a["quote"]["id"]

        # Held for real: another transaction cannot take it without waiting.
        with db.owner_engine.connect() as probe:
            with pytest.raises(Exception, match="could not obtain lock"):
                probe.execute(text("SELECT id FROM quotations WHERE id = :q FOR UPDATE NOWAIT"), {"q": row.id})
            probe.rollback()
    finally:
        session.rollback()
        session.close()

    # And released: the same probe now succeeds.
    with db.owner_engine.connect() as probe:
        probe.execute(text("SELECT id FROM quotations WHERE id = :q FOR UPDATE NOWAIT"), {"q": a["quote"]["id"]})
        probe.rollback()


def test_for_update_cannot_see_the_other_tenants_row(two_tenant_quotes):
    db, a, b = two_tenant_quotes
    session = db.AppSession()
    try:
        set_tenant_context(session, company_id=b["company"])
        row = (
            session.query(Quotation)
            .filter(Quotation.id == a["quote"]["id"])
            .with_for_update()
            .first()
        )
        assert row is None
        # Raw SQL too, so no application filter can be the thing that hid it.
        assert session.execute(text("SELECT count(*) FROM quotations WHERE id = :q"), {"q": a["quote"]["id"]}).scalar() == 0
        assert session.execute(text("SELECT count(*) FROM quotation_items q WHERE q.quotation_id = :q"), {"q": a["quote"]["id"]}).scalar() == 0
    finally:
        session.rollback()
        session.close()

    # It took no lock on A's row either.
    with db.owner_engine.connect() as probe:
        probe.execute(text("SELECT id FROM quotations WHERE id = :q FOR UPDATE NOWAIT"), {"q": a["quote"]["id"]})
        probe.rollback()


def test_with_no_tenant_context_nothing_is_visible(two_tenant_quotes):
    db, _, _ = two_tenant_quotes
    session = db.AppSession()
    try:
        assert session.execute(text("SELECT count(*) FROM quotations")).scalar() == 0
        assert session.execute(text("SELECT count(*) FROM quotation_items")).scalar() == 0
    finally:
        session.rollback()
        session.close()


def test_a_row_for_another_company_cannot_be_written(two_tenant_quotes):
    db, a, b = two_tenant_quotes
    session = db.AppSession()
    try:
        set_tenant_context(session, company_id=b["company"])
        with pytest.raises(Exception, match="row-level security"):
            session.execute(text("""
                INSERT INTO quotation_items
                    (quotation_id, product_id, quantity, unit_price, gst_rate, taxable_amount,
                     tax_amount, cgst_amount, sgst_amount, igst_amount, line_total)
                VALUES (:q, :p, 1, 1, 0, 1, 0, 0, 0, 0, 1)
            """), {"q": a["quote"]["id"], "p": b["product"]})
    finally:
        session.rollback()
        session.close()


def test_conversion_through_the_app_as_the_restricted_role(two_tenant_quotes, signed_in):
    """The whole path under RLS: lock, invoice, number, stock, status, cancel, restore."""
    db, a, b = two_tenant_quotes
    client = TestClient(app)
    signed_in(a["email"])
    draft = iso._ok(client.get(f"/api/quotations/{a['quote']['id']}/conversion-draft"))["invoice"]
    invoice = iso._ok(client.post(f"/api/quotations/{a['quote']['id']}/convert", json=draft))
    assert invoice["source_quotation_number"] == a["quote"]["quotation_number"]
    assert _status_of(db, a["quote"]["id"]) == "converted"

    # B cannot convert or even see A's, under the same role.
    signed_in(b["email"])
    assert client.post(f"/api/quotations/{a['quote']['id']}/convert", json=draft).status_code == 404
    assert client.get(f"/api/quotations/{a['quote']['id']}/pdf").status_code == 404
    assert client.delete(f"/api/invoices/{invoice['id']}").status_code == 404

    signed_in(a["email"])
    iso._ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _status_of(db, a["quote"]["id"]) == "open"
    iso._ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _status_of(db, a["quote"]["id"]) == "converted"


def test_deleting_a_quoted_address_as_the_app_role_clears_the_link_and_keeps_the_snapshot(two_tenant_quotes, signed_in):
    db, a, _ = two_tenant_quotes
    client = TestClient(app)
    signed_in(a["email"])
    address = iso._ok(client.post(
        f"/api/ledgers/{a['ledger']}/addresses/",
        json={"label": "Warehouse", "address": "9 Dock Road"},
    ), 201)
    quote = iso._ok(client.post("/api/quotations/", json={
        "ledger_id": a["ledger"],
        "shipping_address_same_as_billing": False,
        "shipping_address_id": address["id"],
        "items": [{"product_id": a["product"], "quantity": 1, "unit_price": 100}],
    }))
    assert quote["shipping_address_id"] == address["id"]

    assert client.delete(f"/api/ledgers/{a['ledger']}/addresses/{address['id']}").status_code == 204

    after = iso._ok(client.get(f"/api/quotations/{quote['id']}"))
    assert after["shipping_address_id"] is None
    assert after["shipping_address"] == "9 Dock Road"
    draft = iso._ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    assert "shipping_address_gone" in {warning["code"] for warning in draft["warnings"]}
    assert draft["invoice"]["shipping_address_same_as_billing"] is True


def test_public_share_page_renders_through_rls(two_tenant_quotes, signed_in, monkeypatch):
    from src.api.routes.public_share import reset_rate_limits

    monkeypatch.setattr(settings, "SHARE_LINKS_ENABLED", True)
    reset_rate_limits()
    db, a, b = two_tenant_quotes
    client = TestClient(app)
    signed_in(a["email"])
    share = iso._ok(client.post("/api/share/", json={"resource_type": "quotation", "resource_id": a["quote"]["id"]}))

    with iso._real_auth():
        page = client.get(f"/s/{share['token']}")
        assert page.status_code == 200, page.text
        assert "Alpha Traders" in page.text and "Beta Stores" not in page.text
        pdf = client.get(f"/s/{share['token']}/pdf")
        assert pdf.status_code == 200, pdf.text[:200]
        document = client.get(f"/s/{share['token']}/document.html")
        assert "This is not a tax invoice" in document.text
    reset_rate_limits()
