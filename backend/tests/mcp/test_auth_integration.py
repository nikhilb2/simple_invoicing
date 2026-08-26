"""End-to-end through the real OAuth token service — no principal stubbing.

Everything else in this package patches ``resolve_principal``; this file exercises
the seam itself, so a change in the OAuth track's contract (argument order, field
names, audience rules) fails here rather than in production.
"""

from __future__ import annotations

import json

import pytest

from src.core.config import settings
from src.mcp_server.config import ALL_SCOPES
from src.models.company import CompanyProfile
from src.models.oauth import OAuthClient
from src.models.user import User, UserRole
from src.services.oauth.tokens import mint_token

INITIALIZE = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})


@pytest.fixture
def granted(db_session):
    """A live access token bound to one user, one company and every scope."""
    user = User(
        email="oauth-user@example.com",
        full_name="OAuth User",
        hashed_password="x",
        role=UserRole.admin,
    )
    company = CompanyProfile(
        name="OAuth Co", address="", gst="", phone_number="", currency_code="INR",
        email="", website="", bank_name="", branch_name="", account_name="",
        account_number="", ifsc_code="",
    )
    client_row = OAuthClient(
        client_id="test-client-id",
        client_name="Test Client",
        redirect_uris=json.dumps(["https://claude.ai/callback"]),
        grant_types="authorization_code refresh_token",
        response_types="code",
        scope=" ".join(ALL_SCOPES),
        token_endpoint_auth_method="none",
        is_active=True,
    )
    db_session.add_all([user, company, client_row])
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(company)

    raw, _ = mint_token(
        db_session,
        token_type="access",
        client_id=client_row.client_id,
        user_id=user.id,
        company_id=company.id,
        scope=" ".join(ALL_SCOPES),
        resource=settings.MCP_RESOURCE_URI,
    )
    db_session.commit()
    return {"token": raw, "user": user, "company": company}


def _post(client, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", content=body, headers=headers)


def test_a_real_token_authenticates_an_mcp_request(client, granted):
    response = _post(client, INITIALIZE, token=granted["token"])
    assert response.status_code == 200, response.text
    assert response.json()["result"]["serverInfo"]["name"] == "simple-invoicing"


def test_a_real_token_lists_tools_scoped_to_its_grant(client, granted):
    body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    response = _post(client, body, token=granted["token"])
    tools = response.json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "invoices_list" in names
    assert "search" in names


def test_a_real_token_dispatches_a_read_tool(client, granted):
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "ledgers_list", "arguments": {}},
        }
    )
    response = _post(client, body, token=granted["token"])
    result = response.json()["result"]
    assert result["isError"] is False
    assert "items" in result["structuredContent"]


def test_a_garbage_token_is_challenged_not_accepted(client, granted):
    response = _post(client, INITIALIZE, token="sio_at_not-a-real-token")
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["WWW-Authenticate"]


def test_no_token_at_all_is_challenged(client, granted):
    response = _post(client, INITIALIZE)
    assert response.status_code == 401


def test_a_non_bearer_authorization_header_is_challenged(client, granted):
    response = client.post(
        "/mcp",
        content=INITIALIZE,
        headers={"Content-Type": "application/json", "Authorization": "Basic abc123"},
    )
    assert response.status_code == 401


def test_a_revoked_token_stops_working(client, db_session, granted):
    from src.models.oauth import OAuthToken
    from src.services.oauth.tokens import hash_token, revoke_token_row

    row = (
        db_session.query(OAuthToken)
        .filter(OAuthToken.token_hash == hash_token(granted["token"]))
        .one()
    )
    revoke_token_row(db_session, row)
    db_session.commit()

    response = _post(client, INITIALIZE, token=granted["token"])
    assert response.status_code == 401


def test_a_token_for_another_audience_is_rejected(client, db_session, granted):
    """RFC 8707 audience binding: a token minted for someone else's resource must
    not open this door."""
    user = granted["user"]
    raw, _ = mint_token(
        db_session,
        token_type="access",
        client_id="test-client-id",
        user_id=user.id,
        company_id=granted["company"].id,
        scope=" ".join(ALL_SCOPES),
        resource="https://someone-else.example.com/mcp",
    )
    db_session.commit()

    response = _post(client, INITIALIZE, token=raw)
    assert response.status_code == 401


def test_the_grants_scopes_gate_the_tool_list(client, db_session, granted):
    from src.mcp_server.config import SCOPE_READ

    raw, _ = mint_token(
        db_session,
        token_type="access",
        client_id="test-client-id",
        user_id=granted["user"].id,
        company_id=granted["company"].id,
        scope=SCOPE_READ,
        resource=settings.MCP_RESOURCE_URI,
    )
    db_session.commit()

    body = json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in _post(client, body, token=raw).json()["result"]["tools"]}
    assert "invoices_list" in names
    assert "invoices_create" not in names
    assert "smtp_get_config" not in names
