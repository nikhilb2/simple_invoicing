"""Tenant isolation in shared hosting.

Two strangers, A and B, each sign up and create a company through the real
POST /api/company/companies. A then fills theirs with one of everything. Every
test below is B (or a user with no company at all) trying to see or touch A's
data some other way: the X-Company-Id header, selecting A's company, listing,
fetching or mutating A's rows by id, or pointing a new document at them.

The single-tenant behaviour these rules replace is covered once at the end, so
a regression in the mode switch shows up here too.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from app_main import app
from src.api.deps import get_current_user
from src.core.config import settings
from src.core.security import create_access_token
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.company_membership import CompanyMembership
from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries
from src.models.user import User, UserRole
from src.services.company_access import add_membership


# ---------------------------------------------------------------------------
# Acting as a persisted user
# ---------------------------------------------------------------------------

@pytest.fixture
def shared_hosting(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", 3)
    monkeypatch.setattr(settings, "SHARE_LINKS_ENABLED", True)


@pytest.fixture
def act_as():
    """Swap the conftest user for a persisted one; call it again to switch.

    The override loads the user through the request's own session, so the
    active_company_id that get_active_company writes is saved for real.
    """
    holder = {"email": None}

    def _current_user(db: Session = Depends(get_db)) -> User:
        return db.query(User).filter(User.email == holder["email"]).one()

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _current_user

    def switch(user: User) -> None:
        holder["email"] = user.email

    try:
        yield switch
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous


@contextmanager
def _real_auth():
    """Drop every get_current_user override so the Authorization header decides."""
    previous = app.dependency_overrides.pop(get_current_user, None)
    try:
        yield
    finally:
        if previous is not None:
            app.dependency_overrides[get_current_user] = previous


def _user(db, email: str, *, verified: bool = True, role: UserRole = UserRole.staff) -> User:
    user = User(
        email=email,
        full_name=email.split("@")[0].title(),
        hashed_password="not-a-real-hash",
        role=role,
        email_verified_at=datetime.now(timezone.utc) if verified else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers(company_id: int) -> dict[str, str]:
    return {"X-Company-Id": str(company_id)}


# ---------------------------------------------------------------------------
# Payloads (shapes from test_company_switching / test_invoice_duplicate)
# ---------------------------------------------------------------------------

def _company_payload(name: str) -> dict:
    return {
        "name": name,
        "address": "",
        "gst": "",
        "phone_number": "",
        "currency_code": "INR",
        "email": "",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def _ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


def _create_company(client, name: str) -> int:
    return _ok(client.post("/api/company/companies", json=_company_payload(name)))["id"]


def _create_ledger(client, name: str) -> int:
    return _ok(client.post("/api/ledgers/", json={
        "name": name,
        "address": "1 Market Road",
        "gst": "",
        "opening_balance": None,
        "phone_number": "9876543210",
        "email": "",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }))["id"]


def _create_product(client, sku: str) -> int:
    return _ok(client.post("/api/products/", json={
        "sku": sku,
        "name": f"Widget {sku}",
        "price": 100,
        "gst_rate": 18,
        "maintain_inventory": True,
        "initial_quantity": 100,
    }))["id"]


def _invoice_payload(ledger_id: int, product_id: int) -> dict:
    return {
        "ledger_id": ledger_id,
        "voucher_type": "sales",
        "items": [{"product_id": product_id, "quantity": 2, "unit_price": 100}],
    }


def _create_invoice(client, ledger_id: int, product_id: int) -> dict:
    return _ok(client.post("/api/invoices/", json=_invoice_payload(ledger_id, product_id)))


def _credit_note_payload(ledger_id: int, invoice: dict) -> dict:
    return {
        "ledger_id": ledger_id,
        "invoice_ids": [invoice["id"]],
        "credit_note_type": "return",
        "direction": "outward",
        "items": [{
            "invoice_id": invoice["id"],
            "invoice_item_id": invoice["items"][0]["id"],
            "quantity": 1,
        }],
    }


def _create_credit_note(client, ledger_id: int, invoice: dict) -> dict:
    return _ok(client.post("/api/credit-notes/", json=_credit_note_payload(ledger_id, invoice)), 201)


def _ids(rows) -> set[int]:
    if isinstance(rows, dict):
        rows = rows["items"]
    return {row["id"] for row in rows}


# ---------------------------------------------------------------------------
# The two tenants
# ---------------------------------------------------------------------------

@pytest.fixture
def tenants(client, db_session, shared_hosting, act_as):
    """A and B with a company each; A's company holds one of everything."""
    user_a = _user(db_session, "alice@alpha.example")
    user_b = _user(db_session, "bob@beta.example")
    user_c = _user(db_session, "carol@nowhere.example")

    act_as(user_b)
    company_b = _create_company(client, "Beta Stores")

    act_as(user_a)
    company_a = _create_company(client, "Alpha Traders")
    ledger = _create_ledger(client, "Alpha Customer")
    product = _create_product(client, "ALPHA-1")
    invoice = _create_invoice(client, ledger, product)
    payment = _ok(client.post("/api/payments/", json={
        "ledger_id": ledger,
        "voucher_type": "receipt",
        "amount": 50,
        "mode": "cash",
    }))
    credit_note = _create_credit_note(client, ledger, invoice)
    term = _ok(client.post("/api/company/terms", json={"content": "Alpha terms"}))
    share = _ok(client.post("/api/share/", json={"resource_type": "invoice", "resource_id": invoice["id"]}))
    api_key = _ok(client.post("/api/api-keys/", json={
        "name": "Alpha key",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    }), 201)
    fys = _ok(client.get("/api/financial-years/"))
    series = _ok(client.get("/api/invoice-series/"))

    return SimpleNamespace(
        user_a=user_a,
        user_b=user_b,
        user_c=user_c,
        company_a=company_a,
        company_b=company_b,
        ledger=ledger,
        product=product,
        invoice=invoice,
        payment=payment,
        credit_note=credit_note,
        term=term,
        share=share,
        api_key=api_key,
        fy_ids=_ids(fys),
        series_ids=_ids(series),
    )


