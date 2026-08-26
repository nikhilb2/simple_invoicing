"""Discovery documents for the built-in OAuth 2.1 authorization server.

These are the first two requests any MCP client makes. A missing or misspelled
field here does not fail loudly — the connector just never finishes onboarding —
so the field sets are asserted exactly.
"""

import pytest
from fastapi.testclient import TestClient

from app_main import app
from src.api.routes import oauth as oauth_routes
from src.api.routes import well_known as well_known_routes
from src.core.config import settings


def _ensure_routes_mounted() -> None:
    """Mount the OAuth routers if app_main.py has not wired them yet.

    Keeps this suite runnable before and after integration; it is a no-op once
    app_main.py includes the routers itself.
    """
    paths = {getattr(route, "path", None) for route in app.routes}
    if "/api/oauth/token" not in paths:
        app.include_router(oauth_routes.router, prefix="/api/oauth", tags=["oauth"])
    if "/.well-known/oauth-authorization-server" not in paths:
        app.include_router(well_known_routes.router)


_ensure_routes_mounted()


@pytest.fixture
def anon_client():
    return TestClient(app)


PROTECTED_RESOURCE_FIELDS = {
    "resource",
    "authorization_servers",
    "bearer_methods_supported",
    "scopes_supported",
}

AUTHORIZATION_SERVER_FIELDS = {
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "registration_endpoint",
    "revocation_endpoint",
    "scopes_supported",
    "response_types_supported",
    "grant_types_supported",
    "code_challenge_methods_supported",
    "token_endpoint_auth_methods_supported",
    "authorization_response_iss_parameter_supported",
}


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource",
        # RFC 9728 §3.1: a resource URL with a path is probed here first.
        "/.well-known/oauth-protected-resource/mcp",
    ],
)
def test_protected_resource_metadata(anon_client, path):
    response = anon_client.get(path)
    assert response.status_code == 200
    body = response.json()

    assert set(body) == PROTECTED_RESOURCE_FIELDS
    assert body["resource"] == settings.MCP_RESOURCE_URI
    assert body["authorization_servers"] == [settings.PUBLIC_API_BASE_URL.rstrip("/")]
    assert body["bearer_methods_supported"] == ["header"]
    assert body["scopes_supported"] == [
        "invoicing:read",
        "invoicing:write",
        "invoicing:admin",
        "invoicing:send_email",
    ]
    # A protected resource must never advertise offline_access.
    assert "offline_access" not in body["scopes_supported"]


def test_authorization_server_metadata(anon_client):
    response = anon_client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    body = response.json()

    issuer = settings.PUBLIC_API_BASE_URL.rstrip("/")
    assert set(body) == AUTHORIZATION_SERVER_FIELDS
    assert body["issuer"] == issuer
    assert body["authorization_endpoint"] == f"{issuer}/api/oauth/authorize"
    assert body["token_endpoint"] == f"{issuer}/api/oauth/token"
    assert body["registration_endpoint"] == f"{issuer}/api/oauth/register"
    assert body["revocation_endpoint"] == f"{issuer}/api/oauth/revoke"
    assert body["response_types_supported"] == ["code"]
    assert body["grant_types_supported"] == ["authorization_code", "refresh_token"]
    # S256 only — OAuth 2.1 removed "plain".
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["token_endpoint_auth_methods_supported"] == [
        "none",
        "client_secret_post",
        "client_secret_basic",
    ]
    assert body["authorization_response_iss_parameter_supported"] is True
    # Claude appends offline_access to obtain a refresh token, so the AS — unlike
    # the resource — has to advertise it.
    assert "offline_access" in body["scopes_supported"]
    assert body["scopes_supported"] == [
        "invoicing:read",
        "invoicing:write",
        "invoicing:admin",
        "invoicing:send_email",
        "offline_access",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
    ],
)
def test_discovery_caching_and_cors_headers(anon_client, path):
    response = anon_client.get(path)
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.headers["access-control-allow-origin"] == "*"


def test_discovery_is_served_from_origin_root_not_under_api(anon_client):
    """Under /api these documents would be invisible to every client."""
    assert anon_client.get("/api/.well-known/oauth-authorization-server").status_code == 404
    assert anon_client.get("/api/.well-known/oauth-protected-resource").status_code == 404
