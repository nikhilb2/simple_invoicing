"""End-to-end tests for the OAuth 2.1 authorization server.

Everything asserted here is something an MCP client depends on and which fails
silently when it is wrong: RFC 6749 error codes, PKCE S256, single-use codes,
refresh rotation, loopback redirect matching and audience binding.
"""

import base64
import hashlib
import secrets
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app_main import app
from src.api.deps import get_current_user
from src.api.routes import oauth as oauth_routes
from src.api.routes import well_known as well_known_routes
from src.core.config import settings
from src.core.security import create_access_token, get_password_hash
from src.models.company import CompanyProfile
from src.models.oauth import OAuthAuthorizationCode, OAuthClient, OAuthToken
from src.models.user import User, UserRole
from src.services.oauth import clients as clients_service
from src.services.oauth.tokens import (
    hash_token,
    mint_token,
    now_utc,
    parse_scope,
    resolve_bearer,
)


def _ensure_routes_mounted() -> None:
    """Mount the OAuth routers if app_main.py has not wired them yet."""
    paths = {getattr(route, "path", None) for route in app.routes}
    if "/api/oauth/token" not in paths:
        app.include_router(oauth_routes.router, prefix="/api/oauth", tags=["oauth"])
    if "/.well-known/oauth-authorization-server" not in paths:
        app.include_router(well_known_routes.router)


_ensure_routes_mounted()

RESOURCE = settings.MCP_RESOURCE_URI
ISSUER = settings.PUBLIC_API_BASE_URL.rstrip("/")
DEFAULT_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
FULL_SCOPE = "invoicing:read invoicing:write offline_access"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def client():
    """A TestClient with conftest's blanket get_current_user override removed.

    conftest.py installs that override at import time for the whole suite; the
    consent endpoints have to see the *real* signed-in user, so it is popped here
    and restored afterwards (the pattern from test_mcp_api_token.py).
    """
    saved = app.dependency_overrides.pop(get_current_user, None)
    clients_service.reset_rate_limits()
    try:
        yield TestClient(app)
    finally:
        if saved:
            app.dependency_overrides[get_current_user] = saved


