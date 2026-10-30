"""Postgres row-level security, proven as a role shaped like production's invoicing_app.

Two tenants, A and B, are created end to end through the FastAPI app with every
request served by a session on the restricted role (tests/db/conftest.py). Then
raw SQL on that role shows what the database itself enforces, independent of
any application filter:

- with app.company_id = A, every protected table returns only A's rows;
- a row for B cannot be written while acting for A (WITH CHECK);
- with no context at all, nothing is visible;
- the context survives a mid-request commit (the after_begin hook);
- a pooled connection handed to the next request carries no tenant id;
- a public share link resolves with no signed-in user, and only to its company;
- the shared-hosting boot check accepts this role and refuses an unsafe one.

Skipped when DATABASE_URL is not Postgres.
"""

import sys
from pathlib import Path

import pytest
from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.core.config import settings
from src.db.rls import (
    CHILD_TABLES,
    DIRECT_TABLES,
    app_role_problems,
    check_app_role_or_raise,
    protected_tables,
)
from src.db.session import get_db
from src.db.tenant_context import get_tenant_context, set_tenant_context
from src.models.user import User
from src.services.share_documents import resolve_share_link

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import test_tenant_isolation as iso  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="row-level security needs Postgres",
)


# ---------------------------------------------------------------------------
# The app, served by the restricted role
# ---------------------------------------------------------------------------

@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", 3)
    monkeypatch.setattr(settings, "SHARE_LINKS_ENABLED", True)


@pytest.fixture
def restricted_app(clean_rls_db, shared):
    """Every request's get_db session is on the restricted role."""

    def _get_db():
        db = clean_rls_db.AppSession()
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
def act_as():
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
        app.dependency_overrides[get_current_user] = previous


def _seed_tenant(client, act_as, user, name: str, sku: str) -> dict:
    act_as(user)
    company = iso._create_company(client, name)
    ledger = iso._create_ledger(client, f"{name} Customer")
    product = iso._create_product(client, sku)
    invoice = iso._create_invoice(client, ledger, product)
    payment = iso._ok(client.post("/api/payments/", json={
        "ledger_id": ledger,
        "voucher_type": "receipt",
        "amount": 50,
        "mode": "cash",
        "invoice_allocations": [{"invoice_id": invoice["id"], "allocated_amount": 50}],
    }))
    credit_note = iso._create_credit_note(client, ledger, invoice)
    share = iso._ok(client.post("/api/share/", json={"resource_type": "invoice", "resource_id": invoice["id"]}))
    return {
        "company": company,
        "ledger": ledger,
        "product": product,
        "invoice": invoice,
        "payment": payment,
        "credit_note": credit_note,
        "share": share,
    }


@pytest.fixture
def two_tenants(client, restricted_app, act_as):
    with restricted_app.OwnerSession() as owner:
        user_a = iso._user(owner, "alice@alpha.example")
        user_b = iso._user(owner, "bob@beta.example")
        owner.expunge_all()
    a = _seed_tenant(client, act_as, user_a, "Alpha Traders", "ALPHA-1")
    b = _seed_tenant(client, act_as, user_b, "Beta Stores", "BETA-1")
    return restricted_app, a, b


def _token(share: dict) -> str:
    return share["token"]


# ---------------------------------------------------------------------------
# Raw SQL as the restricted role
# ---------------------------------------------------------------------------

def _as_app(db, company_id=None):
    """A raw connection on the restricted role with app.company_id set (or not)."""
    conn = db.app_engine.connect()
    conn.begin()
    if company_id is not None:
        conn.execute(text("SELECT set_config('app.company_id', :c, true)"), {"c": str(company_id)})
    return conn


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def _owner_count(db, sql: str, **params) -> int:
    with db.owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


BUSINESS_TABLES = [
    "invoices", "invoice_items", "buyers", "products", "inventory", "payments",
    "payment_invoice_allocations", "credit_notes", "credit_note_items",
    "credit_note_invoice_refs", "financial_years", "invoice_series", "share_links",
]


def test_the_seed_really_wrote_both_tenants(two_tenants):
    db, a, b = two_tenants
    for table in BUSINESS_TABLES:
        assert _owner_count(db, f"SELECT count(*) FROM {table}") >= 2, table


