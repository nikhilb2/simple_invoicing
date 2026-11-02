"""Tests for the API key routes (issue #480).

Covers creation returning the raw key once while the list only exposes
the prefix, non-admin 403s on create, list and delete, delete behaviour
including unknown ids and keys belonging to another company, the verify
endpoint, and newest first list ordering, using the shared TestClient
plus db_session fixtures from tests/conftest.py.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app_main import app
from src.api.deps import get_current_user
from src.models.api_key import ApiKey
from src.models.company import CompanyProfile
from src.models.user import User, UserRole


def _seed_company(db_session, company_id, name):
    company = CompanyProfile(
        id=company_id,
        name=name,
        address="",
        gst="",
        phone_number="",
        currency_code="USD",
        email="",
        website="",
        bank_name="",
        branch_name="",
        account_name="",
        account_number="",
        ifsc_code="",
    )
    db_session.add(company)
    db_session.commit()
    return company


def _seed_admin_user(db_session):
    admin = User(
        id=1,
        email="admin@example.com",
        full_name="Admin User",
        hashed_password="not-a-real-hash",
        role=UserRole.admin,
    )
    db_session.add(admin)
    db_session.commit()
    return admin


def _seed_key(db_session, *, company_id, name, created_at):
    key = ApiKey(
        company_id=company_id,
        created_by_user_id=1,
        name=name,
        key_prefix="si_abcdef123",
        key_encrypted="encrypted-placeholder",
        expires_at=datetime(2027, 6, 1, tzinfo=timezone.utc),
        is_active=True,
        created_at=created_at,
    )
    db_session.add(key)
    db_session.commit()
    return key


@contextmanager
def _as_role(role):
    """Swap the conftest admin override for another role, then restore it."""
    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="test@example.com", role=role
    )
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous


def _create_key(client, name="CI key"):
    response = client.post(
        "/api/api-keys/",
        json={"name": name, "expires_at": "2027-06-01T00:00:00Z"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _list_keys(client):
    response = client.get("/api/api-keys/")
    assert response.status_code == 200, response.text
    return response.json()


def test_create_returns_raw_key_once_and_list_hides_it(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_admin_user(db_session)

    created = _create_key(client)
    raw_key = created["raw_key"]
    assert raw_key.startswith("si_")
    assert len(raw_key) == 3 + 64
    assert created["key_prefix"] == raw_key[:12]
    assert created["name"] == "CI key"
    assert created["is_active"] is True
    assert created["created_by_user_id"] == 1

    listed = _list_keys(client)
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]
    assert listed[0]["key_prefix"] == created["key_prefix"]
    assert "raw_key" not in listed[0]


def test_non_admin_gets_403_on_create_list_and_delete(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_admin_user(db_session)
    key = _seed_key(
        db_session,
        company_id=1,
        name="admin key",
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )

    with _as_role(UserRole.staff):
        create_response = client.post(
            "/api/api-keys/",
            json={"name": "staff key", "expires_at": "2027-06-01T00:00:00Z"},
        )
        assert create_response.status_code == 403

        list_response = client.get("/api/api-keys/")
        assert list_response.status_code == 403

        delete_response = client.delete(f"/api/api-keys/{key.id}")
        assert delete_response.status_code == 403

    assert db_session.query(ApiKey).filter(ApiKey.id == key.id).first() is not None


def test_delete_removes_key(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_admin_user(db_session)
    created = _create_key(client)

    response = client.delete(f"/api/api-keys/{created['id']}")
    assert response.status_code == 200
    assert response.json()["detail"] == "API key deleted"

    assert _list_keys(client) == []
    assert (
        db_session.query(ApiKey).filter(ApiKey.id == created["id"]).first() is None
    )


def test_delete_unknown_id_returns_404(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_admin_user(db_session)

    response = client.delete("/api/api-keys/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "API key not found"


def test_delete_key_from_another_company_returns_404(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")
    _seed_admin_user(db_session)
    other_key = _seed_key(
        db_session,
        company_id=2,
        name="other company key",
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )

    response = client.delete(f"/api/api-keys/{other_key.id}")
    assert response.status_code == 404

    assert (
        db_session.query(ApiKey).filter(ApiKey.id == other_key.id).first()
        is not None
    )


def test_verify_returns_valid_and_company_id(client, db_session):
    _seed_company(db_session, 1, "Company A")

    response = client.get("/api/api-keys/verify")
    assert response.status_code == 200
    assert response.json() == {"valid": True, "company_id": 1}


def test_list_is_newest_first(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_admin_user(db_session)
    _seed_key(
        db_session,
        company_id=1,
        name="oldest",
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    _seed_key(
        db_session,
        company_id=1,
        name="newest",
        created_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc),
    )
    _seed_key(
        db_session,
        company_id=1,
        name="middle",
        created_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
    )

    listed = _list_keys(client)
    assert [item["name"] for item in listed] == ["newest", "middle", "oldest"]
    assert all("raw_key" not in item for item in listed)


def test_unauthenticated_request_gets_401():
    saved_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = TestClient(app).get("/api/api-keys/")
        assert response.status_code == 401
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_current_user] = saved_override