@pytest.fixture
def admin_user(db_session):
    company = CompanyProfile(name="Acme Ltd", address="1 Test Way")
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)

    user = User(
        email="owner@example.com",
        full_name="Owner",
        role=UserRole.admin,
        hashed_password=get_password_hash("secret"),
        active_company_id=company.id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user, company


@pytest.fixture
def staff_user(db_session):
    user = User(
        email="staff@example.com",
        full_name="Staff",
        role=UserRole.staff,
        hashed_password=get_password_hash("secret"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def auth_headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.email)}"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def make_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def register_client(client, **overrides) -> dict:
    payload = {
        "client_name": "Claude",
        "redirect_uris": [DEFAULT_REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    payload.update(overrides)
    response = client.post("/api/oauth/register", json=payload)
    return response


def start_authorize(client, client_id, challenge, *, redirect_uri=DEFAULT_REDIRECT, **overrides):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": FULL_SCOPE,
        "state": "opaque-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RESOURCE,
    }
    params.update(overrides)
    params = {k: v for k, v in params.items() if v is not None}
    return client.get("/api/oauth/authorize", params=params, follow_redirects=False)


def consent(client, user, request_id, company_id, approve=True):
    return client.post(
        "/api/oauth/authorize/decision",
        json={"request_id": request_id, "approve": approve, "company_id": company_id},
        headers=auth_headers(user),
    )


def code_from_redirect(redirect_to: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(redirect_to).query)["code"][0]


def request_id_from_location(location: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(location).query)["request_id"][0]


def full_flow(client, user, company, *, scope=FULL_SCOPE, redirect_uri=DEFAULT_REDIRECT):
    """register -> authorize -> consent -> code -> token. Returns (client_id, verifier, token_body)."""
    registration = register_client(client, redirect_uris=[redirect_uri]).json()
    client_id = registration["client_id"]
    verifier, challenge = make_pkce()

    authorize = start_authorize(
        client, client_id, challenge, redirect_uri=redirect_uri, scope=scope
    )
    assert authorize.status_code == 302
    request_id = request_id_from_location(authorize.headers["location"])

    decision = consent(client, user, request_id, company.id)
    assert decision.status_code == 200, decision.text
    code = code_from_redirect(decision.json()["redirect_to"])

    token = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200, token.text
    return client_id, verifier, token.json(), code


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


def test_register_accepts_json_and_issues_public_client(client):
    response = register_client(client)
    assert response.status_code == 201
    body = response.json()

    assert body["client_id"]
    # A public client (auth method "none") must not be handed a secret.
    assert "client_secret" not in body
    assert body["redirect_uris"] == [DEFAULT_REDIRECT]
    assert body["token_endpoint_auth_method"] == "none"
    assert response.headers["cache-control"] == "no-store"


def test_register_issues_secret_for_confidential_client(client):
    response = register_client(client, token_endpoint_auth_method="client_secret_post")
    assert response.status_code == 201
    assert response.json()["client_secret"]


def test_register_rejects_non_https_non_loopback_redirect(client):
    response = register_client(client, redirect_uris=["http://evil.example.com/cb"])
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_register_accepts_loopback_redirects(client):
    for uri in ("http://127.0.0.1:8765/callback", "http://localhost:1/cb", "http://[::1]:9/cb"):
        response = register_client(client, redirect_uris=[uri])
        assert response.status_code == 201, uri


def test_register_rejects_unknown_grant_type(client):
    response = register_client(client, grant_types=["password"])
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


def test_register_disabled_by_setting(client, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_DCR_ENABLED", False)
    response = register_client(client)
    assert response.status_code == 403
    assert response.json()["error"] == "access_denied"


# --------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------


def test_full_authorization_code_flow(client, db_session, admin_user):
    user, company = admin_user
    client_id, _, token, _ = full_flow(client, user, company)

    assert token["token_type"] == "Bearer"
    assert token["access_token"].startswith("sio_at_")
    assert token["refresh_token"].startswith("sio_rt_")
    assert token["expires_in"] == settings.OAUTH_ACCESS_TOKEN_TTL_MINUTES * 60
    assert set(parse_scope(token["scope"])) == set(parse_scope(FULL_SCOPE))

    principal = resolve_bearer(token["access_token"], db_session)
    assert principal is not None
    assert principal.user_id == user.id
    assert principal.email == user.email
    assert principal.role == "admin"
    # The grant is bound to exactly one company, stamped at consent time.
    assert principal.company_id == company.id
    assert principal.client_id == client_id
    assert "invoicing:read" in principal.scopes


def test_authorization_redirect_carries_state_and_iss(client, admin_user):
    from urllib.parse import parse_qs, urlparse

    user, company = admin_user
    registration = register_client(client).json()
    _, challenge = make_pkce()
    authorize = start_authorize(client, registration["client_id"], challenge)
    request_id = request_id_from_location(authorize.headers["location"])

    redirect_to = consent(client, user, request_id, company.id).json()["redirect_to"]
    query = parse_qs(urlparse(redirect_to).query)
    assert query["state"] == ["opaque-state"]
    # RFC 9207 — we advertise authorization_response_iss_parameter_supported.
    assert query["iss"] == [ISSUER]
    assert query["code"]


def test_authorize_redirects_to_consent_page_with_only_request_id(client, admin_user):
    from urllib.parse import parse_qs, urlparse

    registration = register_client(client).json()
    _, challenge = make_pkce()
    authorize = start_authorize(client, registration["client_id"], challenge)

    assert authorize.status_code == 302
    location = urlparse(authorize.headers["location"])
    assert f"{location.scheme}://{location.netloc}" == settings.PUBLIC_APP_BASE_URL.rstrip("/")
    assert location.path == "/oauth/consent"
    # Nothing security-relevant round-trips through the browser.
    assert set(parse_qs(location.query)) == {"request_id"}


def test_consent_screen_payload(client, admin_user):
    user, company = admin_user
    registration = register_client(client).json()
    _, challenge = make_pkce()
    authorize = start_authorize(client, registration["client_id"], challenge)
    request_id = request_id_from_location(authorize.headers["location"])

    info = client.get(
        f"/api/oauth/authorize/request/{request_id}", headers=auth_headers(user)
    )
    assert info.status_code == 200
    body = info.json()
    assert body["client_name"] == "Claude"
    # The host the code is actually sent to, not the self-asserted name, is what
    # the consent screen asks the user to trust.
    assert body["redirect_uri_host"] == "claude.ai"
    assert [s["scope"] for s in body["scopes"]] == parse_scope(FULL_SCOPE)
    assert all(s["description"] for s in body["scopes"])
    assert {c["id"] for c in body["companies"]} == {company.id}
    assert body["default_company_id"] == company.id


def test_consent_denial_redirects_with_access_denied(client, admin_user):
    from urllib.parse import parse_qs, urlparse

    user, company = admin_user
    registration = register_client(client).json()
    _, challenge = make_pkce()
    authorize = start_authorize(client, registration["client_id"], challenge)
    request_id = request_id_from_location(authorize.headers["location"])

    decision = consent(client, user, request_id, company.id, approve=False)
    assert decision.status_code == 200
    query = parse_qs(urlparse(decision.json()["redirect_to"]).query)
    assert query["error"] == ["access_denied"]
    assert query["state"] == ["opaque-state"]
    assert query["iss"] == [ISSUER]


def test_admin_scope_is_not_granted_to_non_admin(client, db_session, admin_user, staff_user):
    """Scope never escalates beyond the consenting user's own role."""
    _, company = admin_user
    registration = register_client(client).json()
    _, challenge = make_pkce()
    authorize = start_authorize(
        client,
        registration["client_id"],
        challenge,
        scope="invoicing:read invoicing:admin",
    )
    request_id = request_id_from_location(authorize.headers["location"])

    decision = consent(client, staff_user, request_id, company.id)
    assert decision.status_code == 200
    code = code_from_redirect(decision.json()["redirect_to"])

    stored = (
        db_session.query(OAuthAuthorizationCode)
        .filter(OAuthAuthorizationCode.code_hash == hash_token(code))
        .first()
    )
    assert parse_scope(stored.scope) == ["invoicing:read"]


# --------------------------------------------------------------------------
# PKCE
# --------------------------------------------------------------------------


def test_pkce_plain_challenge_is_rejected(client):
    from urllib.parse import parse_qs, urlparse

    registration = register_client(client).json()
    response = start_authorize(
        client, registration["client_id"], "a-plain-verifier", code_challenge_method="plain"
    )
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["error"] == ["invalid_request"]
    assert "S256" in query["error_description"][0]


def test_authorize_requires_code_challenge(client):
    from urllib.parse import parse_qs, urlparse

    registration = register_client(client).json()
    response = start_authorize(client, registration["client_id"], None, code_challenge=None)
    assert response.status_code == 302
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["invalid_request"]


def test_pkce_verifier_must_match_challenge(client, admin_user):
    user, company = admin_user
    registration = register_client(client).json()
    client_id = registration["client_id"]
    _, challenge = make_pkce()

    authorize = start_authorize(client, client_id, challenge)
    request_id = request_id_from_location(authorize.headers["location"])
    code = code_from_redirect(consent(client, user, request_id, company.id).json()["redirect_to"])

    wrong_verifier, _ = make_pkce()
    response = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEFAULT_REDIRECT,
            "client_id": client_id,
            "code_verifier": wrong_verifier,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_pkce_correct_verifier_succeeds(client, admin_user):
    user, company = admin_user
    _, _, token, _ = full_flow(client, user, company)
    assert token["access_token"]


# --------------------------------------------------------------------------
# redirect_uri matching
# --------------------------------------------------------------------------


def test_redirect_uri_must_match_exactly_for_https(client):
    registration = register_client(client).json()
    _, challenge = make_pkce()
    response = start_authorize(
        client,
        registration["client_id"],
        challenge,
        redirect_uri="https://claude.ai/api/mcp/auth_callback_evil",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_loopback_redirect_matches_with_port_ignored(client, admin_user):
    """Claude Code binds an ephemeral port it cannot register (RFC 8252 §7.3)."""
    user, company = admin_user
    registration = register_client(client, redirect_uris=["http://127.0.0.1:8765/callback"]).json()
    client_id = registration["client_id"]
    verifier, challenge = make_pkce()

    ephemeral = "http://127.0.0.1:54321/callback"
    authorize = start_authorize(client, client_id, challenge, redirect_uri=ephemeral)
    assert authorize.status_code == 302

    request_id = request_id_from_location(authorize.headers["location"])
    redirect_to = consent(client, user, request_id, company.id).json()["redirect_to"]
    assert redirect_to.startswith(ephemeral)

    token = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code_from_redirect(redirect_to),
            "redirect_uri": ephemeral,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200, token.text


def test_loopback_port_agnostic_matching_still_requires_same_path(client):
    registration = register_client(client, redirect_uris=["http://127.0.0.1:8765/callback"]).json()
    _, challenge = make_pkce()
    response = start_authorize(
        client,
        registration["client_id"],
        challenge,
        redirect_uri="http://127.0.0.1:54321/somewhere-else",
    )
    assert response.status_code == 400


def test_https_redirect_port_is_not_ignored(client):
    registration = register_client(client, redirect_uris=["https://app.example.com/cb"]).json()
    _, challenge = make_pkce()
    response = start_authorize(
        client, registration["client_id"], challenge, redirect_uri="https://app.example.com:8443/cb"
    )
    assert response.status_code == 400


def test_token_redirect_uri_must_match_the_authorization_request(client, admin_user):
    user, company = admin_user
    registration = register_client(
        client, redirect_uris=[DEFAULT_REDIRECT, "https://claude.ai/other"]
    ).json()
    client_id = registration["client_id"]
    verifier, challenge = make_pkce()

    authorize = start_authorize(client, client_id, challenge)
    request_id = request_id_from_location(authorize.headers["location"])
    code = code_from_redirect(consent(client, user, request_id, company.id).json()["redirect_to"])

    response = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/other",
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


# --------------------------------------------------------------------------
# token endpoint contract
# --------------------------------------------------------------------------


def test_token_endpoint_requires_form_encoding_not_json(client, admin_user):
    """Claude posts form-encoded; a JSON-only parser would 415 and break it."""
    user, company = admin_user
    client_id, verifier, _, _ = full_flow(client, user, company)

    # The form-encoded path already succeeded inside full_flow. A JSON body must
    # produce an RFC 6749 error, never a 422 validation blob.
    response = client.post(
        "/api/oauth/token",
        json={"grant_type": "authorization_code", "client_id": client_id},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_token_response_is_no_store(client, admin_user):
    user, company = admin_user
    registration = register_client(client).json()
    client_id = registration["client_id"]
    verifier, challenge = make_pkce()
    authorize = start_authorize(client, client_id, challenge)
    request_id = request_id_from_location(authorize.headers["location"])
    code = code_from_redirect(consent(client, user, request_id, company.id).json()["redirect_to"])

    response = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEFAULT_REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert response.headers["cache-control"] == "no-store"


def test_unknown_client_gets_invalid_client(client):
    response = client.post(
        "/api/oauth/token",
        data={"grant_type": "authorization_code", "client_id": "nope", "code": "x"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


def test_confidential_client_requires_its_secret(client, admin_user):
    user, company = admin_user
    registration = register_client(
        client, token_endpoint_auth_method="client_secret_post"
    ).json()
    client_id = registration["client_id"]
    secret = registration["client_secret"]
    verifier, challenge = make_pkce()

    authorize = start_authorize(client, client_id, challenge)
    request_id = request_id_from_location(authorize.headers["location"])
    code = code_from_redirect(consent(client, user, request_id, company.id).json()["redirect_to"])

    base = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DEFAULT_REDIRECT,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    bad = client.post("/api/oauth/token", data={**base, "client_secret": "wrong"})
    assert bad.status_code == 401
    assert bad.json()["error"] == "invalid_client"

    good = client.post("/api/oauth/token", data={**base, "client_secret": secret})
    assert good.status_code == 200


def test_client_secret_basic_is_accepted(client, admin_user):
    user, company = admin_user
    registration = register_client(
        client, token_endpoint_auth_method="client_secret_basic"
    ).json()
    client_id = registration["client_id"]
    secret = registration["client_secret"]
    verifier, challenge = make_pkce()

    authorize = start_authorize(client, client_id, challenge)
    request_id = request_id_from_location(authorize.headers["location"])
    code = code_from_redirect(consent(client, user, request_id, company.id).json()["redirect_to"])

    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    response = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEFAULT_REDIRECT,
            "code_verifier": verifier,
        },
        headers={"Authorization": f"Basic {basic}"},
    )
    assert response.status_code == 200, response.text


def test_no_refresh_token_without_offline_access(client, admin_user):
    user, company = admin_user
    _, _, token, _ = full_flow(client, user, company, scope="invoicing:read")
    assert "refresh_token" not in token


# --------------------------------------------------------------------------
# single-use codes and chain revocation
# --------------------------------------------------------------------------


def test_authorization_code_is_single_use_and_replay_revokes_descendants(
    client, db_session, admin_user
):
    user, company = admin_user
    client_id, verifier, token, code = full_flow(client, user, company)

    assert resolve_bearer(token["access_token"], db_session) is not None

    replay = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEFAULT_REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"

    db_session.expire_all()
    # Every token descended from the replayed code is now dead.
    assert resolve_bearer(token["access_token"], db_session) is None
    refresh = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": client_id,
        },
    )
    assert refresh.status_code == 400
    assert refresh.json()["error"] == "invalid_grant"


def test_expired_authorization_code_is_invalid_grant(client, db_session, admin_user):
    user, company = admin_user
    registration = register_client(client).json()
    client_id = registration["client_id"]
    verifier, challenge = make_pkce()
    authorize = start_authorize(client, client_id, challenge)
    request_id = request_id_from_location(authorize.headers["location"])
    code = code_from_redirect(consent(client, user, request_id, company.id).json()["redirect_to"])

    row = (
        db_session.query(OAuthAuthorizationCode)
        .filter(OAuthAuthorizationCode.code_hash == hash_token(code))
        .first()
    )
    row.expires_at = now_utc() - timedelta(seconds=5)
    db_session.commit()

    response = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEFAULT_REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


# --------------------------------------------------------------------------
# refresh rotation
# --------------------------------------------------------------------------


def test_refresh_rotates_and_retires_the_old_token(client, db_session, admin_user):
    user, company = admin_user
    client_id, _, token, _ = full_flow(client, user, company)

    rotated = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": client_id,
        },
    )
    assert rotated.status_code == 200, rotated.text
    body = rotated.json()
    assert body["refresh_token"] != token["refresh_token"]
    assert body["access_token"] != token["access_token"]
    assert resolve_bearer(body["access_token"], db_session) is not None

    old = (
        db_session.query(OAuthToken)
        .filter(OAuthToken.token_hash == hash_token(token["refresh_token"]))
        .first()
    )
    assert old.revoked_at is not None
    new = (
        db_session.query(OAuthToken)
        .filter(OAuthToken.token_hash == hash_token(body["refresh_token"]))
        .first()
    )
    # The rotation lineage is recorded on the replacement.
    assert new.parent_id == old.id


def test_reusing_a_retired_refresh_token_revokes_the_whole_chain(
    client, db_session, admin_user
):
    user, company = admin_user
    client_id, _, token, _ = full_flow(client, user, company)

    rotated = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": client_id,
        },
    ).json()

    reuse = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": client_id,
        },
    )
    assert reuse.status_code == 400
    # RFC 6749 code — Claude branches on this exact string to decide to re-auth.
    assert reuse.json()["error"] == "invalid_grant"

    db_session.expire_all()
    assert resolve_bearer(rotated["access_token"], db_session) is None
    still_alive = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": rotated["refresh_token"],
            "client_id": client_id,
        },
    )
    assert still_alive.status_code == 400
    assert still_alive.json()["error"] == "invalid_grant"


