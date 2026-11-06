"""Tenant text must not be able to pull server files or internal URLs into a PDF."""

import ast
import base64
from pathlib import Path

import pytest
import weasyprint

from src.models.company import CompanyProfile
from src.services import pdf_render
from src.services.pdf_render import safe_url_fetcher
from tests.api.test_company_settings import (
    _create_company,
    _make_minimal_png_bytes,
    _restore_user_override,
    _with_persistent_user_override,
)

SRC = Path(__file__).resolve().parents[2] / "src"


def _injection(target: str) -> str:
    """Tag soup that survives lenient base64 decoding, whatever the target's length."""
    for pad in range(4):
        payload = "A" * (4 + pad) + f'"><a rel="attachment" href="{target}">x</a><img src="'
        try:
            base64.b64decode(payload)
            return payload
        except ValueError:
            continue
    raise AssertionError("no padding decodes")


@pytest.fixture
def persistent_user():
    old = _with_persistent_user_override()
    yield
    _restore_user_override(old)


@pytest.fixture
def fetched(monkeypatch):
    """Every URL that actually reaches the real fetcher."""
    urls = []
    real = pdf_render.default_url_fetcher

    def spy(url, *args, **kwargs):
        urls.append(url)
        return real(url, *args, **kwargs)

    monkeypatch.setattr(pdf_render, "default_url_fetcher", spy)
    return urls


@pytest.mark.parametrize("payload", [
    _injection("file:///etc/passwd"),
    '"><img src="file:///etc/passwd">',
])
def test_markup_is_refused_as_a_logo(client, db_session, persistent_user, payload):
    _create_company(client, "Injection Co")
    response = client.put("/api/company/logo", json={"data": payload, "mime_type": "image/png"})
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("raw", [
    b"just some text that is valid base64 once encoded",
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    b"GIF89a not on the allowed list",
])
def test_valid_base64_that_is_not_png_or_jpeg_is_refused(client, db_session, persistent_user, raw):
    _create_company(client, "Not An Image Co")
    response = client.put("/api/company/logo", json={
        "data": base64.b64encode(raw).decode(),
        "mime_type": "image/png",
    })
    assert response.status_code == 400, response.text
    assert "PNG or JPEG" in response.text


def test_the_client_cannot_choose_the_stored_type(client, db_session, persistent_user, monkeypatch):
    # Optimisation off, so the stored type is whatever the upload route settled on.
    monkeypatch.setattr("src.api.routes.company._HAS_PIL", False)
    _create_company(client, "Claims SVG Co")
    png = _make_minimal_png_bytes(width=2, height=2, r=1, g=2, b=3)
    response = client.put("/api/company/logo", json={
        "data": base64.b64encode(png).decode(),
        "mime_type": "image/svg+xml",
    })
    assert response.status_code == 200, response.text
    assert response.json()["logo_mime_type"] == "image/png"


def test_rendering_loads_data_uris_but_nothing_else(tmp_path, fetched):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-MARKER")
    png = base64.b64encode(_make_minimal_png_bytes(width=2, height=2, r=1, g=2, b=3)).decode()
    html = f"""<html><body>
      <img src="data:image/png;base64,{png}">
      <img src="file://{secret}">
      <img src="http://169.254.169.254/latest/meta-data/">
      <link rel="attachment" href="file://{secret}">
      <a rel="attachment" href="file://{secret}">x</a>
    </body></html>"""

    pdf = weasyprint.HTML(string=html, url_fetcher=safe_url_fetcher).write_pdf()

    assert pdf.startswith(b"%PDF")
    assert fetched and all(url.startswith("data:") for url in fetched), fetched
    assert b"/EmbeddedFile" not in pdf


def test_a_poisoned_logo_already_in_the_database_cannot_escape_the_invoice_pdf(
    client, db_session, persistent_user, tmp_path, fetched
):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-MARKER")
    company_id = _create_company(client, "Old Poisoned Row Co")
    company = db_session.get(CompanyProfile, company_id)
    company.logo_data = _injection(f"file://{secret}")
    company.logo_mime_type = "image/png"
    db_session.commit()
    headers = {"X-Company-Id": str(company_id)}

    ledger = client.post("/api/ledgers/", headers=headers, json={
        "name": "Customer", "address": "x", "phone_number": "1",
    }).json()["id"]
    product = client.post("/api/products/", headers=headers, json={
        "sku": "S1", "name": "Widget", "price": 100, "maintain_inventory": False,
    }).json()["id"]
    invoice = client.post("/api/invoices/", headers=headers, json={
        "ledger_id": ledger, "items": [{"product_id": product, "quantity": 1}],
    })
    assert invoice.status_code == 200, invoice.text

    response = client.get(f"/api/invoices/{invoice.json()['id']}/pdf", headers=headers)

    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")
    assert all(url.startswith("data:") for url in fetched), fetched
    assert b"/EmbeddedFile" not in response.content


def test_templates_escape_the_logo():
    for name, expression in [
        ("invoice_template.py", "base64,{_e(invoice.company_logo_data)}"),
        ("purchase_template.py", "base64,{_e(invoice.company_logo_data)}"),
        ("credit_note_template.py", "base64,{_e(logo_data)}"),
    ]:
        assert expression in (SRC / "services" / "pdf_templates" / name).read_text()


def test_every_pdf_render_uses_the_safe_fetcher():
    """One forgotten call would reopen file:// for all tenant text."""
    calls = 0
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "HTML"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "weasyprint"
            ):
                calls += 1
                keywords = {k.arg: k.value for k in node.keywords}
                fetcher = keywords.get("url_fetcher")
                assert isinstance(fetcher, ast.Name) and fetcher.id == "safe_url_fetcher", (
                    f"{path}:{node.lineno} renders without safe_url_fetcher"
                )
    assert calls >= 7
