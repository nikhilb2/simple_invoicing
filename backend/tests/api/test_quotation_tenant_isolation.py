"""Tenant isolation for every quotation route and share link, in both deployment modes.

Runs here on SQLite through the app's own filters, and again on Postgres as the
RLS-constrained role from tests/db/test_quotation_rls_postgres.py, which collects
this module the way test_rls_tenant_isolation_postgres.py collects the main suite.
"""

from types import SimpleNamespace

import pytest
from test_tenant_isolation import (  # noqa: F401 -- fixtures
    _create_company,
    _create_invoice,
    _create_ledger,
    _create_product,
    _ids,
    _ok,
    _real_auth,
    _user,
    act_as,
    shared_hosting,
)

from src.api.routes.public_share import reset_rate_limits
from src.core.config import settings
from src.models.global_settings import GlobalSettings
from src.models.invoice import Invoice
from src.models.ledger_address import LedgerAddress
from src.models.quotation import Quotation, QuotationItem
from src.models.user import UserRole


def _quote_body(ledger: int, product: int, **extra) -> dict:
    return {"ledger_id": ledger, "items": [{"product_id": product, "quantity": 1, "unit_price": 100}], **extra}


@pytest.fixture(autouse=True)
def _share_on(monkeypatch):
    monkeypatch.setattr(settings, "SHARE_LINKS_ENABLED", True)
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def two(client, db_session, shared_hosting, act_as):  # noqa: F811
    """A and B each hold a quotation; B also has its own ledger and product."""
    user_a = _user(db_session, "alice@alpha.example")
    user_b = _user(db_session, "bob@beta.example")

    act_as(user_b)
    company_b = _create_company(client, "Beta Stores")
    ledger_b = _create_ledger(client, "Beta Customer")
    product_b = _create_product(client, "BETA-1")
    quote_b = _ok(client.post("/api/quotations/", json=_quote_body(ledger_b, product_b)))

    act_as(user_a)
    company_a = _create_company(client, "Alpha Traders")
    ledger_a = _create_ledger(client, "Alpha Customer")
    product_a = _create_product(client, "ALPHA-1")
    quote_a = _ok(client.post("/api/quotations/", json=_quote_body(ledger_a, product_a)))
    proforma_a = _ok(client.post("/api/quotations/", json=_quote_body(ledger_a, product_a, document_type="proforma")))
    share_a = _ok(client.post("/api/share/", json={"resource_type": "quotation", "resource_id": quote_a["id"]}))

    return SimpleNamespace(
        user_a=user_a, user_b=user_b,
        company_a=company_a, company_b=company_b,
        ledger_a=ledger_a, ledger_b=ledger_b,
        product_a=product_a, product_b=product_b,
        quote_a=quote_a, quote_b=quote_b, proforma_a=proforma_a, share_a=share_a,
    )


def _token(share: dict) -> str:
    return share["token"]


def test_numbering_starts_afresh_in_each_company(two):
    assert two.quote_a["quotation_number"] == two.quote_b["quotation_number"]
    assert two.quote_a["id"] != two.quote_b["id"]


def test_list_shows_only_own_quotations(client, two, act_as):  # noqa: F811
    act_as(two.user_a)
    assert _ids(_ok(client.get("/api/quotations/"))) == {two.quote_a["id"], two.proforma_a["id"]}
    act_as(two.user_b)
    assert _ids(_ok(client.get("/api/quotations/"))) == {two.quote_b["id"]}
    counts = _ok(client.get("/api/quotations/"))["status_counts"]
    assert counts == {"open": 1}


def test_search_does_not_reach_the_other_tenant(client, two, act_as):  # noqa: F811
    act_as(two.user_b)
    assert _ok(client.get("/api/quotations/", params={"search": "Alpha Customer"}))["total"] == 0