def test_dead_refresh_token_reports_invalid_grant(client, admin_user):
    user, company = admin_user
    client_id, _, _, _ = full_flow(client, user, company)

    response = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": "sio_rt_never-existed",
            "client_id": client_id,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_refresh_cannot_widen_scope(client, admin_user):
    user, company = admin_user
    client_id, _, token, _ = full_flow(
        client, user, company, scope="invoicing:read offline_access"
    )
    response = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": client_id,
            "scope": "invoicing:read invoicing:write",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_scope"


# --------------------------------------------------------------------------
# audience / resource binding
# --------------------------------------------------------------------------


def test_authorize_rejects_a_foreign_resource(client):
    from urllib.parse import parse_qs, urlparse

    registration = register_client(client).json()
    _, challenge = make_pkce()
    response = start_authorize(
        client, registration["client_id"], challenge, resource="https://evil.example.com/mcp"
    )
    assert response.status_code == 302
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["invalid_target"]


def test_resolve_bearer_rejects_a_token_bound_to_another_audience(db_session, admin_user):
    """Audience validation is a MUST — a token minted for someone else is not ours."""
    user, company = admin_user

    good_raw, _ = mint_token(
        db_session,
        token_type="access",
        client_id="c1",
        user_id=user.id,
        company_id=company.id,
        scope="invoicing:read",
        resource=RESOURCE,
    )
    bad_raw, _ = mint_token(
        db_session,
        token_type="access",
        client_id="c1",
        user_id=user.id,
        company_id=company.id,
        scope="invoicing:read",
        resource="https://someone-else.example.com/mcp",
    )
    db_session.commit()

    assert resolve_bearer(good_raw, db_session) is not None
    assert resolve_bearer(bad_raw, db_session) is None


