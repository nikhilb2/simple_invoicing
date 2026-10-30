"""Email + password signup: register, verify, resend, forgot / reset, login rules.

Mail never leaves the process: platform_mail._deliver is replaced by a list, and
the links are read back out of the plain-text body the way a person would.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app_main import app
from src.api.deps import get_current_user
from src.core import analytics
from src.core.config import settings
from src.core.security import (
    create_access_token,
    create_purpose_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
)
from src.models.user import User, UserRole
from src.services import platform_mail


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


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(platform_mail, "_deliver", sent.append)
    return sent


@pytest.fixture
def shared(monkeypatch):
    """Shared hosting with a platform mailer: password signup is on."""
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_FROM_EMAIL", "no-reply@si.test")
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://app.si.test")


@pytest.fixture
def single_with_smtp(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://app.si.test")


@pytest.fixture
def frozen_clock(monkeypatch):
    from src.core import rate_limit

    now = [1000.0]
    monkeypatch.setattr(rate_limit, "_clock", lambda: now[0])
    return now


@pytest.fixture
def real_auth(monkeypatch):
    """Use the real get_current_user instead of conftest's fixed admin."""
    monkeypatch.delitem(app.dependency_overrides, get_current_user)


def _user(
    db,
    email="owner@example.com",
    password="GoodPass@123",
    verified=True,
    active=True,
    role=UserRole.staff,
):
    user = User(
        email=email,
        full_name="Owner",
        role=role,
        hashed_password=get_password_hash(password) if password else None,
        email_verified_at=datetime.now(timezone.utc) if verified else None,
        is_active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _body(msg) -> str:
    return msg.get_body(preferencelist=("plain",)).get_content()


def _link_token(msg, path: str) -> str:
    match = re.search(rf"https://app\.si\.test{re.escape(path)}\?token=([A-Za-z0-9_\-\.]+)", _body(msg))
    assert match, _body(msg)
    return match.group(1)


def _find(events, name):
    return [e for e in events.captured if e[0] == name]


def _register(client, email="new@example.com", password="Signup@123", name="New Person", **kw):
    return client.post("/api/auth/register", json={"email": email, "password": password, "full_name": name}, **kw)


# ---------------------------------------------------------------------------
# /auth/config
# ---------------------------------------------------------------------------

def test_config_single_tenant_defaults(client, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", None)
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", None)

    response = client.get("/api/auth/config")

    assert response.status_code == 200
    assert response.json() == {"password_signup_enabled": False, "password_reset_enabled": False, "providers": []}


def test_config_shared_hosting_everything_on(client, shared, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "secret")

    body = client.get("/api/auth/config").json()

    assert body == {
        "password_signup_enabled": True,
        "password_reset_enabled": True,
        "providers": [{"id": "google", "name": "Google"}],
    }


def test_config_shared_hosting_without_smtp_has_no_password_signup(client, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", None)
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", None)

    body = client.get("/api/auth/config").json()

    assert body["password_signup_enabled"] is False
    assert body["password_reset_enabled"] is False


def test_config_single_tenant_lists_google_for_login_and_offers_reset(client, single_with_smtp, monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "OAUTH_GOOGLE_CLIENT_SECRET", "secret")

    body = client.get("/api/auth/config").json()

    # Signup stays off outside shared hosting; Google login for existing users
    # and password reset do not depend on the mode.
    assert body == {
        "password_signup_enabled": False,
        "password_reset_enabled": True,
        "providers": [{"id": "google", "name": "Google"}],
    }


def test_signup_routes_are_not_in_the_openapi_schema(client):
    paths = client.get("/openapi.json").json()["paths"]

    for hidden in (
        "/api/auth/config",
        "/api/auth/register",
        "/api/auth/verify-email",
        "/api/auth/resend-verification",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/oauth/{provider}/login",
        "/api/auth/oauth/{provider}/callback",
        "/api/auth/oauth/exchange",
    ):
        assert hidden not in paths, hidden
    assert "/api/auth/login" in paths


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def test_register_is_404_when_signup_is_off(client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", "smtp.test")

    assert _register(client).status_code == 404
    assert outbox == []


def test_register_is_404_in_shared_hosting_without_smtp(client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", None)

    assert _register(client).status_code == 404


def test_register_creates_unverified_staff_user_and_mails_link(client, db_session, shared, outbox, events):
    response = _register(client, email="  New.Person@Example.COM ")

    assert response.status_code == 202
    user = db_session.query(User).one()
    assert user.email == "new.person@example.com"
    assert user.role == UserRole.staff
    assert user.email_verified_at is None
    assert user.is_active is True
    assert verify_password("Signup@123", user.hashed_password)

    (msg,) = outbox
    assert msg["To"] == "new.person@example.com"
    assert "no-reply@si.test" in msg["From"]
    _link_token(msg, "/verify-email")
    # The HTML alternative carries the same link.
    assert "https://app.si.test/verify-email?token=" in msg.get_body(preferencelist=("html",)).get_content()

    (_, distinct_id, props), = _find(events, "user_signed_up")
    assert distinct_id == "new.person@example.com"
    assert props["method"] == "password"


def test_register_existing_verified_address_answers_the_same_and_changes_nothing(client, db_session, shared, outbox):
    _user(db_session, email="owner@example.com")
    fresh = _register(client, email="fresh@example.com")
    outbox.clear()

    existing = _register(client, email="Owner@Example.com", password="Attacker@999")

    assert existing.status_code == fresh.status_code == 202
    assert existing.json() == fresh.json()
    assert outbox == []
    owner = db_session.query(User).filter(User.email == "owner@example.com").one()
    db_session.refresh(owner)
    assert verify_password("GoodPass@123", owner.hashed_password)
    assert db_session.query(User).count() == 2


def test_register_existing_unverified_replaces_the_unproven_claim(client, db_session, shared, outbox):
    _user(db_session, email="pending@example.com", password="First@1234", verified=False)

    response = _register(client, email="PENDING@example.com", password="Second@1234")

    assert response.status_code == 202
    (msg,) = outbox
    assert msg["To"] == "pending@example.com"
    user = db_session.query(User).one()
    db_session.refresh(user)
    assert verify_password("Second@1234", user.hashed_password)


def test_pre_registered_address_cannot_be_hijacked_through_the_owners_own_link(client, db_session, shared, outbox):
    # A stranger registers the owner's address first, and the owner gets that link.
    _register(client, email="owner@example.com", password="Attacker@123")
    strangers_link = _link_token(outbox[-1], "/verify-email")
    # The owner then signs up themselves and gets a link of their own.
    _register(client, email="owner@example.com", password="Owner@12345")
    owners_link = _link_token(outbox[-1], "/verify-email")

    # The stranger's link died when the owner's registration replaced the password.
    assert client.post("/api/auth/verify-email", json={"token": strangers_link}).status_code == 400
    assert client.post("/api/auth/verify-email", json={"token": owners_link}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "Attacker@123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "Owner@12345"}).status_code == 200


def test_verify_link_dies_when_the_password_changes(client, db_session, shared, outbox):
    _register(client, email="owner@example.com")
    link = _link_token(outbox[-1], "/verify-email")
    user = db_session.query(User).one()
    user.hashed_password = get_password_hash("Changed@1234")
    db_session.commit()

    assert client.post("/api/auth/verify-email", json={"token": link}).status_code == 400


def test_register_matches_legacy_mixed_case_address(client, db_session, shared, outbox):
    _user(db_session, email="Legacy.User@Example.com")

    assert _register(client, email="legacy.user@example.com").status_code == 202
    assert db_session.query(User).count() == 1


def test_register_validates_password_length(client, shared, outbox):
    assert _register(client, password="short").status_code == 422


# ---------------------------------------------------------------------------
# Verify / resend
# ---------------------------------------------------------------------------

def test_verify_email_link_verifies(client, db_session, shared, outbox, events):
    _register(client)
    token = _link_token(outbox[0], "/verify-email")

    response = client.post("/api/auth/verify-email", json={"token": token})

    assert response.status_code == 200
    user = db_session.query(User).one()
    assert user.email_verified_at is not None
    assert len(_find(events, "email_verified")) == 1
    # Clicking it again is harmless.
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200


def test_verify_email_rejects_garbage(client, shared):
    response = client.post("/api/auth/verify-email", json={"token": "not-a-jwt"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_token"


def test_verify_email_rejects_expired_token(client, db_session, shared):
    from src.core.security import password_fingerprint

    user = _user(db_session, verified=False)
    token = create_purpose_token(
        str(user.id), "verify", timedelta(seconds=-5), {"email": user.email, "pwd": password_fingerprint(user.hashed_password)}
    )

    response = client.post("/api/auth/verify-email", json={"token": token})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_token"


def test_resend_verification(client, db_session, shared, outbox):
    _user(db_session, email="pending@example.com", verified=False)
    _user(db_session, email="done@example.com", verified=True)

    for email in ("pending@example.com", "done@example.com", "nobody@example.com"):
        response = client.post("/api/auth/resend-verification", json={"email": email})
        assert response.status_code == 202
        assert response.json() == {"detail": "If that address is waiting to be confirmed, a new link is on its way."}

    (msg,) = outbox
    assert msg["To"] == "pending@example.com"


def test_resend_verification_is_404_without_smtp(client, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", None)

    assert client.post("/api/auth/resend-verification", json={"email": "a@example.com"}).status_code == 404


# ---------------------------------------------------------------------------
# Token type confusion
# ---------------------------------------------------------------------------

def test_session_tokens_are_not_verify_or_reset_tokens(client, db_session, shared):
    user = _user(db_session, verified=False)

    for token in (create_access_token(user.email), create_refresh_token(user.email)):
        assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 400
        assert (
            client.post("/api/auth/reset-password", json={"token": token, "new_password": "Changed@123"}).status_code
            == 400
        )
    # Even an access token whose sub is the user's id, as a purpose token's is.
    forged = jwt.encode(
        {"sub": str(user.id), "email": user.email, "type": "access", "exp": datetime.utcnow() + timedelta(hours=1)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    assert client.post("/api/auth/verify-email", json={"token": forged}).status_code == 400


def test_verify_and_reset_tokens_are_not_interchangeable(client, db_session, shared):
    user = _user(db_session, verified=False)
    verify = create_purpose_token(str(user.id), "verify", timedelta(hours=1), {"email": user.email})
    reset = create_purpose_token(str(user.id), "reset", timedelta(hours=1), {"email": user.email, "pwd": "none"})

    assert client.post("/api/auth/verify-email", json={"token": reset}).status_code == 400
    assert client.post("/api/auth/reset-password", json={"token": verify, "new_password": "Changed@123"}).status_code == 400


def test_verify_and_reset_tokens_are_not_session_tokens(client, db_session, shared, real_auth):
    user = _user(db_session, verified=False)
    for token_type in ("verify", "reset"):
        # sub = the email, which is what get_current_user looks a session up by.
        token = create_purpose_token(user.email, token_type, timedelta(hours=1), {"email": user.email})

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        refreshed = client.post("/api/auth/refresh", json={"refresh_token": token})

        assert me.status_code == 401
        assert refreshed.status_code == 401


def test_extra_claims_cannot_override_the_access_type():
    token = create_access_token("x@example.com", extra_claims={"type": "refresh", "sub": "y@example.com"})
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    assert claims["type"] == "access"
    assert claims["sub"] == "x@example.com"


def test_purpose_tokens_cannot_be_session_typed():
    with pytest.raises(ValueError):
        create_purpose_token("1", "access", timedelta(hours=1))


# ---------------------------------------------------------------------------
# Forgot / reset
# ---------------------------------------------------------------------------

def test_forgot_password_is_404_without_smtp(client, monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", None)

    assert client.post("/api/auth/forgot-password", json={"email": "a@example.com"}).status_code == 404


def test_forgot_password_answers_the_same_for_unknown_addresses(client, db_session, shared, outbox):
    _user(db_session, email="owner@example.com")

    known = client.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    (msg,) = outbox
    assert msg["To"] == "owner@example.com"


def test_reset_password_flow_and_single_use(client, db_session, shared, outbox):
    _user(db_session, email="owner@example.com", password="OldPass@123")
    client.post("/api/auth/forgot-password", json={"email": "OWNER@example.com"})
    (msg,) = outbox
    # Sent to the stored address, not the one typed.
    assert msg["To"] == "owner@example.com"
    token = _link_token(msg, "/reset-password")

    first = client.post("/api/auth/reset-password", json={"token": token, "new_password": "NewPass@456"})
    again = client.post("/api/auth/reset-password", json={"token": token, "new_password": "Another@789"})

    assert first.status_code == 200
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "invalid_token"
    login = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "NewPass@456"})
    assert login.status_code == 200


def test_reset_token_dies_when_password_changes_another_way(client, db_session, shared, outbox):
    user = _user(db_session, email="owner@example.com", password="OldPass@123")
    client.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    token = _link_token(outbox[0], "/reset-password")

    user.hashed_password = get_password_hash("ChangedElsewhere@1")
    db_session.commit()

    response = client.post("/api/auth/reset-password", json={"token": token, "new_password": "NewPass@456"})
    assert response.status_code == 400


def test_reset_for_google_only_account_sets_a_password_once(client, db_session, shared, outbox):
    _user(db_session, email="google@example.com", password=None)
    client.post("/api/auth/forgot-password", json={"email": "google@example.com"})
    token = _link_token(outbox[0], "/reset-password")

    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "NewPass@456"}).status_code == 200
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "Other@4567"}).status_code == 400


def test_reset_proves_the_address(client, db_session, shared, outbox):
    _user(db_session, email="pending@example.com", verified=False)
    client.post("/api/auth/forgot-password", json={"email": "pending@example.com"})
    token = _link_token(outbox[0], "/reset-password")

    client.post("/api/auth/reset-password", json={"token": token, "new_password": "NewPass@456"})

    user = db_session.query(User).one()
    db_session.refresh(user)
    assert user.email_verified_at is not None


def test_unicode_lookalike_address_does_not_reach_an_account(client, db_session, shared, outbox):
    _user(db_session, email="admin@example.com")

    # U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE lowercases to "i̇" in Unicode;
    # it must not be folded onto "admin".
    client.post("/api/auth/forgot-password", json={"email": "admİn@example.com"})
    _register(client, email="admİn@example.com")

    assert all(msg["To"] != "admin@example.com" for msg in outbox)
    login = client.post("/api/auth/login", json={"email": "admİn@example.com", "password": "GoodPass@123"})
    assert login.status_code == 401


# ---------------------------------------------------------------------------
# Login rules
# ---------------------------------------------------------------------------

def test_unverified_login_is_403_in_shared_hosting(client, db_session, shared):
    _user(db_session, verified=False)

    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "GoodPass@123"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "email_not_verified"


def test_unverified_login_with_wrong_password_is_still_401(client, db_session, shared):
    _user(db_session, verified=False)

    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "Wrong@0000"})

    assert response.status_code == 401


def test_unverified_login_is_allowed_in_single_tenant(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    _user(db_session, verified=False)

    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "GoodPass@123"})

    assert response.status_code == 200


@pytest.mark.parametrize("mode", ["single_tenant", "shared_hosting"])
def test_inactive_login_is_403(client, db_session, monkeypatch, mode):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", mode)
    _user(db_session, active=False)

    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "GoodPass@123"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "account_inactive"


def test_account_without_password_gets_invalid_credentials(client, db_session):
    _user(db_session, password=None)

    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "Anything@123"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_login_ignores_ascii_case_for_legacy_addresses(client, db_session):
    _user(db_session, email="Mixed.Case@Example.com")

    response = client.post("/api/auth/login", json={"email": "mixed.case@example.com", "password": "GoodPass@123"})

    assert response.status_code == 200
    # Sessions are keyed to the stored address, which get_current_user matches exactly.
    claims = jwt.decode(response.json()["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert claims["sub"] == "Mixed.Case@Example.com"


def test_unknown_address_still_costs_a_bcrypt_round(client, monkeypatch):
    from src.core import security

    calls = []
    original = security.pwd_context.verify
    monkeypatch.setattr(security.pwd_context, "verify", lambda *a, **k: calls.append(1) or original(*a, **k))

    client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Whatever@123"})

    assert calls, "an unknown address must not skip the password check"


def test_reset_password_ends_existing_sessions(client, db_session, shared, outbox):
    _user(db_session, email="owner@example.com", password="OldPass@123")
    hijacked = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "OldPass@123"}).json()
    # Refresh tokens carry whole-second iat; step past the second they were issued in.
    import time as _time

    _time.sleep(1.1)
    client.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    token = _link_token(outbox[0], "/reset-password")
    client.post("/api/auth/reset-password", json={"token": token, "new_password": "NewPass@456"})

    stale = client.post("/api/auth/refresh", json={"refresh_token": hijacked["refresh_token"]})
    fresh = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "NewPass@456"}).json()

    assert stale.status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code == 200


def test_refresh_is_refused_for_an_inactive_account(client, db_session):
    user = _user(db_session, active=False)

    response = client.post("/api/auth/refresh", json={"refresh_token": create_refresh_token(user.email)})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Change password (first password for Google-only accounts)
# ---------------------------------------------------------------------------

def test_change_password_without_current_sets_first_password(client, db_session):
    # conftest's current user is test@example.com.
    _user(db_session, email="test@example.com", password=None)

    response = client.post(
        "/api/auth/change-password",
        json={"new_password": "FirstPass@1"},
        headers={"Authorization": f"Bearer {create_access_token('test@example.com')}"},
    )

    assert response.status_code == 200
    user = db_session.query(User).one()
    db_session.refresh(user)
    assert verify_password("FirstPass@1", user.hashed_password)


@pytest.mark.parametrize(
    "credential",
    [
        "si_live_0123456789abcdef",  # a company API key
        "static-mcp-token",  # MCP_API_TOKEN
        create_access_token("test@example.com", extra_claims={"src": "mcp", "tool": "x"}),
        None,
    ],
)
def test_first_password_needs_a_real_sign_in(client, db_session, credential):
    _user(db_session, email="test@example.com", password=None)
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}

    response = client.post("/api/auth/change-password", json={"new_password": "FirstPass@1"}, headers=headers)

    assert response.status_code == 403
    user = db_session.query(User).one()
    db_session.refresh(user)
    assert user.hashed_password is None