# ---------------------------------------------------------------------------
# Reaching A's company at all
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/invoices/",
    "/api/ledgers/",
    "/api/products/",
    "/api/payments/",
    "/api/credit-notes/",
    "/api/financial-years/",
    "/api/invoice-series/",
    "/api/share/",
    "/api/api-keys/",
])
def test_company_header_for_another_tenant_is_forbidden(client, tenants, act_as, path):
    act_as(tenants.user_b)
    response = client.get(path, headers=_headers(tenants.company_a))
    assert response.status_code == 403, response.text


def test_company_header_for_a_missing_company_is_also_forbidden(client, tenants, act_as):
    # 403, not 404: B must not be able to probe which company ids exist.
    act_as(tenants.user_b)
    response = client.get("/api/ledgers/", headers=_headers(tenants.company_a + 1000))
    assert response.status_code == 403, response.text


def test_selecting_another_tenants_company_is_forbidden(client, db_session, tenants, act_as):
    act_as(tenants.user_b)
    assert client.post(f"/api/company/select/{tenants.company_a}").status_code == 403
    assert client.post(f"/api/company/select/{tenants.company_a + 1000}").status_code == 403

    db_session.refresh(tenants.user_b)
    assert tenants.user_b.active_company_id == tenants.company_b


def test_company_list_shows_only_the_users_own_companies(client, tenants, act_as):
    act_as(tenants.user_b)
    companies = _ok(client.get("/api/company/companies"))
    assert [(c["id"], c["is_active"]) for c in companies] == [(tenants.company_b, True)]


def test_company_profile_is_the_users_own(client, tenants, act_as):
    act_as(tenants.user_b)
    assert _ok(client.get("/api/company/"))["name"] == "Beta Stores"