@pytest.mark.parametrize("table", BUSINESS_TABLES)
def test_acting_for_a_shows_only_a(two_tenants, table):
    db, a, b = two_tenants
    total = _owner_count(db, f"SELECT count(*) FROM {table}")
    conn = _as_app(db, a["company"])
    try:
        visible = _count(conn, table)
        if table in DIRECT_TABLES or table == "share_links":
            assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE company_id <> :a"), {"a": a["company"]}).scalar() == 0
        else:
            fk, parent = CHILD_TABLES[table]
            leaked = conn.execute(text(
                f"SELECT count(*) FROM {table} t JOIN {parent} p ON p.id = t.{fk} WHERE p.company_id <> :a"
            ), {"a": a["company"]}).scalar()
            assert leaked == 0
    finally:
        conn.close()
    assert 0 < visible < total, (table, visible, total)


def test_select_star_from_invoices_returns_only_a(two_tenants):
    db, a, b = two_tenants
    conn = _as_app(db, a["company"])
    try:
        ids = {row.id for row in conn.execute(text("SELECT * FROM invoices"))}
    finally:
        conn.close()
    assert ids == {a["invoice"]["id"]}


def test_no_context_sees_nothing(two_tenants):
    db, _, _ = two_tenants
    conn = _as_app(db)
    try:
        for table in protected_tables():
            assert _count(conn, table) == 0, table
        # Platform tables are not RLS'd: sign-in still works with no tenant.
        assert _count(conn, "users") == 2
        assert _count(conn, "company_profiles") == 2
    finally:
        conn.close()


def test_writing_a_row_for_b_while_acting_for_a_is_refused(two_tenants):
    db, a, b = two_tenants
    conn = _as_app(db, a["company"])
    try:
        with pytest.raises(ProgrammingError, match="row-level security"):
            conn.execute(text(
                "INSERT INTO buyers (company_id, name, address, phone_number) "
                "VALUES (:b, 'Smuggled', 'x', '1')"
            ), {"b": b["company"]})
    finally:
        conn.close()

    conn = _as_app(db, a["company"])
    try:
        with pytest.raises(ProgrammingError, match="row-level security"):
            conn.execute(text("UPDATE products SET company_id = :b"), {"b": b["company"]})
    finally:
        conn.close()

    conn = _as_app(db, a["company"])
    try:
        # B's rows are not even there to change.
        changed = conn.execute(
            text("UPDATE invoices SET status = 'cancelled' WHERE id = :id"), {"id": b["invoice"]["id"]}
        ).rowcount
        assert changed == 0
        # Nor can an item be attached to B's invoice.
        with pytest.raises(ProgrammingError, match="row-level security"):
            conn.execute(text(
                "INSERT INTO invoice_items (invoice_id, product_id, quantity, unit_price, gst_rate, "
                "taxable_amount, tax_amount, cgst_amount, sgst_amount, igst_amount, line_total) "
                "VALUES (:inv, :prod, 1, 1, 0, 0, 0, 0, 0, 0, 1)"
            ), {"inv": b["invoice"]["id"], "prod": a["product"]})
    finally:
        conn.close()


def test_a_null_company_row_belongs_to_nobody(two_tenants):
    db, a, _ = two_tenants
    with db.owner_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO buyers (company_id, name, address, phone_number) VALUES (NULL, 'Orphan', 'x', '1')"
        ))
    conn = _as_app(db, a["company"])
    try:
        assert conn.execute(text("SELECT count(*) FROM buyers WHERE name = 'Orphan'")).scalar() == 0
        with pytest.raises(ProgrammingError, match="row-level security"):
            conn.execute(text(
                "INSERT INTO buyers (company_id, name, address, phone_number) VALUES (NULL, 'Orphan 2', 'x', '1')"
            ))
    finally:
        conn.close()


