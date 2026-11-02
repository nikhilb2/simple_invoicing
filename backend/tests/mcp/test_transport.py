"""Transport-level behaviour: the auth gate, HTTP verbs and JSON-RPC framing."""

from __future__ import annotations

import json

from src.mcp_server.config import FALLBACK_PROTOCOL_VERSION, LATEST_PROTOCOL_VERSION
from tests.mcp.conftest import override_principal

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": LATEST_PROTOCOL_VERSION, "capabilities": {}},
}


def _post(client, payload, **kwargs):
    return client.post(
        "/mcp",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json", **kwargs.pop("headers", {})},
        **kwargs,
    )


def test_unauthenticated_call_is_a_real_401(client):
    """A 200 wrapping isError:true produces no auth prompt in Claude at all."""
    with override_principal(None):
        response = _post(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "invoices_list", "arguments": {}}})
    assert response.status_code == 401


def test_401_carries_the_resource_metadata_challenge(client):
    with override_principal(None):
        response = _post(client, INITIALIZE)
    assert response.status_code == 401
    challenge = response.headers["WWW-Authenticate"]
    assert challenge.startswith("Bearer ")
    assert 'error="invalid_token"' in challenge
    assert "resource_metadata=" in challenge
    assert "/.well-known/oauth-protected-resource/mcp" in challenge
    assert "scope=" in challenge
    assert "invoicing:read" in challenge


def test_unauthenticated_tools_list_is_also_401(client):
    with override_principal(None):
        response = _post(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert response.status_code == 401


def test_get_is_method_not_allowed(client, mcp_principal):
    with override_principal(mcp_principal):
        response = client.get("/mcp")
    assert response.status_code == 405


def test_delete_terminates_politely(client, mcp_principal):
    with override_principal(mcp_principal):
        response = client.delete("/mcp")
    assert response.status_code == 200


def test_notification_gets_202_with_no_body(client, mcp_principal):
    with override_principal(mcp_principal):
        response = _post(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response.status_code == 202
    assert response.content == b""


def test_parse_error_is_http_200_with_an_error_member(client, mcp_principal):
    with override_principal(mcp_principal):
        response = client.post(
            "/mcp", content="{not json", headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32700


def test_unknown_method_is_http_200_with_minus_32601(client, mcp_principal):
    with override_principal(mcp_principal):
        response = _post(client, {"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 7
    assert body["error"]["code"] == -32601


def test_initialize_echoes_a_supported_protocol_version(client, mcp_principal):
    with override_principal(mcp_principal):
        response = _post(client, INITIALIZE)
    result = response.json()["result"]
    assert result["protocolVersion"] == LATEST_PROTOCOL_VERSION
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "simple-invoicing"
    assert result["instructions"]


def test_initialize_falls_back_for_an_unknown_client_version(client, mcp_principal):
    payload = {**INITIALIZE, "params": {"protocolVersion": "1999-01-01"}}
    with override_principal(mcp_principal):
        response = _post(client, payload)
    assert response.json()["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION


def test_older_protocol_revision_is_negotiated_intact(client, mcp_principal):
    payload = {**INITIALIZE, "params": {"protocolVersion": FALLBACK_PROTOCOL_VERSION}}
    with override_principal(mcp_principal):
        response = _post(client, payload)
    assert response.json()["result"]["protocolVersion"] == FALLBACK_PROTOCOL_VERSION


def test_unsupported_protocol_header_is_a_real_400(client, mcp_principal):
    with override_principal(mcp_principal):
        response = _post(client, INITIALIZE, headers={"MCP-Protocol-Version": "1999-01-01"})
    assert response.status_code == 400


def test_disallowed_origin_is_rejected(client, mcp_principal):
    """DNS-rebinding protection required by the transport spec."""
    with override_principal(mcp_principal):
        response = _post(client, INITIALIZE, headers={"Origin": "https://evil.example.com"})
    assert response.status_code == 403


def test_configured_app_origin_is_allowed(client, mcp_principal):
    from src.core.config import settings

    with override_principal(mcp_principal):
        response = _post(client, INITIALIZE, headers={"Origin": settings.PUBLIC_APP_BASE_URL})
    assert response.status_code == 200


def test_ping_is_answered(client, mcp_principal):
    with override_principal(mcp_principal):
        response = _post(client, {"jsonrpc": "2.0", "id": 3, "method": "ping"})
    assert response.json()["result"] == {}


def test_batch_of_notifications_is_202(client, mcp_principal):
    with override_principal(mcp_principal):
        response = _post(client, [{"jsonrpc": "2.0", "method": "notifications/initialized"}])
    assert response.status_code == 202


def test_batch_returns_one_response_per_request(client, mcp_principal):
    with override_principal(mcp_principal):
        response = _post(
            client,
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ],
        )
    body = response.json()
    assert [entry["id"] for entry in body] == [1, 2]


def test_api_prefixed_alias_serves_the_same_endpoint(client, mcp_principal):
    with override_principal(mcp_principal):
        response = client.post(
            "/api/mcp", content=json.dumps(INITIALIZE), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "simple-invoicing"


def test_trailing_slash_is_registered_directly_not_mounted(client, mcp_principal):
    """`app.mount` would 307 bare /mcp to /mcp/, and several clients drop the
    POST body on a 307."""
    with override_principal(mcp_principal):
        response = client.post(
            "/mcp/", content=json.dumps(INITIALIZE), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 200
    assert response.history == []


def test_mcp_disabled_returns_404(client, mcp_principal, monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(settings, "MCP_ENABLED", False)
    with override_principal(mcp_principal):
        response = _post(client, INITIALIZE)
    assert response.status_code == 404


def test_a_notification_naming_a_request_method_is_still_unanswered(client, mcp_principal):
    """No `id` means no response, whatever the method says."""
    with override_principal(mcp_principal):
        response = _post(client, {"jsonrpc": "2.0", "method": "ping"})
    assert response.status_code == 202
    assert response.content == b""