# ---------------------------------------------------------------------------
# Lists inside B's own company
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path, attr", [
    ("/api/invoices/", "invoice"),
    ("/api/ledgers/", "ledger"),
    ("/api/products/", "product"),
    ("/api/payments/", "payment"),
    ("/api/credit-notes/", "credit_note"),
    ("/api/company/terms", "term"),
    ("/api/share/", "share"),
    ("/api/api-keys/", "api_key"),
])
def test_lists_in_own_company_omit_the_other_tenants_rows(client, tenants, act_as, path, attr):
    act_as(tenants.user_b)
    row = getattr(tenants, attr)
    row_id = row if isinstance(row, int) else row["id"]
    assert row_id not in _ids(_ok(client.get(path)))
    assert row_id not in _ids(_ok(client.get(path, headers=_headers(tenants.company_b))))


def test_financial_years_and_series_are_per_company(client, tenants, act_as):
    act_as(tenants.user_b)
    own_fys = _ids(_ok(client.get("/api/financial-years/")))
    own_series = _ids(_ok(client.get("/api/invoice-series/")))

    # B has their own seeded year and series, and none of A's.
    assert len(own_fys) == 1 and len(own_series) == 5
    assert own_fys.isdisjoint(tenants.fy_ids)
    assert own_series.isdisjoint(tenants.series_ids)


_REPORTS = [
    "/api/dashboard/metrics",
    "/api/analytics/sales-by-month",
    "/api/analytics/sales-by-product/csv",
    "/api/analytics/profit-loss",
    "/api/analytics/product-performance",
    "/api/inventory/",
    "/api/products/with-inventory",
    "/api/products/export-csv",
    "/api/invoices/export",
    "/api/invoices/dues",
    "/api/ledgers/day-book",
    "/api/ledgers/day-book/csv",
    "/api/ledgers/tax-ledger/",
    "/api/ledgers/tax-ledger/csv",
    "/api/ledgers/tax-ledger/gstr1/summary",
    "/api/serials/scan?code=ALPHA-1",
]


def test_reports_and_exports_in_own_company_never_mention_the_other_tenant(client, tenants, act_as):
    fy_range = {"from_date": "2026-04-01", "to_date": "2027-03-31"}
    markers = ["Alpha Customer", "Widget ALPHA-1", tenants.invoice["invoice_number"]]

    # A sees their own data in the day book, so the markers are worth looking for.
    act_as(tenants.user_a)
    day_book = client.get("/api/ledgers/day-book", params=fy_range).text
    assert "Alpha Customer" in day_book and tenants.invoice["invoice_number"] in day_book

    act_as(tenants.user_b)
    for path in _REPORTS:
        response = client.get(path, params=fy_range)
        assert response.status_code in (200, 404), f"{path}: {response.status_code} {response.text}"
        leaked = [marker for marker in markers if marker in response.text]
        assert leaked == [], f"{path} leaks {leaked}"

    metrics = _ok(client.get("/api/dashboard/metrics"))
    assert metrics["catalog"]["total_products"] == 0


def test_invoice_search_does_not_find_the_other_tenants_invoice(client, tenants, act_as):
    act_as(tenants.user_b)
    found = _ok(client.get("/api/invoices/", params={"search": tenants.invoice["invoice_number"]}))
    assert found["items"] == []


# ---------------------------------------------------------------------------
# A's rows by id, from B's own company
# ---------------------------------------------------------------------------

def _reads_by_id(t) -> list[str]:
    return [
        f"/api/invoices/{t.invoice['id']}",
        f"/api/invoices/{t.invoice['id']}/pdf",
        f"/api/ledgers/{t.ledger}",
        f"/api/ledgers/{t.ledger}/statement",
        f"/api/ledgers/{t.ledger}/unpaid-invoices",
        f"/api/products/{t.product}",
        f"/api/payments/{t.payment['id']}",
        f"/api/payments/{t.payment['id']}/pdf",
        f"/api/credit-notes/{t.credit_note['id']}",
        f"/api/credit-notes/{t.credit_note['id']}/pdf",
    ]


