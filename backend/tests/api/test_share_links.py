"""Public share links: minting, revocation, tenant isolation, and the public page.

The security assertions here are the point of the file. A share token is an
unauthenticated credential printed into a WhatsApp message; the tests that matter
are the ones that would catch someone accidentally widening what it reaches.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app_main import app
from src.api.routes.public_share import reset_rate_limits
from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.invoice import Invoice, InvoiceItem
from src.models.payment import Payment
from src.models.product import Product
from src.models.share_link import ShareLink
from src.models.user import User, UserRole


@pytest.fixture(autouse=True)
def _clean_rate_limits():
    # The token buckets are module-level state; without this a long test file
    # starts failing halfway through for reasons that look nothing like the cause.
    reset_rate_limits()
    yield
    reset_rate_limits()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _company(db, name: str) -> CompanyProfile:
    company = CompanyProfile(
        name=name,
        address="1 Test Road",
        gst="27AAAAA0000A1Z5",
        phone_number="+91 9000000000",
        currency_code="INR",
        email="owner@example.com",
        website="",
        logo_data="aGVsbG8=",  # base64("hello") — enough to exercise the logo route
        logo_mime_type="image/png",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _user(db) -> User:
    user = db.query(User).filter(User.email == "owner@example.com").first()
    if user:
        return user
    user = User(
        email="owner@example.com",
        full_name="Owner",
        hashed_password="x",
        role=UserRole.admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _ledger(db, company: CompanyProfile, name: str = "Acme Traders") -> Ledger:
    ledger = Ledger(
        company_id=company.id,
        name=name,
        address="9 Buyer Lane",
        gst="27BBBBB0000B1Z5",
        phone_number="+91 9111111111",
    )
    db.add(ledger)
    db.commit()
    db.refresh(ledger)
    return ledger


def _invoice(db, company: CompanyProfile, ledger: Ledger, number: str = "INV-0042") -> Invoice:
    user = _user(db)
    product = Product(
        company_id=company.id,
        sku=f"SKU-{number}",
        name="Widget",
        price=Decimal("100.00"),
        gst_rate=Decimal("18.00"),
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    invoice = Invoice(
        invoice_number=number,
        company_id=company.id,
        ledger_id=ledger.id,
        ledger_name=ledger.name,
        ledger_address=ledger.address,
        company_name=company.name,
        company_address=company.address,
        company_currency_code="INR",
        company_logo_data=company.logo_data,
        company_logo_mime_type=company.logo_mime_type,
        voucher_type="sales",
        status="active",
        created_by=user.id,
        taxable_amount=Decimal("100.00"),
        total_tax_amount=Decimal("18.00"),
        cgst_amount=Decimal("9.00"),
        sgst_amount=Decimal("9.00"),
        total_amount=Decimal("118.00"),
        invoice_date=datetime(2026, 6, 1, 10, 0, 0),
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    db.add(InvoiceItem(
        invoice_id=invoice.id,
        product_id=product.id,
        hsn_sac="1234",
        quantity=Decimal("1.000"),
        unit_price=Decimal("100.00"),
        gst_rate=Decimal("18.00"),
        taxable_amount=Decimal("100.00"),
        tax_amount=Decimal("18.00"),
        cgst_amount=Decimal("9.00"),
        sgst_amount=Decimal("9.00"),
        line_total=Decimal("118.00"),
    ))
    db.commit()
    db.refresh(invoice)
    return invoice


def _payment(db, company: CompanyProfile, ledger: Ledger) -> Payment:
    user = _user(db)
    payment = Payment(
        company_id=company.id,
        ledger_id=ledger.id,
        voucher_type="receipt",
        amount=Decimal("118.00"),
        date=datetime(2026, 6, 2, 12, 0, 0),
        payment_number="RCPT-0001",
        mode="cash",
        created_by=user.id,
        status="active",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def _headers(company: CompanyProfile) -> dict[str, str]:
    return {"X-Company-Id": str(company.id)}


def _create_link(client, company, resource_type, resource_id, **extra):
    body = {"resource_type": resource_type, "resource_id": resource_id, **extra}
    return client.post("/api/share/", json=body, headers=_headers(company))


# ---------------------------------------------------------------------------
# Minting and revoking
# ---------------------------------------------------------------------------

def test_create_returns_token_and_is_idempotent(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)

    first = _create_link(client, company, "invoice", invoice.id)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["token"]
    assert payload["url"].endswith(f"/s/{payload['token']}")
    assert payload["resource_type"] == "invoice"
    assert payload["resource_id"] == invoice.id
    assert payload["view_count"] == 0
    assert payload["last_viewed_at"] is None

    second = _create_link(client, company, "invoice", invoice.id)
    assert second.status_code == 200
    # Pressing "Share" twice must not put a second live URL into circulation.
    assert second.json()["token"] == payload["token"]
    assert second.json()["id"] == payload["id"]


def test_list_returns_live_links_only(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)

    created = _create_link(client, company, "invoice", invoice.id).json()

    listed = client.get(
        "/api/share/",
        params={"resource_type": "invoice", "resource_id": invoice.id},
        headers=_headers(company),
    )
    assert listed.status_code == 200
    assert [row["token"] for row in listed.json()] == [created["token"]]

    assert client.delete(f"/api/share/{created['id']}", headers=_headers(company)).status_code == 204

    listed_again = client.get(
        "/api/share/",
        params={"resource_type": "invoice", "resource_id": invoice.id},
        headers=_headers(company),
    )
    assert listed_again.json() == []


def test_revoke_is_a_soft_delete(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    created = _create_link(client, company, "invoice", invoice.id).json()

    client.delete(f"/api/share/{created['id']}", headers=_headers(company))

    row = db_session.query(ShareLink).filter(ShareLink.id == created["id"]).first()
    assert row is not None, "revoke must never hard-delete: the row is the audit trail"
    assert row.revoked_at is not None


def test_statement_link_requires_a_period(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)

    missing = _create_link(client, company, "ledger_statement", ledger.id)
    assert missing.status_code == 400

    ok = _create_link(
        client, company, "ledger_statement", ledger.id,
        from_date="2026-04-01", to_date="2026-06-30",
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["from_date"] == "2026-04-01"
    assert ok.json()["to_date"] == "2026-06-30"


# ---------------------------------------------------------------------------
# The public page
# ---------------------------------------------------------------------------

def test_public_page_renders_the_summary_without_auth_header(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    body = page.text
    # Readable without downloading anything.
    assert "Invoice INV-0042" in body
    assert "Acme Traders" in body
    assert "118.00" in body
    # Open Graph is the whole reason this is server-rendered.
    assert 'property="og:title"' in body
    assert 'property="og:description"' in body
    assert 'property="og:image"' in body
    assert 'property="og:site_name"' in body
    assert 'name="twitter:card"' in body
    assert f"/s/{token}/logo" in body
    assert f"/s/{token}/pdf?download=1" in body
    assert '<meta name="robots" content="noindex' in body


def test_public_routes_are_also_mounted_under_api(client, db_session):
    """/s depends on an ingress rule; /api is routed on every tenant already."""
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    page = client.get(f"/api/s/{token}")
    assert page.status_code == 200
    # The page's own links stay on the mount the recipient actually reached.
    assert f"/api/s/{token}/pdf?download=1" in page.text


def test_public_routes_declare_no_auth_dependencies():
    """The real regression guard for this whole feature.

    conftest overrides ``get_current_user`` globally, so a request without an
    Authorization header succeeds whether or not the route declares the dependency.
    Only introspection can tell the difference.
    """
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if "/s/{token}" not in path:
            continue
        checked += 1
        names = {d.call.__name__ for d in route.dependant.dependencies if d.call}
        assert "get_current_user" not in names, path
        assert "get_active_company" not in names, path
    assert checked >= 8, "expected the public routes on both mounts"


def test_pdf_is_served_inline_by_default_and_attachment_on_download(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    inline = client.get(f"/s/{token}/pdf")
    assert inline.status_code == 200
    assert inline.headers["content-type"] == "application/pdf"
    assert inline.headers["content-disposition"].startswith("inline;")
    assert inline.content.startswith(b"%PDF")

    attached = client.get(f"/s/{token}/pdf", params={"download": 1})
    assert attached.headers["content-disposition"].startswith("attachment;")
    assert 'filename="invoice_INV-0042.pdf"' in attached.headers["content-disposition"]


def test_logo_route_serves_the_decoded_bytes(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    logo = client.get(f"/s/{token}/logo")
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/")
    assert logo.content == b"hello"


def test_document_html_renders_for_the_desktop_iframe(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    doc = client.get(f"/s/{token}/document.html")
    assert doc.status_code == 200
    assert "INV-0042" in doc.text


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def test_security_headers_on_html_and_pdf(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    for response in (client.get(f"/s/{token}"), client.get(f"/s/{token}/pdf")):
        assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
        assert response.headers["cache-control"] == "no-store"
        # Without this the ad link hands the token to simpleinvoicings.com in Referer.
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"

    html = client.get(f"/s/{token}")
    csp = html.headers["content-security-policy"]
    assert "script-src 'none'" in csp
    assert "frame-ancestors 'self'" in csp
    assert "base-uri 'none'" in csp


def test_ad_links_carry_noreferrer(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    body = client.get(f"/s/{token}").text
    assert "simpleinvoicings.com" in body
    assert 'rel="noopener noreferrer nofollow"' in body


def test_the_ad_never_reaches_the_pdf(client, db_session):
    """The load-bearing half of "ad on the page, never in the document".

    A recipient files this PDF with their accounts. Someone adding a "helpful"
    footer to the invoice builder later must break this test, not ship.
    """
    from src.services.share_documents import build_invoice_html

    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    pdf = client.get(f"/s/{token}/pdf")
    assert pdf.status_code == 200
    assert b"simpleinvoicings" not in pdf.content

    html = build_invoice_html(db_session, company.id, invoice.id)
    assert "simpleinvoicings" not in html
    assert "Made with Simple Invoicing" not in html


def test_revoked_and_unknown_tokens_are_indistinguishable(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    created = _create_link(client, company, "invoice", invoice.id).json()

    assert client.get(f"/s/{created['token']}").status_code == 200
    client.delete(f"/api/share/{created['id']}", headers=_headers(company))

    revoked = client.get(f"/s/{created['token']}")
    unknown = client.get("/s/definitely-not-a-real-token")

    assert revoked.status_code == 404
    assert unknown.status_code == 404
    # Identical body: never confirm to a scanner that a token was once real.
    assert revoked.content == unknown.content

    assert client.get(f"/s/{created['token']}/pdf").status_code == 404


def test_cancelled_invoice_shows_the_unavailable_page(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    invoice.status = "cancelled"
    db_session.commit()

    page = client.get(f"/s/{token}")
    # 404, not 200: this response must be indistinguishable from an unknown or
    # revoked token, and those are 404.
    assert page.status_code == 404
    assert "no longer available" in page.text
    # …and none of the document leaks onto the notice page.
    assert "INV-0042" not in page.text
    assert "Acme Traders" not in page.text

    assert client.get(f"/s/{token}/pdf").status_code == 404


def test_inactive_payment_shows_the_unavailable_page(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    payment = _payment(db_session, company, ledger)
    token = _create_link(client, company, "payment", payment.id).json()["token"]

    assert client.get(f"/s/{token}").status_code == 200

    payment.status = "cancelled"
    db_session.commit()

    page = client.get(f"/s/{token}")
    # 404, not 200: this response must be indistinguishable from an unknown or
    # revoked token, and those are 404.
    assert page.status_code == 404
    assert "no longer available" in page.text


def test_cannot_mint_a_link_for_another_companys_invoice(client, db_session):
    alpha = _company(db_session, "Alpha Ltd")
    beta = _company(db_session, "Beta Ltd")
    beta_ledger = _ledger(db_session, beta, name="Beta Buyer")
    beta_invoice = _invoice(db_session, beta, beta_ledger, number="BETA-0001")

    # Acting as Alpha, ask for Beta's invoice.
    response = _create_link(client, alpha, "invoice", beta_invoice.id)
    assert response.status_code == 404


def test_a_token_resolves_only_within_its_own_company(client, db_session):
    """The rule that stops a token reaching across tenants.

    The link row says company Alpha; the resource id belongs to Beta. Every
    downstream query filters on the link's own company_id, so the document is
    simply not there — and the page is the same uniform 404 an unknown token gets.
    """
    alpha = _company(db_session, "Alpha Ltd")
    beta = _company(db_session, "Beta Ltd")
    beta_ledger = _ledger(db_session, beta, name="Beta Buyer")
    beta_invoice = _invoice(db_session, beta, beta_ledger, number="BETA-0001")

    smuggled = ShareLink(
        company_id=alpha.id,
        token="smuggled-token",
        resource_type="invoice",
        resource_id=beta_invoice.id,
        view_count=0,
    )
    db_session.add(smuggled)
    db_session.commit()

    page = client.get("/s/smuggled-token")
    assert page.status_code == 404
    assert page.content == client.get("/s/definitely-not-a-real-token").content
    assert "BETA-0001" not in page.text


# ---------------------------------------------------------------------------
# View counting
# ---------------------------------------------------------------------------

def test_view_count_increments_on_html_only(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    created = _create_link(client, company, "invoice", invoice.id).json()
    token = created["token"]

    def count() -> int:
        db_session.expire_all()
        return db_session.query(ShareLink).filter(ShareLink.token == token).one().view_count

    assert count() == 0

    client.get(f"/s/{token}")
    assert count() == 1

    # The desktop iframe and the download button both hit these; counting them
    # would multiply every real open.
    client.get(f"/s/{token}/pdf")
    client.get(f"/s/{token}/pdf", params={"download": 1})
    client.get(f"/s/{token}/document.html")
    client.get(f"/s/{token}/logo")
    assert count() == 1

    client.get(f"/s/{token}")
    assert count() == 2


@pytest.mark.parametrize(
    "user_agent",
    [
        "WhatsApp/2.23.20.0 A",
        "facebookexternalhit/1.1",
        "TelegramBot (like TwitterBot)",
        "Twitterbot/1.0",
        "Slackbot-LinkExpanding 1.0",
    ],
)
def test_crawlers_do_not_count_as_views(client, db_session, user_agent):
    """"Opened 1 time" must not mean "WhatsApp drew a preview card"."""
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    response = client.get(f"/s/{token}", headers={"User-Agent": user_agent})
    assert response.status_code == 200

    db_session.expire_all()
    row = db_session.query(ShareLink).filter(ShareLink.token == token).one()
    assert row.view_count == 0
    assert row.last_viewed_at is None


# ---------------------------------------------------------------------------
# The refactored authenticated endpoints must not have moved
# ---------------------------------------------------------------------------

def test_authenticated_invoice_pdf_still_works(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)

    response = client.get(f"/api/invoices/{invoice.id}/pdf", headers=_headers(company))
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert response.headers["content-disposition"] == 'attachment; filename="invoice_INV-0042.pdf"'

    assert client.get("/api/invoices/999999/pdf", headers=_headers(company)).status_code == 404


def test_authenticated_statement_pdf_still_works(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    _invoice(db_session, company, ledger)

    response = client.get(
        f"/api/ledgers/{ledger.id}/statement/pdf",
        params={"from_date": "2026-04-01", "to_date": "2026-06-30"},
        headers=_headers(company),
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "statement_Acme_Traders_2026-04-01_2026-06-30.pdf" in response.headers["content-disposition"]


def test_authenticated_receipt_pdf_still_works(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    payment = _payment(db_session, company, ledger)

    response = client.get(f"/api/payments/{payment.id}/pdf", headers=_headers(company))
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert response.headers["content-disposition"] == 'inline; filename="receipt_RCPT-0001.pdf"'


def test_statement_share_link_renders_end_to_end(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    _invoice(db_session, company, ledger)

    token = _create_link(
        client, company, "ledger_statement", ledger.id,
        from_date="2026-04-01", to_date="2026-06-30",
    ).json()["token"]

    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    assert "Account Statement" in page.text
    assert "Acme Traders" in page.text

    pdf = client.get(f"/s/{token}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert b"simpleinvoicings" not in pdf.content


def test_receipt_share_link_renders_end_to_end(client, db_session):
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    payment = _payment(db_session, company, ledger)

    token = _create_link(client, company, "payment", payment.id).json()["token"]

    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    assert "Receipt RCPT-0001" in page.text

    pdf = client.get(f"/s/{token}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert 'filename="receipt_RCPT-0001.pdf"' in pdf.headers["content-disposition"]


def test_share_url_prefers_a_configured_https_origin(client, db_session, monkeypatch):
    """rudra and wf never set PUBLIC_APP_BASE_URL — it must not leak localhost."""
    from src.core.config import settings

    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)

    # Default (http://localhost:5173) is untrusted: fall back to the request origin.
    unset = _create_link(client, company, "invoice", invoice.id).json()
    assert "localhost:5173" not in unset["url"]
    assert unset["url"].endswith(f"/s/{unset['token']}")

    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://books.example.com/")
    listed = client.get(
        "/api/share/",
        params={"resource_type": "invoice", "resource_id": invoice.id},
        headers=_headers(company),
    ).json()
    assert listed[0]["url"] == f"https://books.example.com/s/{listed[0]['token']}"


def test_share_links_can_be_switched_off(client, db_session, monkeypatch):
    from src.core.config import settings

    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    monkeypatch.setattr(settings, "SHARE_LINKS_ENABLED", False)
    assert client.get(f"/s/{token}").status_code == 404
    assert _create_link(client, company, "invoice", invoice.id).status_code == 403


def test_ad_block_degrades_field_by_field(client, db_session, monkeypatch):
    """Every promo field is independently optional.

    A half-configured deployment must show less, never something broken: no
    dangling "call" button with no number, no empty chip row, no dead link.
    """
    from src.core.config import settings

    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    body = client.get(f"/s/{token}").text
    assert "Simple Invoicings" in body
    assert "simpleinvoicings.com" in body
    # The published number renders as a tel: link, not as plain text.
    assert 'href="tel:+919871052105"' in body
    assert "https://wa.me/919871052105" in body
    assert "1 month free" in body

    # Blanking the phone removes the button rather than leaving an empty tel:.
    monkeypatch.setattr(settings, "SHARE_AD_PHONE", "")
    body = client.get(f"/s/{token}").text
    assert "tel:" not in body
    assert "https://wa.me/919871052105" in body  # unaffected

    # Blanking WhatsApp falls back to the website as the primary call to action.
    monkeypatch.setattr(settings, "SHARE_AD_WHATSAPP", "")
    body = client.get(f"/s/{token}").text
    assert "wa.me" not in body
    assert "simpleinvoicings.com" in body

    # Blank chips drop the row entirely.
    monkeypatch.setattr(settings, "SHARE_AD_CHIPS", "")
    assert "1 month free" not in client.get(f"/s/{token}").text

    # And the whole block can be switched off.
    monkeypatch.setattr(settings, "SHARE_AD_ENABLED", False)
    body = client.get(f"/s/{token}").text
    assert "simpleinvoicings.com" not in body
    assert "Simple Invoicings" not in body


def test_promo_never_reaches_the_pdf(client, db_session):
    """The ad lives on the web page only -- the PDF is the business's document."""
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    pdf = client.get(f"/s/{token}/pdf")
    assert pdf.content.startswith(b"%PDF-")
    for needle in (b"simpleinvoicings", b"Simple Invoicings", b"wa.me", b"98710"):
        assert needle not in pdf.content