def test_change_password_still_requires_current_when_one_exists(client, db_session):
    _user(db_session, email="test@example.com", password="OldPass@123")

    response = client.post("/api/auth/change-password", json={"new_password": "NewPass@456"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect"


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------

def test_login_is_rate_limited_per_ip(client, frozen_clock):
    statuses = [
        client.post("/api/auth/login", json={"email": f"u{i}@example.com", "password": "Whatever@1"}).status_code
        for i in range(31)
    ]

    assert statuses[:30] == [401] * 30
    assert statuses[30] == 429
    assert client.post("/api/auth/login", json={"email": "x@example.com", "password": "y"}).status_code == 429


def test_failed_logins_from_one_ip_lock_that_ip_out_of_that_account(client, db_session, frozen_clock):
    _user(db_session)
    attacker = {"X-Forwarded-For": "198.51.100.7"}
    for _ in range(10):
        response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "Wrong@0000"}, headers=attacker)
        assert response.status_code == 401

    blocked = client.post(
        "/api/auth/login", json={"email": "OWNER@example.com", "password": "GoodPass@123"}, headers=attacker
    )
    owner = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "GoodPass@123"},
        headers={"X-Forwarded-For": "203.0.113.99"},
    )

    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "rate_limited"
    assert blocked.headers["Retry-After"]
    # The stranger's guessing does not lock the owner out.
    assert owner.status_code == 200
    # And the allowance comes back with time.
    frozen_clock[0] += 120
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "GoodPass@123"}, headers=attacker).status_code == 200