def _not_found_by_the_handler(response) -> bool:
    # A 404 from an unknown route says "Not Found"; the handlers name the row.
    return response.status_code == 404 and response.json().get("detail") != "Not Found"


def test_reading_the_other_tenants_rows_by_id_is_not_found(client, tenants, act_as):
    # The owner can read every one of them, so a 404 below is the scoping at work.
    act_as(tenants.user_a)
    for path in _reads_by_id(tenants):
        assert client.get(path).status_code == 200, path

    act_as(tenants.user_b)
    for path in _reads_by_id(tenants):
        response = client.get(path)
        assert _not_found_by_the_handler(response), f"{path}: {response.status_code} {response.text}"


def test_changing_the_other_tenants_rows_by_id_is_not_found(client, tenants, act_as):
    t = tenants
    fy_id = next(iter(t.fy_ids))
    series_id = min(t.series_ids)
    attempts = [
        ("put", f"/api/ledgers/{t.ledger}", {
            "name": "Hijacked", "address": "x", "gst": "", "phone_number": "9876543210",
        }),
        ("delete", f"/api/ledgers/{t.ledger}", None),
        ("put", f"/api/products/{t.product}", {"sku": "HIJACK", "name": "Hijacked", "price": 1}),
        ("delete", f"/api/products/{t.product}", None),
        ("put", f"/api/invoices/{t.invoice['id']}", _invoice_payload(t.ledger, t.product)),
        ("delete", f"/api/invoices/{t.invoice['id']}", None),
        ("post", f"/api/invoices/{t.invoice['id']}/duplicate", None),
        ("delete", f"/api/payments/{t.payment['id']}", None),
        ("post", f"/api/credit-notes/{t.credit_note['id']}/cancel", None),
        ("put", f"/api/company/terms/{t.term['id']}", {"content": "Hijacked"}),
        ("delete", f"/api/company/terms/{t.term['id']}", None),
        ("delete", f"/api/share/{t.share['id']}", None),
        ("delete", f"/api/api-keys/{t.api_key['id']}", None),
        ("put", f"/api/invoice-series/{series_id}", {
            "prefix": "HIJ", "suffix": "", "include_year": True, "year_format": "YYYY",
            "separator": "-", "pad_digits": 3,
        }),
        ("put", f"/api/financial-years/{fy_id}/activate", None),
    ]

    act_as(t.user_b)
    for method, path, body in attempts:
        kwargs = {"json": body} if body is not None else {}
        response = client.request(method.upper(), path, **kwargs)
        assert _not_found_by_the_handler(response), f"{method} {path}: {response.status_code} {response.text}"

    # And nothing of A's actually moved.
    act_as(t.user_a)
    assert _ok(client.get(f"/api/ledgers/{t.ledger}"))["name"] == "Alpha Customer"
    assert _ok(client.get(f"/api/products/{t.product}"))["name"] == "Widget ALPHA-1"
    assert _ok(client.get(f"/api/invoices/{t.invoice['id']}"))["status"] == "active"
    assert _ok(client.get(f"/api/credit-notes/{t.credit_note['id']}"))["status"] == "active"
    assert _ok(client.get(f"/api/payments/{t.payment['id']}"))["id"] == t.payment["id"]
    assert [term["content"] for term in _ok(client.get("/api/company/terms"))] == ["Alpha terms"]
    assert t.share["id"] in _ids(_ok(client.get("/api/share/")))
    assert t.api_key["id"] in _ids(_ok(client.get("/api/api-keys/")))
    series = {s["id"]: s for s in _ok(client.get("/api/invoice-series/"))}
    assert series[series_id]["prefix"] != "HIJ"
    assert [fy["is_active"] for fy in _ok(client.get("/api/financial-years/"))] == [True]


# ---------------------------------------------------------------------------
# New documents in B's company pointing at A's rows
# ---------------------------------------------------------------------------