@pytest.mark.parametrize("method, suffix, body", [
    ("get", "", None),
    ("get", "/pdf", None),
    ("get", "/conversion-draft", None),
    ("put", "", "update"),
    ("post", "/status", {"status": "accepted"}),
    ("post", "/cancel", None),
    ("post", "/duplicate", None),
    ("post", "/convert", "invoice"),
])
def test_every_route_answers_404_for_the_other_tenants_quotation(client, db_session, two, act_as, method, suffix, body):  # noqa: F811
    act_as(two.user_b)
    if body == "update":
        body = _quote_body(two.ledger_b, two.product_b)
    elif body == "invoice":
        body = {
            "ledger_id": two.ledger_b,
            "voucher_type": "sales",
            "items": [{"product_id": two.product_b, "quantity": 1, "unit_price": 100}],
        }
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(f"/api/quotations/{two.quote_a['id']}{suffix}", **kwargs)
    assert response.status_code == 404, response.text
    assert "Alpha" not in response.text

    # Not merely hidden: nothing happened to it.
    db_session.expire_all()
    row = db_session.query(Quotation).filter(Quotation.id == two.quote_a["id"]).one()
    assert row.status == "open"
    assert row.total_amount == pytest.approx(two.quote_a["total_amount"])
    assert db_session.query(Invoice).filter(Invoice.source_quotation_id == row.id).count() == 0


def test_quotation_cannot_use_the_other_tenants_ledger_or_product(client, two, act_as):  # noqa: F811
    act_as(two.user_b)
    other_ledger = client.post("/api/quotations/", json=_quote_body(two.ledger_a, two.product_b))
    assert other_ledger.status_code == 404
    other_product = client.post("/api/quotations/", json=_quote_body(two.ledger_b, two.product_a))
    assert other_product.status_code == 404
    edit = client.put(f"/api/quotations/{two.quote_b['id']}", json=_quote_body(two.ledger_a, two.product_b))
    assert edit.status_code == 404


def test_quotation_cannot_use_the_other_tenants_shipping_address(client, db_session, two, act_as):  # noqa: F811
    act_as(two.user_a)
    address = _ok(client.post(
        f"/api/ledgers/{two.ledger_a}/addresses/",
        json={"label": "Warehouse", "address": "Alpha Dock"},
    ), 201)
    act_as(two.user_b)
    response = client.post("/api/quotations/", json=_quote_body(
        two.ledger_b, two.product_b,
        shipping_address_same_as_billing=False,
        shipping_address_id=address["id"],
    ))
    assert response.status_code == 404
    assert "Alpha Dock" not in response.text
    assert db_session.query(LedgerAddress).count() == 1


def test_conversion_cannot_post_to_the_other_tenants_ledger(client, db_session, two, act_as):  # noqa: F811
    act_as(two.user_b)
    response = client.post(f"/api/quotations/{two.quote_b['id']}/convert", json={
        "ledger_id": two.ledger_a,
        "voucher_type": "sales",
        "items": [{"product_id": two.product_b, "quantity": 1, "unit_price": 100}],
    })
    assert response.status_code == 404
    db_session.expire_all()
    assert db_session.query(Quotation).filter(Quotation.id == two.quote_b["id"]).one().status == "open"


def test_conversion_within_a_company_works(client, db_session, two, act_as):  # noqa: F811
    act_as(two.user_b)
    draft = _ok(client.get(f"/api/quotations/{two.quote_b['id']}/conversion-draft"))
    invoice = _ok(client.post(f"/api/quotations/{two.quote_b['id']}/convert", json=draft["invoice"]))
    assert invoice["source_quotation_id"] == two.quote_b["id"]
    assert invoice["source_quotation_number"] == two.quote_b["quotation_number"]

    # Cancel and restore hooks stay in the company too.
    _ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert _ok(client.get(f"/api/quotations/{two.quote_b['id']}"))["status"] == "open"
    _ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert _ok(client.get(f"/api/quotations/{two.quote_b['id']}"))["status"] == "converted"

    # And the other tenant's quotation never moved.
    db_session.expire_all()
    assert db_session.query(Quotation).filter(Quotation.id == two.quote_a["id"]).one().status == "open"