def test_failed_logins_are_capped_per_email_across_ips(client, db_session, frozen_clock):
    _user(db_session)
    for i in range(100):
        response = client.post(
            "/api/auth/login",
            json={"email": "owner@example.com", "password": "Wrong@0000"},
            headers={"X-Forwarded-For": f"10.0.{i // 250}.{i % 250}"},
        )
        assert response.status_code == 401

    response = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "Wrong@0000"},
        headers={"X-Forwarded-For": "203.0.113.200"},
    )
    assert response.status_code == 429


def test_flooding_the_bucket_table_does_not_unblock_a_key(frozen_clock):
    from src.core.rate_limit import TokenBucket

    bucket = TokenBucket(capacity=2, refill_per_second=0.001, max_keys=100)
    bucket.hit("victim")
    bucket.hit("victim")
    assert bucket.blocked("victim")

    for i in range(1000):
        bucket.hit(f"junk-{i}")

    assert bucket.blocked("victim")
    assert len(bucket._buckets) <= 200


def test_successful_logins_do_not_spend_the_email_allowance(client, db_session):
    _user(db_session)
    for i in range(15):
        response = client.post(
            "/api/auth/login",
            json={"email": "owner@example.com", "password": "GoodPass@123"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        )
        assert response.status_code == 200


def test_register_is_rate_limited_per_email(client, shared, outbox, frozen_clock):
    statuses = [
        _register(client, email="target@example.com", headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code
        for i in range(4)
    ]

    assert statuses == [202, 202, 202, 429]
    # Re-registering an unverified address re-sends -- but never more than the
    # per-address allowance, whatever IP it comes from.
    assert len(outbox) == 3


def test_mail_endpoints_are_rate_limited_per_ip(client, shared, outbox, frozen_clock):
    statuses = [
        client.post("/api/auth/forgot-password", json={"email": f"user{i}@example.com"}).status_code
        for i in range(11)
    ]

    assert statuses[:10] == [202] * 10
    assert statuses[10] == 429
    assert client.post("/api/auth/resend-verification", json={"email": "z@example.com"}).status_code == 429


def test_oauth_exchange_is_rate_limited_per_ip(client, frozen_clock):
    statuses = [client.post("/api/auth/oauth/exchange", json={"code": f"bogus{i}"}).status_code for i in range(21)]

    assert statuses[:20] == [400] * 20
    assert statuses[20] == 429