def test_invoice_cannot_use_the_other_tenants_ledger_or_product(client, tenants, act_as):
    act_as(tenants.user_b)
    own_ledger = _create_ledger(client, "Beta Customer")
    own_product = _create_product(client, "BETA-1")

    with_their_ledger = client.post("/api/invoices/", json=_invoice_payload(tenants.ledger, own_product))
    assert with_their_ledger.status_code == 404, with_their_ledger.text

    with_their_product = client.post("/api/invoices/", json=_invoice_payload(own_ledger, tenants.product))
    assert with_their_product.status_code == 404, with_their_product.text


def test_payment_cannot_use_the_other_tenants_ledger(client, tenants, act_as):
    act_as(tenants.user_b)
    response = client.post("/api/payments/", json={
        "ledger_id": tenants.ledger, "voucher_type": "receipt", "amount": 10,
    })
    assert response.status_code == 404, response.text


def test_credit_note_cannot_target_the_other_tenants_invoice(client, tenants, act_as):
    act_as(tenants.user_b)
    own_ledger = _create_ledger(client, "Beta Customer")
    response = client.post(
        "/api/credit-notes/", json=_credit_note_payload(own_ledger, tenants.invoice),
    )
    assert response.status_code in (400, 404), response.text


def test_share_link_cannot_be_minted_for_the_other_tenants_invoice(client, tenants, act_as):
    act_as(tenants.user_b)
    response = client.post("/api/share/", json={
        "resource_type": "invoice", "resource_id": tenants.invoice["id"],
    })
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# API keys authenticate as their creator, inside their own company only
# ---------------------------------------------------------------------------

def test_api_key_is_pinned_to_its_company(client, tenants):
    bearer = {"Authorization": f"Bearer {tenants.api_key['raw_key']}"}
    with _real_auth():
        own = client.get("/api/ledgers/", headers=bearer)
        assert tenants.ledger in _ids(_ok(own))

        elsewhere = client.get("/api/ledgers/", headers={**bearer, **_headers(tenants.company_b)})
        assert elsewhere.status_code == 403, elsewhere.text


def test_api_key_cannot_take_account_actions_beyond_its_company(client, db_session, tenants, act_as):
    # A second company for A, which the key (issued in A's first) must not reach.
    act_as(tenants.user_a)
    other = _ok(client.post("/api/company/companies", json=_company_payload("Alpha Two")))["id"]

    bearer = {"Authorization": f"Bearer {tenants.api_key['raw_key']}"}
    with _real_auth():
        listed = client.get("/api/company/companies", headers=bearer)
        assert [c["id"] for c in _ok(listed)] == [tenants.company_a]

        assert client.post(f"/api/company/select/{other}", headers=bearer).status_code == 403
        created = client.post("/api/company/companies", json=_company_payload("Via Key"), headers=bearer)
        assert created.status_code == 403, created.text
        # The OAuth consent flow would otherwise mint a token for any of A's companies.
        consent = client.get("/api/oauth/authorize/request/anything", headers=bearer)
        assert consent.status_code == 403, consent.text
        grants = client.get("/api/oauth/grants", headers=bearer)
        assert grants.status_code == 403, grants.text


def test_api_key_cannot_change_its_creators_password(client, db_session, tenants):
    bearer = {"Authorization": f"Bearer {tenants.api_key['raw_key']}"}
    with _real_auth():
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "whatever-it-is", "new_password": "Takeover@123"},
            headers=bearer,
        )
    # 403 from the session guard, before the current password is even checked.
    assert response.status_code == 403, response.text
    db_session.expire_all()
    user_a = db_session.query(User).filter(User.id == tenants.user_a.id).one()
    assert user_a.hashed_password == "not-a-real-hash"


def test_api_key_stops_working_when_its_creator_loses_the_company(client, db_session, tenants):
    db_session.query(CompanyMembership).filter(
        CompanyMembership.user_id == tenants.user_a.id,
        CompanyMembership.company_id == tenants.company_a,
    ).delete()
    db_session.commit()

    with _real_auth():
        response = client.get(
            "/api/ledgers/", headers={"Authorization": f"Bearer {tenants.api_key['raw_key']}"},
        )
    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# OAuth consent offers only the user's own companies
