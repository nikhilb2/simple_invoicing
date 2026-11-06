"""get_current_user refuses deactivated accounts and pre-reset access tokens.

/auth/refresh already stopped minting new tokens for both; these tests pin
that an access token already in hand stops working too, at once, rather than
running on until it expires.
"""

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app_main import app
from src.api.deps import get_current_user
from src.core.config import settings
from src.core.security import create_access_token, decode_token, get_password_hash
from src.models.user import User, UserRole


@pytest.fixture
def real_auth(monkeypatch):
    """Use the real get_current_user instead of conftest's fixed admin."""
    monkeypatch.delitem(app.dependency_overrides, get_current_user)


def _user(db, *, active=True, sessions_valid_after=None) -> User:
    user = User(
        email="owner@example.com",
        full_name="Owner",
        role=UserRole.admin,
        hashed_password=get_password_hash("GoodPass@123"),
        email_verified_at=datetime.now(timezone.utc),
        is_active=active,
        sessions_valid_after=sessions_valid_after,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _me(client, token):
    return client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})


def _token_without_iat(email: str) -> str:
    """An access token shaped like the ones issued before iat was added."""
    expire = datetime.utcnow() + timedelta(minutes=5)
    return jwt.encode(
        {"sub": email, "exp": expire, "type": "access"},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def test_access_tokens_carry_iat():
    claims = decode_token(create_access_token("owner@example.com"))
    assert isinstance(claims["iat"], int)


def test_extra_claims_cannot_override_iat():
    claims = decode_token(create_access_token("owner@example.com", extra_claims={"iat": 1}))
    assert claims["iat"] > 1


def test_active_user_with_a_fresh_token_is_accepted(client, db_session, real_auth):
    _user(db_session)
    assert _me(client, create_access_token("owner@example.com")).status_code == 200


def test_deactivated_user_is_refused(client, db_session, real_auth):
    _user(db_session, active=False)
    response = _me(client, create_access_token("owner@example.com"))
    assert response.status_code == 401


def test_token_issued_before_the_session_cutoff_is_refused(client, db_session, real_auth):
    issued_before = create_access_token("owner@example.com")
    # iat is whole seconds; put the cutoff clearly after it.
    _user(db_session, sessions_valid_after=datetime.now(timezone.utc) + timedelta(seconds=2))
    assert _me(client, issued_before).status_code == 401


def test_token_issued_after_the_session_cutoff_is_accepted(client, db_session, real_auth):
    _user(db_session, sessions_valid_after=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert _me(client, create_access_token("owner@example.com")).status_code == 200


def test_legacy_token_without_iat_is_accepted_while_no_cutoff_exists(client, db_session, real_auth):
    _user(db_session)
    assert _me(client, _token_without_iat("owner@example.com")).status_code == 200


def test_legacy_token_without_iat_is_refused_once_a_cutoff_exists(client, db_session, real_auth):
    _user(db_session, sessions_valid_after=datetime.now(timezone.utc) - timedelta(days=1))
    assert _me(client, _token_without_iat("owner@example.com")).status_code == 401


def test_password_reset_ends_access_tokens_already_issued(client, db_session, real_auth, monkeypatch):
    from src.services import platform_mail

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_FROM_EMAIL", "no-reply@si.test")
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://app.si.test")
    sent = []
    monkeypatch.setattr(platform_mail, "_deliver", sent.append)

    _user(db_session)
    stolen = client.post(
        "/api/auth/login", json={"email": "owner@example.com", "password": "GoodPass@123"}
    ).json()["access_token"]
    assert _me(client, stolen).status_code == 200

    # The cutoff and iat are compared in whole seconds.
    import re
    import time

    time.sleep(1.1)
    client.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    body = sent[0].get_body(preferencelist=("plain",)).get_content()
    token = re.search(r"/reset-password\?token=([A-Za-z0-9_\-\.]+)", body).group(1)
    assert client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "NewPass@456"}
    ).status_code == 200

    assert _me(client, stolen).status_code == 401