def test_api_key_lookup_admits_only_the_presented_prefix(two_tenants):
    from datetime import datetime, timedelta, timezone

    from src.models.api_key import ApiKey

    db, a, b = two_tenants
    with db.OwnerSession() as owner:
        user_ids = [row[0] for row in owner.execute(text("SELECT id FROM users ORDER BY id"))]
        for company, prefix, user_id in ((a["company"], "si_aaaaaaaaa", user_ids[0]), (b["company"], "si_bbbbbbbbb", user_ids[1])):
            owner.add(ApiKey(
                company_id=company, created_by_user_id=user_id, name="k", key_prefix=prefix,
                key_encrypted="x", expires_at=datetime.now(timezone.utc) + timedelta(days=1), is_active=True,
            ))
        owner.commit()
    conn = _as_app(db)
    try:
        assert _count(conn, "api_keys") == 0
        conn.execute(text("SELECT set_config('app.api_key_prefix', 'si_bbbbbbbbb', true)"))
        assert [r[0] for r in conn.execute(text("SELECT key_prefix FROM api_keys"))] == ["si_bbbbbbbbb"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The session hook
# ---------------------------------------------------------------------------

def _visible_invoice_companies(session) -> set[int]:
    return {row[0] for row in session.execute(text("SELECT DISTINCT company_id FROM invoices"))}


def test_context_survives_a_mid_request_commit(two_tenants):
    db, a, _ = two_tenants
    session = db.AppSession()
    try:
        set_tenant_context(session, company_id=a["company"])
        assert _visible_invoice_companies(session) == {a["company"]}
        session.commit()  # what handlers do in the middle of a request
        assert _visible_invoice_companies(session) == {a["company"]}
        session.rollback()
        assert _visible_invoice_companies(session) == {a["company"]}
    finally:
        session.close()


def test_context_set_mid_transaction_applies_at_once(two_tenants):
    db, a, b = two_tenants
    session = db.AppSession()
    try:
        assert _visible_invoice_companies(session) == set()
        set_tenant_context(session, company_id=a["company"])
        assert _visible_invoice_companies(session) == {a["company"]}
        set_tenant_context(session, company_id=b["company"])
        assert _visible_invoice_companies(session) == {b["company"]}
        set_tenant_context(session, company_id=None)
        assert _visible_invoice_companies(session) == set()
    finally:
        session.close()


def test_a_pooled_connection_does_not_carry_the_tenant_to_the_next_request(two_tenants):
    db, a, _ = two_tenants
    from sqlalchemy.orm import sessionmaker

    single = db.schema_engine(db.app_url, db.schema, pool_size=1, max_overflow=0)
    Factory = sessionmaker(bind=single)
    try:
        first = Factory()
        set_tenant_context(first, company_id=a["company"])
        first_pid = first.execute(text("SELECT pg_backend_pid()")).scalar()
        assert _visible_invoice_companies(first) == {a["company"]}
        first.commit()
        assert _visible_invoice_companies(first) == {a["company"]}  # re-applied after commit
        first.close()

        second = Factory()
        try:
            assert second.execute(text("SELECT pg_backend_pid()")).scalar() == first_pid
            assert get_tenant_context(second) == {}
            leftover = second.execute(text("SELECT current_setting('app.company_id', true)")).scalar()
            assert leftover in (None, "")
            assert _visible_invoice_companies(second) == set()
        finally:
            second.close()
    finally:
        single.dispose()


def test_hook_is_inert_in_single_tenant(two_tenants, monkeypatch):
    db, a, _ = two_tenants
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    session = db.AppSession()
    try:
        set_tenant_context(session, company_id=a["company"])
        assert session.execute(text("SELECT current_setting('app.company_id', true)")).scalar() in (None, "")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Public share links: no user, company from the link
# ---------------------------------------------------------------------------

def test_share_link_resolves_to_its_own_company_only(two_tenants):
    db, a, b = two_tenants
    session = db.AppSession()
    try:
        link = resolve_share_link(session, _token(a["share"]))
        assert link is not None and link.company_id == a["company"]
        assert _visible_invoice_companies(session) == {a["company"]}
        # Only that one link is visible, not A's others or B's.
        assert {row[0] for row in session.execute(text("SELECT token FROM share_links"))} == {_token(a["share"])}
        session.commit()
        assert _visible_invoice_companies(session) == {a["company"]}
    finally:
        session.close()

    session = db.AppSession()
    try:
        assert resolve_share_link(session, "not-a-real-token-at-all-000000000000") is None
        assert _visible_invoice_companies(session) == set()
    finally:
        session.close()


def test_public_share_page_renders_through_rls(two_tenants, client):
    db, a, b = two_tenants
    with iso._real_auth():
        page = client.get(f"/s/{_token(a['share'])}")
        assert page.status_code == 200, page.text
        assert a["invoice"]["invoice_number"] in page.text
        assert b["invoice"]["invoice_number"] not in page.text or (
            a["invoice"]["invoice_number"] == b["invoice"]["invoice_number"]
        )
        assert "Alpha Traders" in page.text and "Beta Stores" not in page.text
        pdf = client.get(f"/s/{_token(a['share'])}/pdf")
        assert pdf.status_code == 200, pdf.text[:200]
        assert client.get("/s/not-a-real-token-at-all-000000000000").status_code == 404


# ---------------------------------------------------------------------------
# End to end through the app
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/invoices/", "/api/ledgers/", "/api/products/", "/api/payments/",
    "/api/credit-notes/", "/api/financial-years/", "/api/invoice-series/", "/api/share/",
])
def test_lists_through_the_app_show_own_rows(two_tenants, client, act_as, path):
    db, a, b = two_tenants
    with db.OwnerSession() as owner:
        user_b = owner.query(User).filter(User.email == "bob@beta.example").one()
        owner.expunge(user_b)
    act_as(user_b)
    response = client.get(path)
    assert response.status_code == 200, response.text
    rows = response.json()
    rows = rows["items"] if isinstance(rows, dict) and "items" in rows else rows
    assert rows, f"B sees none of its own rows at {path}"
    assert all(row.get("company_id", b["company"]) == b["company"] for row in rows), rows