def test_delete_guards_see_only_their_own_company(client, two, act_as):  # noqa: F811
    act_as(two.user_b)
    assert client.delete(f"/api/products/{two.product_b}").status_code == 400
    assert client.delete(f"/api/ledgers/{two.ledger_b}").status_code == 400
    # A fresh product of B's is not held back by A's quotations.
    fresh = _create_product(client, "BETA-FRESH")
    assert client.delete(f"/api/products/{fresh}").status_code == 200


def test_share_link_cannot_be_minted_for_the_other_tenants_quotation(client, two, act_as):  # noqa: F811
    act_as(two.user_b)
    response = client.post("/api/share/", json={"resource_type": "quotation", "resource_id": two.quote_a["id"]})
    assert response.status_code == 404


def test_public_link_serves_only_its_own_company(client, two, act_as):  # noqa: F811
    with _real_auth():
        page = client.get(f"/s/{_token(two.share_a)}")
        assert page.status_code == 200
        assert "Alpha" in page.text
        assert "Beta" not in page.text
        pdf = client.get(f"/s/{_token(two.share_a)}/pdf")
        assert pdf.status_code == 200
        document = client.get(f"/s/{_token(two.share_a)}/document.html")
        assert document.status_code == 200
        assert "Alpha Traders" in document.text and "Beta Stores" not in document.text
        assert client.get("/s/not-a-real-token-at-all-000000000000").status_code == 404


def test_public_link_cannot_be_repointed_across_companies(client, db_session, two):
    """A link whose resource id names another company's row must not resolve to it."""
    from src.models.share_link import ShareLink

    link = db_session.query(ShareLink).filter(ShareLink.token == _token(two.share_a)).one()
    link.resource_id = two.quote_b["id"]
    db_session.commit()
    with _real_auth():
        assert client.get(f"/s/{_token(two.share_a)}").status_code == 404
        assert client.get(f"/s/{_token(two.share_a)}/pdf").status_code == 404
        assert client.get(f"/s/{_token(two.share_a)}/document.html").status_code == 404


# ---------------------------------------------------------------------------
# Single tenant: the other deployment mode, same routes
# ---------------------------------------------------------------------------