def test_resolve_bearer_rejects_expired_revoked_refresh_and_junk(db_session, admin_user):
    user, company = admin_user

    expired_raw, expired_row = mint_token(
        db_session,
        token_type="access",
        client_id="c1",
        user_id=user.id,
        company_id=company.id,
        scope="invoicing:read",
        resource=RESOURCE,
    )
    expired_row.expires_at = now_utc() - timedelta(minutes=1)

    revoked_raw, revoked_row = mint_token(
        db_session,
        token_type="access",
        client_id="c1",
        user_id=user.id,
        company_id=company.id,
        scope="invoicing:read",
        resource=RESOURCE,
    )
    revoked_row.revoked_at = now_utc()

    refresh_raw, _ = mint_token(
        db_session,
        token_type="refresh",
        client_id="c1",
        user_id=user.id,
        company_id=company.id,
        scope="invoicing:read",
        resource=RESOURCE,
    )
    db_session.commit()

    assert resolve_bearer(expired_raw, db_session) is None
    assert resolve_bearer(revoked_raw, db_session) is None
    # A refresh token is not a bearer credential for the resource.
    assert resolve_bearer(refresh_raw, db_session) is None
    assert resolve_bearer("", db_session) is None
    assert resolve_bearer("sio_at_garbage", db_session) is None
    # An app JWT must never resolve through the OAuth path.
    assert resolve_bearer(create_access_token(user.email), db_session) is None


