"""Sign in with Google: the Authlib flow, user resolution and the one-time code.

Nothing here touches the network. Most tests swap the Authlib client for a fake
that hands back a chosen set of ID-token claims; the last group drives the REAL
Authlib client with its discovery document pre-loaded and only the token
endpoint and ID-token parsing stubbed, to prove the state / nonce / PKCE plumbing
-- the CSRF defence -- actually holds.
"""

import hashlib
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from authlib.integrations.base_client import OAuthError
from starlette.responses import RedirectResponse

from src.core import analytics
from src.core.config import settings
from src.core.security import get_password_hash, verify_password
from src.models.oauth_login_code import OAuthLoginCode
from src.models.user import User, UserRole
from src.models.user_identity import UserIdentity
from src.services import auth_providers

APP = "https://app.si.test"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class RecordingClient:
    def __init__(self):
        self.captured = []

    def capture(self, event, distinct_id=None, properties=None, disable_geoip=None):
        self.captured.append((event, distinct_id, properties or {}))

    def set(self, distinct_id=None, properties=None):
        pass

    def capture_exception(self, *args, **kwargs):
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


class FakeGoogle:
    """Stands in for Authlib's StarletteOAuth2App."""

    def __init__(self):
        self.userinfo = None
        self.error: Exception | None = None
        self.redirect_uris = []

    async def authorize_redirect(self, request, redirect_uri=None, **kwargs):
        self.redirect_uris.append(redirect_uri)
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?state=fake", status_code=302)

    async def authorize_access_token(self, request, **kwargs):
        if self.error is not None:
            raise self.error
        return {"access_token": "at", "id_token": "it", "userinfo": dict(self.userinfo)}