# ---------------------------------------------------------------------------

def test_oauth_consent_lists_only_accessible_companies(db_session, tenants):
    from src.api.routes import oauth as oauth_routes
    from src.models.oauth import OAuthAuthRequest, OAuthClient

    db_session.add(OAuthClient(
        client_id="client-1",
        client_name="Some MCP client",
        redirect_uris='["https://client.example/callback"]',
    ))
    db_session.add(OAuthAuthRequest(
        request_id="req-1",
        client_id="client-1",
        redirect_uri="https://client.example/callback",
        scope="invoicing:read",
        code_challenge="x" * 43,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    ))
    db_session.commit()

    db_session.refresh(tenants.user_b)
    info = oauth_routes.get_authorize_request("req-1", db=db_session, current_user=tenants.user_b)
    assert [c.id for c in info.companies] == [tenants.company_b]
    assert info.default_company_id == tenants.company_b


# ---------------------------------------------------------------------------
# A user with no company yet
# ---------------------------------------------------------------------------

def test_user_without_a_company_is_told_to_create_one(client, tenants, act_as):
    act_as(tenants.user_c)

    profile = client.get("/api/company/")
    assert profile.status_code == 409, profile.text
    assert profile.json()["detail"]["code"] == "company_required"

    scoped = client.get("/api/ledgers/")
    assert scoped.status_code == 409, scoped.text
    assert scoped.json()["detail"]["code"] == "company_required"

    assert _ok(client.get("/api/company/companies")) == []


def test_user_without_a_company_cannot_borrow_one_by_header(client, tenants, act_as):
    act_as(tenants.user_c)
    response = client.get("/api/ledgers/", headers=_headers(tenants.company_a))
    assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Platform surfaces: a tenant's admin is not the platform's admin
# ---------------------------------------------------------------------------

def _platform_calls():
    return [
        ("get", "/api/smtp-configs/", None),
        ("get", "/api/users/", None),
        ("post", "/api/users/", {
            "email": "mallory@example.com", "full_name": "Mallory",
            "password": "password123", "role": "admin",
        }),
        ("post", "/api/marketplace/sync-all", None),
    ]


def test_platform_surfaces_are_forbidden_to_a_tenant_admin(client, tenants, act_as):
    act_as(tenants.user_a)
    for method, path, body in _platform_calls():
        kwargs = {"json": body} if body is not None else {}
        response = client.request(method.upper(), path, **kwargs)
        assert response.status_code == 403, f"{method} {path}: {response.status_code} {response.text}"


def test_a_global_admin_role_is_not_a_platform_admin(client, db_session, tenants, act_as):
    # The global role is meaningless in shared hosting; only the allowlist counts.
    tenants.user_a.role = UserRole.admin
    db_session.commit()
    act_as(tenants.user_a)
    assert client.get("/api/users/").status_code == 403