def test_resolve_bearer_touches_last_used_at(db_session, admin_user):
    user, company = admin_user
    raw, row = mint_token(
        db_session,
        token_type="access",
        client_id="c1",
        user_id=user.id,
        company_id=company.id,
        scope="invoicing:read",
        resource=RESOURCE,
    )
    db_session.commit()
    assert row.last_used_at is None

    assert resolve_bearer(raw, db_session) is not None
    db_session.expire_all()
    refreshed = db_session.query(OAuthToken).filter(OAuthToken.token_hash == hash_token(raw)).first()
    assert refreshed.last_used_at is not None


def test_oauth_access_token_does_not_work_on_the_rest_api(client, db_session, admin_user):
    """OAuth tokens are for /mcp only; the JWT path must keep rejecting them."""
    user, company = admin_user
    _, _, token, _ = full_flow(client, user, company)

    response = client.get(
        "/api/products/", headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------
# revocation + grant management
# --------------------------------------------------------------------------


def test_rfc7009_revocation_of_refresh_kills_the_grant(client, db_session, admin_user):
    user, company = admin_user
    client_id, _, token, _ = full_flow(client, user, company)

    response = client.post(
        "/api/oauth/revoke",
        data={"token": token["refresh_token"], "client_id": client_id},
    )
    assert response.status_code == 200

    db_session.expire_all()
    assert resolve_bearer(token["access_token"], db_session) is None


def test_revocation_of_unknown_token_is_still_200(client):
    registration = register_client(client).json()
    response = client.post(
        "/api/oauth/revoke",
        data={"token": "sio_at_nope", "client_id": registration["client_id"]},
    )
    assert response.status_code == 200


def test_grants_listing_and_revocation(client, db_session, admin_user):
    user, company = admin_user
    client_id, _, token, _ = full_flow(client, user, company)

    listing = client.get("/api/oauth/grants", headers=auth_headers(user))
    assert listing.status_code == 200
    grants = listing.json()
    assert len(grants) == 1
    assert grants[0]["client_id"] == client_id
    assert grants[0]["client_name"] == "Claude"
    assert grants[0]["company_id"] == company.id
    assert grants[0]["company_name"] == "Acme Ltd"

    revoked = client.delete(f"/api/oauth/grants/{client_id}", headers=auth_headers(user))
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] >= 1

    db_session.expire_all()
    assert resolve_bearer(token["access_token"], db_session) is None
    assert client.get("/api/oauth/grants", headers=auth_headers(user)).json() == []