@pytest.fixture
def google_configured(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", APP)
    auth_providers.reset_registry()


@pytest.fixture
def shared(monkeypatch, google_configured):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")


@pytest.fixture
def single(monkeypatch, google_configured):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")


@pytest.fixture
def google(monkeypatch, google_configured):
    fake = FakeGoogle()
    fake.userinfo = {
        "sub": "google-sub-1",
        "email": "person@gmail.com",
        "email_verified": True,
        "name": "Google Person",
    }
    real_get_client = auth_providers.get_client
    monkeypatch.setattr(
        auth_providers,
        "get_client",
        lambda provider: fake if real_get_client(provider) is not None else None,
    )
    return fake


def _user(db, email="person@gmail.com", password="GoodPass@123", verified=True, active=True):
    user = User(
        email=email,
        full_name="Existing",
        role=UserRole.staff,
        hashed_password=get_password_hash(password) if password else None,
        email_verified_at=datetime.now(timezone.utc) if verified else None,
        is_active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _sign_in(client, next_path="/invoices"):
    """login then callback, as the browser would. Returns the callback's Location."""
    start = client.get("/api/auth/oauth/google/login", params={"next": next_path}, follow_redirects=False)
    assert start.status_code == 302
    done = client.get("/api/auth/oauth/google/callback?code=x&state=fake", follow_redirects=False)
    assert done.status_code == 302
    return done.headers["location"]


def _query(location):
    parts = urlsplit(location)
    return f"{parts.scheme}://{parts.netloc}{parts.path}", {k: v[0] for k, v in parse_qs(parts.query).items()}


def _find(events, name):
    return [e for e in events.captured if e[0] == name]


# ---------------------------------------------------------------------------
# Login redirect
# ---------------------------------------------------------------------------

def test_login_redirects_to_google_with_the_app_origin_callback(client, shared, google):
    response = client.get("/api/auth/oauth/google/login?next=/invoices", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.google.com/")
    assert google.redirect_uris == [f"{APP}/api/auth/oauth/google/callback"]
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("si_oauth_state=")
    assert "samesite=lax" in cookie.lower()
    assert "httponly" in cookie.lower()


def test_unknown_provider_is_404(client, shared, google):
    assert client.get("/api/auth/oauth/github/login", follow_redirects=False).status_code == 404
    assert client.get("/api/auth/oauth/github/callback", follow_redirects=False).status_code == 404


def test_unconfigured_google_is_404(client, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", None)
    auth_providers.reset_registry()

    assert client.get("/api/auth/oauth/google/login", follow_redirects=False).status_code == 404


def test_login_redirect_failure_lands_on_login_error(client, shared, google):
    async def boom(*args, **kwargs):
        raise RuntimeError("discovery unreachable")

    google.authorize_redirect = boom

    response = client.get("/api/auth/oauth/google/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == f"{APP}/login?error=oauth_failed"


# ---------------------------------------------------------------------------
# next= validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "unsafe",
    [
        "//evil.example",
        "/\\evil.example",
        "https://evil.example/",
        "http:/evil.example",
        "javascript:alert(1)",
        "/\t/evil.example",
        "/\n/evil.example",
        "evil.example",
        "",
        "/" + "a" * 3000,
    ],
)
def test_unsafe_next_is_replaced_with_root(client, shared, google, unsafe):
    location = _sign_in(client, next_path=unsafe)

    base, query = _query(location)
    assert base == f"{APP}/auth/callback"
    assert query["next"] == "/"


def test_safe_next_survives_the_round_trip(client, shared, google):
    location = _sign_in(client, next_path="/invoices/42?tab=items")

    _, query = _query(location)
    assert query["next"] == "/invoices/42?tab=items"


# ---------------------------------------------------------------------------
# User resolution
# ---------------------------------------------------------------------------

def test_new_user_is_created_verified_without_password(client, db_session, shared, google, events):
    location = _sign_in(client)

    base, query = _query(location)
    assert base == f"{APP}/auth/callback"
    user = db_session.query(User).one()
    assert user.email == "person@gmail.com"
    assert user.full_name == "Google Person"
    assert user.role == UserRole.staff
    assert user.hashed_password is None
    assert user.email_verified_at is not None
    identity = db_session.query(UserIdentity).one()
    assert (identity.user_id, identity.provider, identity.provider_subject) == (user.id, "google", "google-sub-1")
    (_, distinct_id, props), = _find(events, "user_signed_up")
    assert distinct_id == "person@gmail.com"
    assert props["method"] == "google"
    assert _find(events, "user_logged_in") == []

    tokens = client.post("/api/auth/oauth/exchange", json={"code": query["code"]})
    assert tokens.status_code == 200
    assert set(tokens.json()) == {"access_token", "refresh_token", "token_type"}


def test_existing_password_user_is_linked_by_verified_email(client, db_session, shared, google, events):
    existing = _user(db_session, email="Person@Gmail.com")

    _sign_in(client)

    assert db_session.query(User).count() == 1
    identity = db_session.query(UserIdentity).one()
    assert identity.user_id == existing.id
    db_session.refresh(existing)
    assert verify_password("GoodPass@123", existing.hashed_password)
    (_, _, props), = _find(events, "user_logged_in")
    assert props["method"] == "google"
    assert _find(events, "user_signed_up") == []


def test_linking_an_unverified_account_ends_the_squatters_sessions(client, db_session, monkeypatch, google):
    from src.core.security import create_refresh_token

    # Single tenant lets the unverified squatter sign in; shared hosting drops
    # the password on link, and must end that session too.
    squatter = _user(db_session, email="person@gmail.com", password="Squatter@123", verified=False)
    held = create_refresh_token(squatter.email)
    time.sleep(1.1)
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")

    _sign_in(client)

    assert client.post("/api/auth/refresh", json={"refresh_token": held}).status_code == 401


def test_linking_an_unverified_account_verifies_it_and_drops_the_unproven_password(client, db_session, shared, google):
    # Someone registered this address without ever proving it. Google now proves
    # it belongs to the person signing in; the stranger's password must not survive.
    squatter = _user(db_session, email="person@gmail.com", password="Squatter@123", verified=False)

    _sign_in(client)

    db_session.refresh(squatter)
    assert squatter.email_verified_at is not None
    assert squatter.hashed_password is None
    login = client.post("/api/auth/login", json={"email": "person@gmail.com", "password": "Squatter@123"})
    assert login.status_code == 401


def test_linked_identity_wins_over_email(client, db_session, shared, google):
    user = _user(db_session, email="old-address@example.com")
    db_session.add(UserIdentity(user_id=user.id, provider="google", provider_subject="google-sub-1", email="old"))
    db_session.commit()

    location = _sign_in(client)

    _, query = _query(location)
    assert "code" in query
    assert db_session.query(User).count() == 1


def test_second_google_identity_for_the_same_account_is_refused(client, db_session, shared, google):
    user = _user(db_session, email="person@gmail.com")
    db_session.add(UserIdentity(user_id=user.id, provider="google", provider_subject="previous-holder", email="x"))
    db_session.commit()

    location = _sign_in(client)

    assert location == f"{APP}/login?error=oauth_failed"
    assert db_session.query(UserIdentity).count() == 1


def test_unverified_google_email_is_rejected(client, db_session, shared, google):
    google.userinfo["email_verified"] = False
    _user(db_session, email="person@gmail.com")

    location = _sign_in(client)

    assert location == f"{APP}/login?error=email_not_verified"
    assert db_session.query(UserIdentity).count() == 0


def test_missing_email_verified_claim_is_rejected(client, db_session, shared, google):
    del google.userinfo["email_verified"]

    assert _sign_in(client) == f"{APP}/login?error=email_not_verified"
    assert db_session.query(User).count() == 0


def test_signup_disabled_outside_shared_hosting(client, db_session, single, google):
    location = _sign_in(client)

    assert location == f"{APP}/login?error=signup_disabled"
    assert db_session.query(User).count() == 0


def test_existing_user_can_sign_in_with_google_in_single_tenant(client, db_session, single, google):
    _user(db_session, email="person@gmail.com")

    _, query = _query(_sign_in(client))

    assert client.post("/api/auth/oauth/exchange", json={"code": query["code"]}).status_code == 200


def test_inactive_user_is_refused(client, db_session, shared, google):
    _user(db_session, email="person@gmail.com", active=False)

    assert _sign_in(client) == f"{APP}/login?error=account_inactive"


def test_authlib_error_lands_on_oauth_failed(client, db_session, shared, google):
    google.error = OAuthError(error="access_denied", description="user said no")

    assert _sign_in(client) == f"{APP}/login?error=oauth_failed"
    assert db_session.query(User).count() == 0


def test_token_without_id_token_claims_is_refused(client, db_session, shared, google):
    async def no_id_token(request, **kwargs):
        return {"access_token": "at"}

    google.authorize_access_token = no_id_token

    assert _sign_in(client) == f"{APP}/login?error=oauth_failed"


# ---------------------------------------------------------------------------
# The one-time code
# ---------------------------------------------------------------------------

def test_code_is_single_use(client, db_session, shared, google):
    _, query = _query(_sign_in(client))

    first = client.post("/api/auth/oauth/exchange", json={"code": query["code"]})
    second = client.post("/api/auth/oauth/exchange", json={"code": query["code"]})

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "invalid_code"


def test_code_expires(client, db_session, shared, google):
    _, query = _query(_sign_in(client))
    row = db_session.query(OAuthLoginCode).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    response = client.post("/api/auth/oauth/exchange", json={"code": query["code"]})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_code"


def test_code_lives_sixty_seconds_and_is_stored_hashed(client, db_session, shared, google):
    before = datetime.now(timezone.utc)
    _, query = _query(_sign_in(client))

    row = db_session.query(OAuthLoginCode).one()
    assert row.code_hash == hashlib.sha256(query["code"].encode()).hexdigest()
    assert row.code_hash != query["code"]
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    assert timedelta(seconds=55) < expires - before <= timedelta(seconds=65)


def test_code_only_works_in_the_browser_that_signed_in(client, db_session, shared, google):
    from fastapi.testclient import TestClient
    from app_main import app

    # The attacker signs in to their own account and stops at the redirect...
    _, query = _query(_sign_in(client))
    # ...then gets a victim's browser, which never went through the flow, to
    # exchange the code.
    victim = TestClient(app)
    response = victim.post("/api/auth/oauth/exchange", json={"code": query["code"]})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_code"


def test_unknown_code_is_invalid(client):
    response = client.post("/api/auth/oauth/exchange", json={"code": "never-issued"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_code"


def test_exchange_refuses_a_user_deactivated_after_the_callback(client, db_session, shared, google):
    _, query = _query(_sign_in(client))
    user = db_session.query(User).one()
    user.is_active = False
    db_session.commit()

    response = client.post("/api/auth/oauth/exchange", json={"code": query["code"]})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "account_inactive"


# ---------------------------------------------------------------------------
# The real Authlib client: state, nonce and PKCE (no network)
# ---------------------------------------------------------------------------

@pytest.fixture
def real_google(shared):
    client = auth_providers.get_client("google")
    # Pretend discovery already ran, so Authlib never fetches it.
    client.server_metadata.update(
        {
            "issuer": "https://accounts.google.com",
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            "_loaded_at": time.time(),
        }
    )
    return client


def test_registry_registers_google_by_oidc_discovery(real_google):
    assert real_google._server_metadata_url == auth_providers.GOOGLE_DISCOVERY_URL
    assert real_google.client_kwargs["scope"] == "openid email profile"
    assert real_google.client_kwargs["code_challenge_method"] == "S256"


def test_real_authlib_round_trip_checks_state_nonce_and_pkce(client, db_session, real_google, monkeypatch):
    seen = {}

    async def fake_fetch_access_token(redirect_uri=None, **kwargs):
        seen["fetch"] = {"redirect_uri": redirect_uri, **kwargs}
        return {"access_token": "at", "id_token": "header.payload.sig", "token_type": "Bearer"}

    async def fake_parse_id_token(token, nonce, claims_options=None, claims_cls=None, leeway=120):
        seen["nonce"] = nonce
        seen["claims_options"] = claims_options
        return {"sub": "real-sub", "email": "real@gmail.com", "email_verified": True, "name": "Real"}

    monkeypatch.setattr(real_google, "fetch_access_token", fake_fetch_access_token)
    monkeypatch.setattr(real_google, "parse_id_token", fake_parse_id_token)

    start = client.get("/api/auth/oauth/google/login?next=/ledgers", follow_redirects=False)
    assert start.status_code == 302
    _, auth_params = _query(start.headers["location"])
    assert auth_params["redirect_uri"] == f"{APP}/api/auth/oauth/google/callback"
    assert auth_params["code_challenge_method"] == "S256"
    assert auth_params["scope"] == "openid email profile"
    state, nonce = auth_params["state"], auth_params["nonce"]

    # A forged state (a CSRF attempt, or a callback from someone else's flow).
    forged = client.get(f"/api/auth/oauth/google/callback?code=c&state={state}x", follow_redirects=False)
    assert forged.headers["location"] == f"{APP}/login?error=oauth_failed"
    assert "fetch" not in seen

    # The forged attempt above consumed nothing; start over for the real one,
    # since its callback also cleared the pending next path.
    start = client.get("/api/auth/oauth/google/login?next=/ledgers", follow_redirects=False)
    _, auth_params = _query(start.headers["location"])
    state, nonce = auth_params["state"], auth_params["nonce"]

    done = client.get(f"/api/auth/oauth/google/callback?code=the-code&state={state}", follow_redirects=False)

    base, query = _query(done.headers["location"])
    assert base == f"{APP}/auth/callback"
    assert query["next"] == "/ledgers"
    assert seen["nonce"] == nonce
    assert seen["fetch"]["code"] == "the-code"
    assert seen["fetch"]["code_verifier"]  # PKCE verifier came back out of the cookie
    assert seen["fetch"]["redirect_uri"] == f"{APP}/api/auth/oauth/google/callback"
    # The ID token must be for OUR client id, from Google's issuer.
    assert seen["claims_options"]["aud"] == {"essential": True, "value": settings.OAUTH_GOOGLE_CLIENT_ID}
    assert "https://accounts.google.com" in seen["claims_options"]["iss"]["values"]

    # The same state cannot be replayed.
    replay = client.get(f"/api/auth/oauth/google/callback?code=the-code&state={state}", follow_redirects=False)
    assert replay.headers["location"] == f"{APP}/login?error=oauth_failed"


def test_callback_without_the_state_cookie_is_refused(client, db_session, real_google):
    # The attacker's browser started the flow; the victim's never did, so the
    # victim's request carries no matching state.
    response = client.get("/api/auth/oauth/google/callback?code=c&state=whatever", follow_redirects=False)

    assert response.headers["location"] == f"{APP}/login?error=oauth_failed"
    assert db_session.query(User).count() == 0