def test_api_key_works_through_rls(two_tenants, client, act_as):
    from datetime import datetime, timedelta, timezone

    db, a, _ = two_tenants
    with db.OwnerSession() as owner:
        user_a = owner.query(User).filter(User.email == "alice@alpha.example").one()
        owner.expunge(user_a)
    act_as(user_a)
    key = iso._ok(client.post("/api/api-keys/", json={
        "name": "Alpha key",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    }), 201)
    with iso._real_auth():
        listed = client.get("/api/ledgers/", headers={"Authorization": f"Bearer {key['raw_key']}"})
    assert listed.status_code == 200, listed.text
    assert iso._ids(listed.json()) == {a["ledger"]}
    # The lookup admitted only this key's prefix and then cleared it.
    with db.owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM api_keys")).scalar() == 1


def test_marketplace_drain_all_walks_each_company(two_tenants):
    from src.models.marketplace import MarketplaceConnection
    from src.services.marketplace import sync as sync_service

    db, a, b = two_tenants
    with db.OwnerSession() as owner:
        for company in (a["company"], b["company"]):
            # "connected" but with no credential: drain stops at not_connected
            # before any network call, which is all this test needs.
            owner.add(MarketplaceConnection(company_id=company, status="connected", base_url="https://m.example"))
        owner.commit()
    session = db.AppSession()
    try:
        results = sync_service.drain_all(session)
        assert sorted(r.company_id for r in results) == sorted([a["company"], b["company"]])
        assert get_tenant_context(session) == {}
        assert session.query(MarketplaceConnection).count() == 0
    finally:
        session.close()


# ---------------------------------------------------------------------------
# The shared-hosting boot check
# ---------------------------------------------------------------------------

def test_boot_check_accepts_the_restricted_role(clean_rls_db):
    with clean_rls_db.app_engine.connect() as conn:
        assert app_role_problems(conn) == []
        check_app_role_or_raise(conn)


def test_boot_check_refuses_a_superuser(clean_rls_db):
    with clean_rls_db.owner_engine.connect() as conn:
        problems = app_role_problems(conn)
        assert any("superuser" in p for p in problems), problems
        with pytest.raises(RuntimeError, match="Refusing to start"):
            check_app_role_or_raise(conn)


@pytest.mark.parametrize("break_it, fix_it, expect", [
    ('ALTER ROLE "{role}" BYPASSRLS', 'ALTER ROLE "{role}" NOBYPASSRLS', "BYPASSRLS"),
    ('ALTER TABLE products OWNER TO "{role}"', # Handing ownership back takes the role's own grants with it.
     "ALTER TABLE products OWNER TO CURRENT_USER; "
     'GRANT SELECT, INSERT, UPDATE, DELETE ON products TO "{role}"; '
     'GRANT USAGE, SELECT ON SEQUENCE products_id_seq TO "{role}"', "owns"),
    ('REVOKE USAGE ON SEQUENCE invoices_id_seq FROM "{role}"',
     'GRANT USAGE ON SEQUENCE invoices_id_seq TO "{role}"', "sequences"),
    ("ALTER TABLE invoices DISABLE ROW LEVEL SECURITY", "ALTER TABLE invoices ENABLE ROW LEVEL SECURITY", "not enabled"),
    ('REVOKE DELETE ON payments FROM "{role}"', 'GRANT DELETE ON payments TO "{role}"', "lacks"),
])
def test_boot_check_refuses_an_unsafe_role(clean_rls_db, break_it, fix_it, expect):
    db = clean_rls_db
    with db.owner_engine.begin() as conn:
        conn.execute(text(break_it.format(role=db.role)))
    try:
        fresh = db.schema_engine(db.app_url, db.schema)
        try:
            with fresh.connect() as conn:
                problems = app_role_problems(conn)
        finally:
            fresh.dispose()
        assert any(expect in p for p in problems), problems
    finally:
        with db.owner_engine.begin() as conn:
            conn.execute(text(fix_it.format(role=db.role)))