@pytest.fixture
def single_tenant(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")


@pytest.fixture
def two_companies(client, db_session, single_tenant, act_as):  # noqa: F811
    """One owner, two companies: a single-tenant deployment still keeps them apart."""
    owner = _user(db_session, "owner@acme.example", role=UserRole.admin)
    settings_row = db_session.query(GlobalSettings).first()
    if settings_row is None:
        settings_row = GlobalSettings()
        db_session.add(settings_row)
    settings_row.max_companies = 5
    db_session.commit()
    act_as(owner)
    company_a = _create_company(client, "Alpha Traders")
    company_b = _create_company(client, "Beta Stores")

    def seed(company_id: int, name: str, sku: str, gst: str) -> dict:
        headers = {"X-Company-Id": str(company_id)}
        ledger = _ok(client.post("/api/ledgers/", headers=headers, json={
            "name": name, "address": "1 Road", "gst": gst, "opening_balance": None,
            "phone_number": "9000000000", "email": "", "website": "", "bank_name": "",
            "branch_name": "", "account_name": "", "account_number": "", "ifsc_code": "",
        }))["id"]
        product = _ok(client.post("/api/products/", headers=headers, json={
            "sku": sku, "name": f"Widget {sku}", "price": 100, "gst_rate": 18,
            "maintain_inventory": True, "initial_quantity": 100,
        }))["id"]
        quote = _ok(client.post("/api/quotations/", headers=headers, json=_quote_body(ledger, product)))
        return {"headers": headers, "ledger": ledger, "product": product, "quote": quote, "company": company_id}

    return SimpleNamespace(
        a=seed(company_a, "Alpha Customer", "ALPHA-1", "27AADCB2230M1ZT"),
        b=seed(company_b, "Beta Customer", "BETA-1", "29AADCB2230M1ZP"),
    )


def test_single_tenant_list_shows_only_the_active_company(client, two_companies):
    a, b = two_companies.a, two_companies.b
    assert _ids(_ok(client.get("/api/quotations/", headers=a["headers"]))) == {a["quote"]["id"]}
    assert _ids(_ok(client.get("/api/quotations/", headers=b["headers"]))) == {b["quote"]["id"]}


@pytest.mark.parametrize("method, suffix, body", [
    ("get", "", None),
    ("get", "/pdf", None),
    ("get", "/conversion-draft", None),
    ("put", "", "update"),
    ("post", "/status", {"status": "accepted"}),
    ("post", "/cancel", None),
    ("post", "/duplicate", None),
    ("post", "/convert", "invoice"),
])
def test_single_tenant_every_route_stops_at_the_company(client, db_session, two_companies, method, suffix, body):
    a, b = two_companies.a, two_companies.b
    if body == "update":
        body = _quote_body(b["ledger"], b["product"])
    elif body == "invoice":
        body = {
            "ledger_id": b["ledger"],
            "voucher_type": "sales",
            "items": [{"product_id": b["product"], "quantity": 1, "unit_price": 100}],
        }
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(
        f"/api/quotations/{a['quote']['id']}{suffix}", headers=b["headers"], **kwargs
    )
    assert response.status_code == 404, response.text

    db_session.expire_all()
    assert db_session.query(Quotation).filter(Quotation.id == a["quote"]["id"]).one().status == "open"
    assert db_session.query(Invoice).filter(Invoice.source_quotation_id == a["quote"]["id"]).count() == 0


def test_single_tenant_cannot_cross_companies_on_ledger_product_or_share(client, two_companies):
    a, b = two_companies.a, two_companies.b
    crossed_ledger = client.post("/api/quotations/", headers=b["headers"], json=_quote_body(a["ledger"], b["product"]))
    assert crossed_ledger.status_code == 404
    crossed_product = client.post("/api/quotations/", headers=b["headers"], json=_quote_body(b["ledger"], a["product"]))
    assert crossed_product.status_code == 404
    share = client.post(
        "/api/share/",
        headers=b["headers"],
        json={"resource_type": "quotation", "resource_id": a["quote"]["id"]},
    )
    assert share.status_code == 404


def test_single_tenant_public_link_serves_only_its_own_company(client, two_companies):
    a = two_companies.a
    share = _ok(client.post(
        "/api/share/",
        headers=a["headers"],
        json={"resource_type": "quotation", "resource_id": a["quote"]["id"]},
    ))
    with _real_auth():
        page = client.get(f"/s/{share['token']}")
        assert page.status_code == 200
        assert "Alpha Traders" in page.text and "Beta Stores" not in page.text
        assert client.get(f"/s/{share['token']}/pdf").status_code == 200


def test_single_tenant_every_route_works_and_a_public_link_serves_it(client, db_session, single_tenant, act_as):  # noqa: F811
    from quotation_helpers import create_ledger, create_product, seed_company

    user = _user(db_session, "owner@acme.example", role=UserRole.admin)
    act_as(user)
    seed_company(client)
    ledger = create_ledger(client)["id"]
    product = create_product(client)["id"]

    quote = _ok(client.post("/api/quotations/", json=_quote_body(ledger, product)))
    assert _ids(_ok(client.get("/api/quotations/"))) == {quote["id"]}
    assert _ok(client.get(f"/api/quotations/{quote['id']}"))["id"] == quote["id"]
    _ok(client.put(f"/api/quotations/{quote['id']}", json=_quote_body(ledger, product)))
    _ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "accepted"}))
    assert client.get(f"/api/quotations/{quote['id']}/pdf").status_code == 200
    copy = _ok(client.post(f"/api/quotations/{quote['id']}/duplicate"))
    _ok(client.post(f"/api/quotations/{copy['id']}/cancel"))
    share = _ok(client.post("/api/share/", json={"resource_type": "quotation", "resource_id": quote["id"]}))
    with _real_auth():
        assert client.get(f"/s/{share['token']}").status_code == 200
    draft = _ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    _ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"]))

    assert db_session.query(QuotationItem).count() == 2