def test_full_document_starts_collapsed(client, db_session):
    """The inline document is opt-in.

    It is a native <details>, not a scripted toggle -- the CSP on this response
    sets script-src 'none', so anything needing JS would silently never open.
    Collapsed also means the browser does not fetch document.html until someone
    asks for it, and most readers only want the summary and the download.
    """
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    body = client.get(f"/s/{token}").text
    assert '<details class="preview">' in body
    # No `open` attribute anywhere on that element -- that is what "collapsed" is.
    assert "<details class=\"preview\" open" not in body
    assert "preview__summary" in body
    # The iframe is still in the markup; it is the disclosure that defers it.
    assert f"/s/{token}/document.html" in body
    # And no inline handler crept in, which the CSP would have killed anyway.
    assert "onclick=" not in body.lower()


def test_every_landing_miss_is_byte_identical(client, db_session):
    """Unknown, revoked and cancelled must be one response, not three.

    Any difference — status, length, a word — tells a scanner that a token was
    once real, which is the one thing a token-guessing attack wants to learn.
    """
    company = _company(db_session, "Alpha Ltd")
    ledger = _ledger(db_session, company)

    unknown = client.get("/s/thistokenwasnevermintedatall00")

    revoked_invoice = _invoice(db_session, company, ledger, number="INV-REV")
    revoked = _create_link(client, company, "invoice", revoked_invoice.id).json()
    client.delete(f"/api/share/{revoked['id']}", headers=_headers(company))
    revoked_page = client.get(f"/s/{revoked['token']}")

    cancelled_invoice = _invoice(db_session, company, ledger, number="INV-CAN")
    cancelled = _create_link(client, company, "invoice", cancelled_invoice.id).json()
    cancelled_invoice.status = "cancelled"
    db_session.commit()
    cancelled_page = client.get(f"/s/{cancelled['token']}")

    assert unknown.status_code == revoked_page.status_code == cancelled_page.status_code == 404
    assert unknown.text == revoked_page.text == cancelled_page.text
    # And nothing about the real documents survives into it. (Match on rendered
    # strings, not bare numbers — "118" also occurs in a CSS gradient stop.)
    for leak in ("INV-REV", "INV-CAN", "Acme Traders", "Alpha Ltd", "118.00"):
        assert leak not in unknown.text


def test_user_supplied_names_are_escaped_on_the_public_page(client, db_session):
    """Company and party names are user-supplied and now render publicly."""
    company = _company(db_session, "Alpha <script>alert(1)</script> Ltd")
    ledger = _ledger(db_session, company, name='Acme "><img src=x> Traders')
    invoice = _invoice(db_session, company, ledger)
    token = _create_link(client, company, "invoice", invoice.id).json()["token"]

    body = client.get(f"/s/{token}").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    assert "<img src=x>" not in body