def test_policies_are_idempotent_and_never_forced(clean_rls_db):
    from src.db.rls import ensure_row_level_security

    with clean_rls_db.owner_engine.begin() as conn:
        assert ensure_row_level_security(conn) == []
        forced = conn.execute(text(
            "SELECT relname FROM pg_class WHERE relforcerowsecurity "
            "AND relnamespace = current_schema()::regnamespace"
        )).fetchall()
        assert forced == []
        covered = {r[0] for r in conn.execute(text(
            "SELECT relname FROM pg_class WHERE relrowsecurity AND relnamespace = current_schema()::regnamespace"
        ))}
    assert covered == set(protected_tables())


def test_every_company_scoped_table_is_covered_or_deliberately_excluded():
    """A new model with a company_id must be added to src/db/rls.py one way or the other."""
    import src.models  # noqa: F401
    from src.db.base import Base
    from src.db.rls import EXCLUDED_TABLES

    for table in Base.metadata.sorted_tables:
        if table.name in EXCLUDED_TABLES:
            continue
        assert table.name in protected_tables(), (
            f"{table.name} is neither protected nor listed in EXCLUDED_TABLES"
        )


# ---------------------------------------------------------------------------
# MCP: a real OAuth token, dispatched through the same deps as the web app
# ---------------------------------------------------------------------------

def test_mcp_tool_call_runs_inside_the_grants_company(two_tenants, client):
    import json

    from src.mcp_server import register_mcp
    from src.mcp_server.config import ALL_SCOPES
    from src.models.oauth import OAuthClient
    from src.services.oauth.tokens import mint_token

    register_mcp(app)
    db, a, b = two_tenants
    with db.OwnerSession() as owner:
        user_a = owner.query(User).filter(User.email == "alice@alpha.example").one()
        owner.add(OAuthClient(
            client_id="rls-client", client_name="RLS client",
            redirect_uris=json.dumps(["https://claude.ai/callback"]),
            grant_types="authorization_code refresh_token", response_types="code",
            scope=" ".join(ALL_SCOPES), token_endpoint_auth_method="none", is_active=True,
        ))
        owner.flush()
        raw, _ = mint_token(
            owner, token_type="access", client_id="rls-client", user_id=user_a.id,
            company_id=a["company"], scope=" ".join(ALL_SCOPES), resource=settings.MCP_RESOURCE_URI,
        )
        owner.commit()

    def call(name, arguments):
        response = client.post(
            "/mcp",
            content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": arguments}}),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {raw}"},
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]

    with iso._real_auth():
        ledgers = call("ledgers_list", {})
        assert ledgers["isError"] is False, ledgers
        assert {row["id"] for row in ledgers["structuredContent"]["items"]} == {a["ledger"]}
        invoices = call("invoices_list", {})
        assert invoices["isError"] is False, invoices
        assert {row["id"] for row in invoices["structuredContent"]["items"]} == {a["invoice"]["id"]}


def test_boot_secures_the_database_and_refuses_an_owner_app_role(clean_rls_db, shared, monkeypatch):
    import app_main

    monkeypatch.setattr(app_main, "migration_engine", clean_rls_db.owner_engine)
    monkeypatch.setattr(app_main, "engine", clean_rls_db.app_engine)
    app_main.secure_shared_hosting_database()  # the restricted role: boots

    monkeypatch.setattr(app_main, "engine", clean_rls_db.owner_engine)
    with pytest.raises(RuntimeError, match="superuser"):
        app_main.secure_shared_hosting_database()

    monkeypatch.setattr(settings, "RLS_BOOT_CHECK", False)
    app_main.secure_shared_hosting_database()  # the local-development escape hatch