def test_platform_admin_allowlist_opens_platform_surfaces(client, tenants, act_as, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", f"ops@example.com, {tenants.user_a.email.upper()}")
    act_as(tenants.user_a)
    users = _ok(client.get("/api/users/"))
    assert tenants.user_b.email in {u["email"] for u in users}


def test_backups_require_a_platform_admin(db_session, tenants, monkeypatch):
    # The backup routes decode the JWT and open their own SessionLocal (so a
    # long pg_dump holds no request session); point that at the test database
    # and call the dependency directly.
    from src.api.routes import backups as backups_routes

    monkeypatch.setattr(backups_routes, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    token = create_access_token(tenants.user_a.email)

    with pytest.raises(HTTPException) as exc:
        backups_routes.require_admin_no_session_hold(token)
    assert exc.value.status_code == 403

    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", tenants.user_a.email)
    assert backups_routes.require_admin_no_session_hold(token).email == tenants.user_a.email


# ---------------------------------------------------------------------------
# Creating a company
# ---------------------------------------------------------------------------

def test_creator_becomes_admin_with_a_seeded_financial_year(db_session, tenants):
    company_id = tenants.company_a
    membership = db_session.query(CompanyMembership).filter(
        CompanyMembership.user_id == tenants.user_a.id,
        CompanyMembership.company_id == company_id,
    ).one()
    assert membership.role == UserRole.admin

    db_session.refresh(tenants.user_a)
    assert tenants.user_a.active_company_id == company_id

    fy = db_session.query(FinancialYear).filter(FinancialYear.company_id == company_id).one()
    assert fy.is_active is True
    today = datetime.now().date()
    start_year = today.year if today.month >= 4 else today.year - 1
    assert fy.label == f"{start_year}-{str(start_year + 1)[-2:]}"

    series = db_session.query(InvoiceSeries).filter(InvoiceSeries.financial_year_id == fy.id).all()
    assert {s.company_id for s in series} == {company_id}
    assert sorted(s.voucher_type for s in series) == [
        "credit_note", "debit_note", "payment", "purchase", "sales",
    ]


def test_company_creation_is_capped_per_user(client, db_session, shared_hosting, act_as, monkeypatch):
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", 1)
    first = _user(db_session, "first@example.com")
    second = _user(db_session, "second@example.com")

    act_as(first)
    _create_company(client, "First Co")
    capped = client.post("/api/company/companies", json=_company_payload("First Co Two"))
    assert capped.status_code == 403, capped.text
    assert "limit reached" in capped.text

    # The cap is per person: someone else's companies do not use it up.
    act_as(second)
    _create_company(client, "Second Co")


def test_unverified_user_cannot_create_a_company(client, db_session, shared_hosting, act_as):
    act_as(_user(db_session, "unverified@example.com", verified=False))
    response = client.post("/api/company/companies", json=_company_payload("Too Soon"))
    assert response.status_code == 403, response.text
    assert db_session.query(CompanyProfile).count() == 0


# ---------------------------------------------------------------------------
# Membership roles, not the global role
# ---------------------------------------------------------------------------

def test_staff_membership_cannot_reach_admin_routes(client, db_session, tenants, act_as):
    gamma = CompanyProfile(name="Gamma Works", address="", gst="", phone_number="")
    db_session.add(gamma)
    db_session.commit()
    add_membership(db_session, tenants.user_b, gamma, UserRole.staff)
    db_session.commit()

    act_as(tenants.user_b)
    in_gamma = _headers(gamma.id)
    assert client.get("/api/ledgers/", headers=in_gamma).status_code == 200
    assert client.get("/api/invoice-series/", headers=in_gamma).status_code == 403
    assert client.post("/api/api-keys/", headers=in_gamma, json={
        "name": "Nope",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    }).status_code == 403

    in_own = _headers(tenants.company_b)
    assert client.get("/api/invoice-series/", headers=in_own).status_code == 200


def test_payment_update_and_cancel_follow_the_membership_role(client, db_session, tenants, act_as):
    # Self-registered users are global staff, so a global role check here would
    # lock every company's own admin out of correcting their own payments.
    company = db_session.get(CompanyProfile, tenants.company_a)
    add_membership(db_session, tenants.user_b, company, UserRole.staff)
    db_session.commit()
    path = f"/api/payments/{tenants.payment['id']}"
    edit = {"voucher_type": "receipt", "amount": 75, "mode": "cash"}

    act_as(tenants.user_b)
    in_alpha = _headers(tenants.company_a)
    assert client.put(path, headers=in_alpha, json=edit).status_code == 403
    assert client.delete(path, headers=in_alpha).status_code == 403

    act_as(tenants.user_a)
    assert tenants.user_a.role == UserRole.staff
    updated = client.put(path, headers=in_alpha, json=edit)
    assert updated.status_code == 200, updated.text
    assert updated.json()["amount"] == 75
    cancelled = client.delete(path, headers=in_alpha)
    assert cancelled.status_code == 200, cancelled.text


# ---------------------------------------------------------------------------
# Numbering is per company
# ---------------------------------------------------------------------------

def test_each_company_numbers_its_documents_from_one(client, tenants, act_as):
    numbers = {}
    for user, tag in ((tenants.user_a, "A"), (tenants.user_b, "B")):
        act_as(user)
        ledger = _create_ledger(client, f"Numbering Customer {tag}")
        product = _create_product(client, f"NUM-{tag}")
        invoice = _create_invoice(client, ledger, product)
        credit_note = _create_credit_note(client, ledger, invoice)
        numbers[tag] = (invoice["invoice_number"], credit_note["credit_note_number"])

    # A's fixture already used INV-...-001 and CN-...-001, so A is on 002 now;
    # B's first documents must still start at 001.
    assert numbers["B"][0].endswith("-001"), numbers
    assert numbers["B"][1].endswith("-001"), numbers


def test_two_companies_can_hold_identical_document_numbers(client, db_session, shared_hosting, act_as):
    user_a = _user(db_session, "alice@alpha.example")
    user_b = _user(db_session, "bob@beta.example")

    numbers = []
    for user, tag in ((user_a, "A"), (user_b, "B")):
        act_as(user)
        _create_company(client, f"Company {tag}")
        ledger = _create_ledger(client, f"Customer {tag}")
        product = _create_product(client, f"SKU-{tag}")
        invoice = _create_invoice(client, ledger, product)
        credit_note = _create_credit_note(client, ledger, invoice)
        numbers.append((invoice["invoice_number"], credit_note["credit_note_number"]))

    (inv_a, cn_a), (inv_b, cn_b) = numbers
    assert inv_a.endswith("-001") and cn_a.endswith("-001"), numbers
    assert (inv_a, cn_a) == (inv_b, cn_b)


# ---------------------------------------------------------------------------
# Single tenant keeps its old fallback
# ---------------------------------------------------------------------------

def test_single_tenant_user_without_membership_gets_the_first_company(client, db_session, act_as):
    assert settings.DEPLOYMENT_MODE == "single_tenant"
    company = CompanyProfile(name="The Only Company", address="", gst="", phone_number="")
    db_session.add(company)
    db_session.commit()
    user = _user(db_session, "solo@example.com")

    act_as(user)
    assert _ok(client.get("/api/company/"))["id"] == company.id
    assert [c["id"] for c in _ok(client.get("/api/company/companies"))] == [company.id]


# ---------------------------------------------------------------------------
# MCP admin scope follows the role in the company granted
# ---------------------------------------------------------------------------

def test_oauth_admin_scope_follows_the_membership_role(db_session, tenants):
    from src.api.routes.oauth import _filter_scopes_to_user
    from src.services.oauth.tokens import SCOPE_ADMIN

    gamma = CompanyProfile(name="Gamma Works", address="", gst="", phone_number="")
    db_session.add(gamma)
    db_session.commit()
    add_membership(db_session, tenants.user_a, gamma, UserRole.staff)
    db_session.commit()
    requested = ["invoicing:read", SCOPE_ADMIN]

    # Global staff, but admin of the company they created.
    assert tenants.user_a.role == UserRole.staff
    assert SCOPE_ADMIN in _filter_scopes_to_user(db_session, requested, tenants.user_a, tenants.company_a)
    # Only staff here, so the grant for this company must not carry it.
    assert SCOPE_ADMIN not in _filter_scopes_to_user(db_session, requested, tenants.user_a, gamma.id)
    # And nothing at all in a company they are not part of.
    assert SCOPE_ADMIN not in _filter_scopes_to_user(db_session, requested, tenants.user_a, tenants.company_b)
    # The consent screen, before a company is picked: admin somewhere is enough to offer it.
    assert SCOPE_ADMIN in _filter_scopes_to_user(db_session, requested, tenants.user_a)
    assert SCOPE_ADMIN not in _filter_scopes_to_user(db_session, requested, tenants.user_c)

    # A global admin gains nothing where their membership is only staff.
    tenants.user_a.role = UserRole.admin
    db_session.commit()
    assert SCOPE_ADMIN not in _filter_scopes_to_user(db_session, requested, tenants.user_a, gamma.id)
