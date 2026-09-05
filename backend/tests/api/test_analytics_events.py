"""Product events fire from the route handlers, not from the browser.

One test per shape rather than one per event: that the handler captures at all,
that a failed action captures its own event, that the browser's replay session
reaches the event, and that an unreachable PostHog cannot fail a request.
"""

import pytest

from src.core import analytics
from src.core.security import get_password_hash
from src.models.user import User, UserRole


class RecordingClient:
    def __init__(self):
        self.captured = []

    def capture(self, event, distinct_id=None, properties=None, disable_geoip=None):
        self.captured.append((event, distinct_id, properties or {}))

    def set(self, distinct_id=None, properties=None):
        pass

    def capture_exception(self, exc, distinct_id=None, properties=None, disable_geoip=None):
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


def _seed_user(db, email: str = "operator@example.com", password: str = "GoodPass@123") -> User:
    user = User(
        email=email,
        full_name="Operator",
        role=UserRole.admin,
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _find(events, name):
    return [e for e in events.captured if e[0] == name]


def test_login_captures_user_logged_in(client, db_session, events):
    _seed_user(db_session)

    response = client.post(
        "/api/auth/login",
        json={"email": "operator@example.com", "password": "GoodPass@123"},
    )

    assert response.status_code == 200
    (_, distinct_id, props), = _find(events, "user_logged_in")
    assert distinct_id == "operator@example.com"
    assert props["$set"]["role"] == "admin"


def test_wrong_password_captures_login_failed(client, db_session, events):
    _seed_user(db_session)

    response = client.post(
        "/api/auth/login",
        json={"email": "operator@example.com", "password": "WrongPass@000"},
    )

    assert response.status_code == 401
    (_, distinct_id, props), = _find(events, "login_failed")
    assert distinct_id == "operator@example.com"
    assert props["reason"] == "bad_password"
    # The account exists, so the person it belongs to is a real one.
    assert "$process_person_profile" not in props


def test_unknown_email_does_not_mint_a_person(client, db_session, events):
    response = client.post(
        "/api/auth/login",
        json={"email": "stranger@example.com", "password": "Whatever@123"},
    )

    assert response.status_code == 401
    (_, _, props), = _find(events, "login_failed")
    assert props["reason"] == "unknown_email"
    assert props["$process_person_profile"] is False


def test_session_header_lands_on_the_event(client, db_session, events):
    _seed_user(db_session)

    client.post(
        "/api/auth/login",
        json={"email": "operator@example.com", "password": "GoodPass@123"},
        headers={"X-PostHog-Session-Id": "session-abc"},
    )

    (_, _, props), = _find(events, "user_logged_in")
    # Without this the event and the browser's recording never line up.
    assert props["$session_id"] == "session-abc"
    assert props["client"] == "web"


def test_a_call_with_no_session_header_is_not_web(client, db_session, events):
    _seed_user(db_session)

    client.post(
        "/api/auth/login",
        json={"email": "operator@example.com", "password": "GoodPass@123"},
    )

    (_, _, props), = _find(events, "user_logged_in")
    assert props["client"] == "api"
    assert "$session_id" not in props


def test_a_broken_posthog_does_not_fail_the_request(client, db_session, monkeypatch):
    class ExplodingClient(RecordingClient):
        def capture(self, *args, **kwargs):
            raise RuntimeError("ingestion unreachable")

    monkeypatch.setattr(analytics, "_client", ExplodingClient())
    monkeypatch.setattr(analytics, "_init_attempted", True)
    _seed_user(db_session)

    response = client.post(
        "/api/auth/login",
        json={"email": "operator@example.com", "password": "GoodPass@123"},
    )

    assert response.status_code == 200


def test_logout_is_counted_on_the_server(client, events):
    response = client.post("/api/auth/logout")

    assert response.status_code == 204
    # conftest overrides the auth dependency with test@example.com.
    (_, distinct_id, _), = _find(events, "user_logged_out")
    assert distinct_id == "test@example.com"


# ---------------------------------------------------------------------------
# Public share pages
#
# These are read by the tenant's customer, who has no account here. The events
# must therefore be anonymous, must never carry the token, and must not change
# what any of these pages actually serve.
# ---------------------------------------------------------------------------

from decimal import Decimal

from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product


def _share_company(db) -> CompanyProfile:
    company = CompanyProfile(
        name="Alpha Ltd",
        address="1 Test Road",
        gst="27AAAAA0000A1Z5",
        phone_number="+91 9000000000",
        currency_code="INR",
        email="owner@example.com",
        website="",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _share_invoice(db, company: CompanyProfile) -> Invoice:
    ledger = Ledger(
        company_id=company.id,
        name="Acme Traders",
        address="9 Buyer Lane",
        gst="27BBBBB0000B1Z5",
        phone_number="+91 9111111111",
    )
    db.add(ledger)
    product = Product(
        company_id=company.id,
        sku="SKU-SHARE",
        name="Widget",
        price=Decimal("100.00"),
        gst_rate=Decimal("18.00"),
    )
    db.add(product)
    db.commit()

    invoice = Invoice(
        company_id=company.id,
        ledger_id=ledger.id,
        invoice_number="INV-0042",
        total_amount=Decimal("118.00"),
        taxable_amount=Decimal("100.00"),
        total_tax_amount=Decimal("18.00"),
        created_by=1,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    db.add(
        InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("100.00"),
            gst_rate=Decimal("18.00"),
            taxable_amount=Decimal("100.00"),
            tax_amount=Decimal("18.00"),
            line_total=Decimal("118.00"),
        )
    )
    db.commit()
    db.refresh(invoice)
    return invoice


def _share_token(client, company, invoice) -> str:
    response = client.post(
        "/api/share/",
        json={"resource_type": "invoice", "resource_id": invoice.id},
        headers={"X-Company-Id": str(company.id)},
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_opening_a_share_page_is_counted(client, db_session, events):
    company = _share_company(db_session)
    invoice = _share_invoice(db_session, company)
    token = _share_token(client, company, invoice)

    assert client.get(f"/s/{token}").status_code == 200

    (_, group_key, props), = _find(events, "share_page_viewed")
    assert props["resource_type"] == "invoice"
    assert props["company_id"] == company.id
    assert props["view_count"] == 1
    assert props["is_first_view"] is True
    # The reader is a customer, not a user: no person profile is created for them.
    assert props["$process_person_profile"] is False
    assert group_key == f"share_link:{props['share_link_id']}"


def test_the_real_url_is_sent_token_and_all(client, db_session, events):
    """A deliberate trade, recorded here so it cannot be made by accident.

    The URL goes out whole so a link can be opened straight from PostHog. The
    token is the entire credential for the document, so this makes read access to
    the PostHog project equivalent to read access to every shared document. If
    that stops being acceptable, this test is the thing to flip.
    """
    company = _share_company(db_session)
    invoice = _share_invoice(db_session, company)
    token = _share_token(client, company, invoice)

    client.get(f"/s/{token}")
    client.get(f"/s/{token}/pdf?download=1")

    (_, _, page), = _find(events, "share_page_viewed")
    (_, _, pdf), = _find(events, "share_pdf_downloaded")

    assert page["$pathname"] == f"/s/{token}"
    assert page["$current_url"].endswith(f"/s/{token}")
    assert pdf["$pathname"] == f"/s/{token}/pdf"

    # The distinct id stays the link's numeric id: it groups a link's events
    # without the token becoming an identity PostHog indexes people by.
    for _, group_key, _ in events.captured:
        assert token not in group_key


def test_a_chat_apps_preview_fetch_is_not_a_visit(client, db_session, events):
    company = _share_company(db_session)
    invoice = _share_invoice(db_session, company)
    token = _share_token(client, company, invoice)

    client.get(f"/s/{token}", headers={"User-Agent": "WhatsApp/2.23"})

    # Counting these would make "opened 3 times" mean "forwarded to 3 chats".
    assert _find(events, "share_page_viewed") == []


def test_downloading_the_pdf_is_counted_separately_from_viewing_it(
    client, db_session, events
):
    company = _share_company(db_session)
    invoice = _share_invoice(db_session, company)
    token = _share_token(client, company, invoice)

    client.get(f"/s/{token}/pdf?download=1")
    client.get(f"/s/{token}/pdf")

    dispositions = [props["disposition"] for _, _, props in _find(events, "share_pdf_downloaded")]
    assert dispositions == ["attachment", "inline"]


def test_the_whatsapp_button_counts_and_then_redirects(client, db_session, events):
    company = _share_company(db_session)
    invoice = _share_invoice(db_session, company)
    token = _share_token(client, company, invoice)

    response = client.get(f"/s/{token}/whatsapp", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://wa.me/")
    (_, _, props), = _find(events, "share_whatsapp_clicked")
    assert props["placement"] == "invoice"


def test_the_whatsapp_button_still_works_on_a_dead_link(client, db_session, events):
    """The CTA on the dead-link page must not 404 just because the link is gone."""
    response = client.get("/s/-/whatsapp", follow_redirects=False)

    assert response.status_code == 302
    (_, group_key, props), = _find(events, "share_whatsapp_clicked")
    assert props["placement"] == "unavailable"
    assert group_key == "share_link:unresolved"


def test_a_miss_is_counted_without_naming_the_document(client, db_session, events):
    client.get("/s/thistokenwasnevermintedatall00")

    (_, _, props), = _find(events, "share_link_unavailable")
    assert props["reason"] == "unresolved"
    assert "share_link_id" not in props


def test_share_route_collapses_the_token_for_grouping(client, db_session, events):
    """The property to break down by.

    The raw URL is one row per link, which answers a question nobody asked;
    `share_route` is one row per kind of page, which is the one people want.
    """
    company = _share_company(db_session)
    invoice = _share_invoice(db_session, company)
    token = _share_token(client, company, invoice)

    client.get(f"/s/{token}")
    client.get(f"/s/{token}/pdf?download=1")

    (_, _, page), = _find(events, "share_page_viewed")
    (_, _, pdf), = _find(events, "share_pdf_downloaded")

    assert page["share_route"] == "/s/:token"
    assert pdf["share_route"] == "/s/:token/pdf"
    assert page["$host"] == "testserver"


def test_the_second_mount_is_visible_in_the_route(client, db_session, events):
    """/s and /api/s both serve these pages; which one was reached matters."""
    company = _share_company(db_session)
    invoice = _share_invoice(db_session, company)
    token = _share_token(client, company, invoice)

    client.get(f"/api/s/{token}")

    (_, _, props), = _find(events, "share_page_viewed")
    assert props["share_route"] == "/api/s/:token"
    assert props["$pathname"] == f"/api/s/{token}"


def test_a_miss_reports_the_url_that_was_tried(client, db_session, events):
    """A guessed token is worth seeing -- it is what a scan looks like."""
    client.get("/s/thistokenwasnevermintedatall00")

    (_, _, props), = _find(events, "share_link_unavailable")
    assert props["share_route"] == "/s/:token"
    assert props["$pathname"] == "/s/thistokenwasnevermintedatall00"


def test_a_share_view_is_located_by_the_forwarded_client_ip(
    client, db_session, events
):
    """End to end: the middleware binds the caller's IP and the event carries it."""
    company = _share_company(db_session)
    invoice = _share_invoice(db_session, company)
    token = _share_token(client, company, invoice)

    client.get(f"/s/{token}", headers={"X-Forwarded-For": "49.36.183.12, 10.0.0.1"})

    (_, _, props), = _find(events, "share_page_viewed")
    # The reader's address, not the ingress hop's and not this pod's.
    assert props["$ip"] == "49.36.183.12"