def test_grants_are_scoped_to_the_current_user(client, admin_user, staff_user):
    user, company = admin_user
    full_flow(client, user, company)

    assert client.get("/api/oauth/grants", headers=auth_headers(staff_user)).json() == []


def test_consent_endpoints_require_authentication(client, admin_user):
    user, company = admin_user
    registration = register_client(client).json()
    _, challenge = make_pkce()
    authorize = start_authorize(client, registration["client_id"], challenge)
    request_id = request_id_from_location(authorize.headers["location"])

    assert client.get(f"/api/oauth/authorize/request/{request_id}").status_code == 401
    assert (
        client.post(
            "/api/oauth/authorize/decision",
            json={"request_id": request_id, "approve": True, "company_id": company.id},
        ).status_code
        == 401
    )


def test_expired_authorization_request_reports_410(client, db_session, admin_user):
    """The consent screen distinguishes a spent request from a network failure."""
    from src.models.oauth import OAuthAuthRequest

    user, company = admin_user
    registration = register_client(client).json()
    _, challenge = make_pkce()
    authorize = start_authorize(client, registration["client_id"], challenge)
    request_id = request_id_from_location(authorize.headers["location"])

    row = (
        db_session.query(OAuthAuthRequest)
        .filter(OAuthAuthRequest.request_id == request_id)
        .first()
    )
    row.expires_at = now_utc() - timedelta(minutes=1)
    db_session.commit()

    assert client.get(
        f"/api/oauth/authorize/request/{request_id}", headers=auth_headers(user)
    ).status_code == 410
    assert consent(client, user, request_id, company.id).status_code == 410


