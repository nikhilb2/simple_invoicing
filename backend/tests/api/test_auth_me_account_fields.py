"""/auth/me reports whether the account has a password and a verified address."""

from datetime import datetime, timezone

from app_main import app
from src.api.deps import get_current_user
from src.core.security import get_password_hash, verify_password
from src.models.user import User, UserRole


def _me_as(client, user: User) -> dict:
    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = client.get("/api/auth/me")
    finally:
        app.dependency_overrides[get_current_user] = previous
    assert response.status_code == 200
    return response.json()


def test_me_reports_password_and_verified_email(client):
    user = User(
        id=7,
        email="owner@example.com",
        full_name="Owner",
        role=UserRole.admin,
        hashed_password=get_password_hash("Secret@123"),
        email_verified_at=datetime.now(timezone.utc),
    )

    body = _me_as(client, user)

    assert body["has_password"] is True
    assert body["email_verified"] is True


def test_me_reports_google_only_unverified_account(client):
    user = User(
        id=8,
        email="new@example.com",
        full_name="New",
        role=UserRole.staff,
        hashed_password=None,
        email_verified_at=None,
    )

    body = _me_as(client, user)

    assert body["has_password"] is False
    assert body["email_verified"] is False


def test_verify_password_rejects_account_without_password():
    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False
