"""Dispatch: the tool call must be the REST call, with the same rules applied."""

from __future__ import annotations

import json

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.core.config import settings
from src.db.session import get_db
from src.mcp_server import dispatch as dispatch_module
from src.mcp_server.config import MCP_TOOL_HEADER
from src.models.company import CompanyProfile
from src.models.user import User, UserRole
from tests.mcp.conftest import make_principal, override_principal


@pytest.fixture
def writes_on(monkeypatch):
    monkeypatch.setattr(settings, "MCP_WRITE_ENABLED", True)


def _ledger_payload(name: str):
    return {
        "name": name,
        "address": "9 Test Road",
        "gst": "",
        "opening_balance": None,
        "phone_number": "+91 9000000000",
        "email": "ledger@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def _structured(body):
    return body["result"]["structuredContent"]


def test_tool_call_returns_the_same_payload_as_the_rest_call(mcp_call, client, company):
    client.post("/api/ledgers/", json=_ledger_payload("Acme Traders"),
                headers={"X-Company-Id": str(company.id)})

    rest = client.get("/api/ledgers/", headers={"X-Company-Id": str(company.id)}).json()
    tool = _structured(mcp_call.call_tool("ledgers_list", {}))

    assert [item["id"] for item in tool["items"]] == [item["id"] for item in rest["items"]]
    assert tool["total"] == rest["total"]


def test_path_parameters_are_substituted(mcp_call, client, company):
    created = client.post(
        "/api/ledgers/", json=_ledger_payload("Beta Supplies"),
        headers={"X-Company-Id": str(company.id)},
    ).json()

    tool = _structured(mcp_call.call_tool("ledgers_get", {"ledger_id": created["id"]}))
    assert tool["name"] == "Beta Supplies"


def test_query_parameters_reach_the_endpoint(mcp_call, client, company):
    client.post("/api/ledgers/", json=_ledger_payload("Findable Co"),
                headers={"X-Company-Id": str(company.id)})
    client.post("/api/ledgers/", json=_ledger_payload("Hidden Co"),
                headers={"X-Company-Id": str(company.id)})

    tool = _structured(mcp_call.call_tool("ledgers_list", {"search": "Findable"}))
    assert [item["name"] for item in tool["items"]] == ["Findable Co"]


def test_body_arguments_are_flattened_not_nested(mcp_call, company, writes_on):
    """Models pick flat arguments far more reliably than {"body": {...}}."""
    body = mcp_call.call_tool("ledgers_create", _ledger_payload("Flat Args Ltd"))
    result = body["result"]
    assert result["isError"] is False, result
    assert result["structuredContent"]["name"] == "Flat Args Ltd"


def test_a_tool_bound_to_company_a_cannot_read_company_b(mcp_call, client, db_session, company):
    other = CompanyProfile(
        name="Other Co", address="", gst="", phone_number="", currency_code="INR",
        email="", website="", bank_name="", branch_name="", account_name="",
        account_number="", ifsc_code="",
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    client.post("/api/ledgers/", json=_ledger_payload("Company B Only"),
                headers={"X-Company-Id": str(other.id)})

    bound_to_a = make_principal(company_id=company.id)
    tool = _structured(mcp_call.call_tool("ledgers_list", {}, principal=bound_to_a))
    assert "Company B Only" not in {item["name"] for item in tool["items"]}


def test_errors_come_back_as_tool_errors_not_http_errors(mcp_call, company):
    body = mcp_call.call_tool("ledgers_get", {"ledger_id": 999999})
    assert body["result"]["isError"] is True
    assert "404" in body["result"]["content"][0]["text"]


def test_validation_errors_are_flattened_to_readable_lines(mcp_call, company, writes_on):
    body = mcp_call.call_tool("ledgers_create", {"name": "Missing Fields"})
    result = body["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "Invalid arguments (422)" in text
    # `field: message`, one per line — not a dumped list of dicts.
    assert "address:" in text
    assert "{'loc'" not in text


def test_unknown_arguments_are_rejected_with_the_valid_list(mcp_call, company):
    result = mcp_call.call_tool("ledgers_list", {"nonsense": 1})["result"]
    assert result["isError"] is True
    assert "Unknown argument(s): nonsense" in result["content"][0]["text"]


def test_missing_path_argument_is_a_clear_tool_error(mcp_call, company):
    result = mcp_call.call_tool("ledgers_get", {})["result"]
    assert result["isError"] is True
    assert "Missing required argument" in result["content"][0]["text"]


def test_page_size_is_clamped_before_the_call(mcp_call, client, company):
    tool = _structured(mcp_call.call_tool("ledgers_list", {"page_size": 500}))
    assert tool["page_size"] == 50
    assert "_page_size_clamped" in tool


def test_csv_export_comes_back_as_text_not_base64(mcp_call, client, company):
    result = mcp_call.call_tool("products_export_csv", {})["result"]
    assert result["isError"] is False
    text = result["content"][0]["text"]
    assert "item code" in text.lower()
    assert "structuredContent" in result
    assert "csv" in result["structuredContent"]


def test_pdf_is_described_not_embedded(mcp_call, client, company, monkeypatch):
    """A multi-megabyte base64 blob would swallow the model's context."""
    import httpx

    from src.mcp_server.registry import get_registry

    registry = get_registry(app)
    spec = registry.get("invoices_download_pdf")
    response = httpx.Response(
        200, content=b"%PDF-1.7 fake", headers={"content-type": "application/pdf"}
    )
    result = dispatch_module.build_result(spec, response)
    assert result.is_error is False
    assert result.structured["content_type"] == "application/pdf"
    assert result.structured["bytes"] == len(b"%PDF-1.7 fake")
    assert "download" in result.structured["note"].lower()
    assert "JVBER" not in json.dumps(result.to_mcp())  # no base64 payload


def test_inner_401_is_a_dispatcher_bug_not_an_outer_401(mcp_call, client, company, caplog):
    """We minted the internal token, so a 401 back is our bug. Surfacing it as an
    outer HTTP 401 would send the client round the OAuth flow forever."""
    import httpx

    from src.mcp_server.registry import get_registry

    registry = get_registry(app)

    async def always_401(*args, **kwargs):
        return httpx.Response(401, json={"detail": "Could not validate credentials"})

    original = registry.client.request
    registry.client.request = always_401
    try:
        with override_principal(make_principal(company_id=company.id)):
            response = client.post(
                "/mcp",
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "ledgers_list", "arguments": {}},
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
    finally:
        registry.client.request = original

    assert response.status_code == 200
    assert "WWW-Authenticate" not in response.headers
    assert response.json()["error"]["code"] == -32603


def test_dispatch_sends_the_mcp_tool_header(company):
    """`get_active_company` keys off this header to stay ephemeral."""
    principal = make_principal(company_id=company.id)
    headers = dispatch_module.internal_headers("ledgers_list", principal)
    assert headers[MCP_TOOL_HEADER] == "ledgers_list"
    assert headers["X-Company-Id"] == str(company.id)
    assert headers["Authorization"].startswith("Bearer ")


def test_internal_token_is_short_lived_and_marked(company):
    from src.core.security import decode_token

    principal = make_principal(company_id=company.id)
    headers = dispatch_module.internal_headers("ledgers_list", principal)
    claims = decode_token(headers["Authorization"].removeprefix("Bearer "))
    assert claims["src"] == "mcp"
    assert claims["tool"] == "ledgers_list"
    assert claims["sub"] == principal.email
    assert claims["exp"] - claims.get("iat", claims["exp"] - 60) <= 60


def _persistent_user(db: Session = Depends(get_db)) -> User:
    user = db.query(User).filter(User.email == "persist@example.com").first()
    if user is None:
        user = User(
            email="persist@example.com",
            full_name="Persistent Admin",
            hashed_password="x",
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def test_tool_call_does_not_persist_the_users_active_company(client, db_session, company):
    """A readOnlyHint tool must never change which company the human sees in the
    web UI on their next page load."""
    other = CompanyProfile(
        name="Second Co", address="", gst="", phone_number="", currency_code="INR",
        email="", website="", bank_name="", branch_name="", account_name="",
        account_number="", ifsc_code="",
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _persistent_user
    try:
        # Establish a real active company through the ordinary REST path.
        client.get("/api/ledgers/", headers={"X-Company-Id": str(company.id)})
        user = db_session.query(User).filter(User.email == "persist@example.com").one()
        db_session.refresh(user)
        before = user.active_company_id
        assert before == company.id

        with override_principal(make_principal(company_id=company.id)):
            response = client.post(
                "/mcp",
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "ledgers_list",
                            "arguments": {"company_id": other.id},
                        },
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is False

        db_session.expire_all()
        user = db_session.query(User).filter(User.email == "persist@example.com").one()
        assert user.active_company_id == before
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous


def test_company_id_argument_narrows_the_tenant(mcp_call, client, db_session, company):
    other = CompanyProfile(
        name="Third Co", address="", gst="", phone_number="", currency_code="INR",
        email="", website="", bank_name="", branch_name="", account_name="",
        account_number="", ifsc_code="",
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    client.post("/api/ledgers/", json=_ledger_payload("Third Co Ledger"),
                headers={"X-Company-Id": str(other.id)})

    bound = make_principal(company_id=company.id)
    tool = _structured(mcp_call.call_tool("ledgers_list", {"company_id": other.id}, principal=bound))
    assert {item["name"] for item in tool["items"]} == {"Third Co Ledger"}


def test_oversized_list_response_is_truncated_and_says_so(mcp_call, client, company, monkeypatch):
    import src.mcp_server.truncation as truncation

    for index in range(30):
        client.post(
            "/api/ledgers/", json=_ledger_payload(f"Bulk Ledger {index:03d}"),
            headers={"X-Company-Id": str(company.id)},
        )

    # Squeeze the budget rather than creating megabytes of fixtures.
    monkeypatch.setattr(truncation, "MAX_RESPONSE_BYTES", 1500)
    tool = _structured(mcp_call.call_tool("ledgers_list", {"page_size": 50}))

    assert "_truncated" in tool
    assert tool["_truncated"]["field"] == "items"
    assert tool["_truncated"]["returned"] < tool["_truncated"]["total"]
    assert len(tool["items"]) == tool["_truncated"]["returned"]


def test_a_bare_list_response_keeps_its_truncation_note(mcp_call, client, company, monkeypatch):
    """`GET /api/payments/` returns a bare array, not a paginated envelope. The
    note must survive being wrapped into {"items": [...]}."""
    import src.mcp_server.truncation as truncation

    ledger = client.post(
        "/api/ledgers/", json=_ledger_payload("Payer Co"),
        headers={"X-Company-Id": str(company.id)},
    ).json()
    for index in range(12):
        client.post(
            "/api/payments/",
            json={
                "ledger_id": ledger["id"],
                "voucher_type": "receipt",
                "amount": 100 + index,
                "date": "2026-01-01",
                "mode": "cash",
                "notes": "n" * 100,
            },
            headers={"X-Company-Id": str(company.id)},
        )

    monkeypatch.setattr(truncation, "MAX_RESPONSE_BYTES", 900)
    tool = _structured(mcp_call.call_tool("payments_list", {}))
    assert "_truncated" in tool
    assert len(tool["items"]) == tool["_truncated"]["returned"]