def test_authorization_request_is_single_use(client, admin_user):
    user, company = admin_user
    registration = register_client(client).json()
    _, challenge = make_pkce()
    authorize = start_authorize(client, registration["client_id"], challenge)
    request_id = request_id_from_location(authorize.headers["location"])

    assert consent(client, user, request_id, company.id).status_code == 200
    assert consent(client, user, request_id, company.id).status_code == 404


def test_unknown_client_at_authorize(client):
    _, challenge = make_pkce()
    response = start_authorize(client, "not-a-client", challenge)
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


def test_authorize_rejects_unsupported_response_type(client):
    from urllib.parse import parse_qs, urlparse

    registration = register_client(client).json()
    _, challenge = make_pkce()
    response = start_authorize(client, registration["client_id"], challenge, response_type="token")
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["error"] == ["unsupported_response_type"]


def test_authorize_rejects_unknown_scope(client):
    from urllib.parse import parse_qs, urlparse

    registration = register_client(client).json()
    _, challenge = make_pkce()
    response = start_authorize(client, registration["client_id"], challenge, scope="invoicing:god")
    assert response.status_code == 302
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["invalid_scope"]


def test_authorize_rejects_scope_outside_the_registration(client):
    from urllib.parse import parse_qs, urlparse

    registration = register_client(client, scope="invoicing:read").json()
    _, challenge = make_pkce()
    response = start_authorize(
        client, registration["client_id"], challenge, scope="invoicing:read invoicing:write"
    )
    assert response.status_code == 302
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == ["invalid_scope"]


def test_client_cannot_redeem_another_clients_code(client, db_session, admin_user):
    user, company = admin_user
    victim = register_client(client).json()
    attacker = register_client(client, client_name="Attacker").json()
    verifier, challenge = make_pkce()

    authorize = start_authorize(client, victim["client_id"], challenge)
    request_id = request_id_from_location(authorize.headers["location"])
    code = code_from_redirect(consent(client, user, request_id, company.id).json()["redirect_to"])

    response = client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DEFAULT_REDIRECT,
            "client_id": attacker["client_id"],
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
