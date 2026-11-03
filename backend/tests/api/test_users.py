"""Tests for the user routes (issue #485).

Covers admin create (password stored hashed and never returned),
the staff default role, non-admin 403s on create, manager list
access versus other roles, duplicate email returning 409, schema
validation of email and required fields, and unauthenticated
access, using the shared TestClient plus db_session fixtures from
tests/conftest.py.

Note on the short password case: UserCreate enforces a minimum password
length of 8, so the schema rejects short passwords with 422. The tests
below pin both the rejection and that an 8-character password is accepted.
"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from app_main import app
from src.api.deps import get_current_user
from src.core.security import verify_password
from src.models.user import User, UserRole


def _seed_user(db_session, user_id, email, role=UserRole.staff):
    user = User(
        id=user_id,
        email=email,
        full_name="Seeded User",
        hashed_password="not-a-real-hash",
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    return user


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


def _create_payload(email="new@example.com", **overrides):
    payload = {
        "email": email,
        "full_name": "New User",
        "password": "correct horse battery staple",
        "role": "manager",
    }
    payload.update(overrides)
    return payload


def _create_user(client, **overrides):
    return client.post("/api/users/", json=_create_payload(**overrides))


def test_admin_can_create_user_and_password_is_hashed_not_returned(
    client, db_session
):
    response = _create_user(client)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["email"] == "new@example.com"
    assert created["full_name"] == "New User"
    assert created["role"] == "manager"
    assert "hashed_password" not in created
    assert "password" not in created

    stored = (
        db_session.query(User).filter(User.email == "new@example.com").one()
    )
    assert stored.hashed_password != "correct horse battery staple"
    assert verify_password("correct horse battery staple", stored.hashed_password)


def test_create_without_role_defaults_to_staff(client, db_session):
    payload = _create_payload()
    del payload["role"]

    response = client.post("/api/users/", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "staff"


def test_non_admin_gets_403_on_create(client, db_session):
    for role in (UserRole.manager, UserRole.staff):
        with _as_role(role):
            response = _create_user(client, email=f"{role.value}@example.com")
            assert response.status_code == 403

    assert db_session.query(User).count() == 0


def test_manager_can_list_and_staff_cannot(client, db_session):
    _seed_user(db_session, 1, "alice@example.com", role=UserRole.admin)
    _seed_user(db_session, 2, "bob@example.com", role=UserRole.staff)

    with _as_role(UserRole.manager):
        response = client.get("/api/users/")
        assert response.status_code == 200, response.text
        assert sorted(item["email"] for item in response.json()) == [
            "alice@example.com",
            "bob@example.com",
        ]
        assert all(
            "hashed_password" not in item for item in response.json()
        )

    with _as_role(UserRole.staff):
        response = client.get("/api/users/")
        assert response.status_code == 403


def test_admin_can_list(client, db_session):
    _seed_user(db_session, 1, "alice@example.com", role=UserRole.admin)

    response = client.get("/api/users/")
    assert response.status_code == 200, response.text
    assert [item["email"] for item in response.json()] == ["alice@example.com"]


def test_duplicate_email_returns_409(client, db_session):
    first = _create_user(client)
    assert first.status_code == 200, first.text

    second = _create_user(client)
    assert second.status_code == 409, second.text
    assert "already exists" in second.json()["detail"]

    assert (
        db_session.query(User).filter(User.email == "new@example.com").count()
        == 1
    )


def test_invalid_email_returns_422(client):
    response = _create_user(client, email="not-an-email")
    assert response.status_code == 422, response.text


def test_missing_full_name_returns_422(client):
    payload = _create_payload()
    del payload["full_name"]

    response = client.post("/api/users/", json=payload)
    assert response.status_code == 422, response.text


def test_short_password_is_rejected_by_the_schema(client, db_session):
    response = _create_user(client, password="x")
    assert response.status_code == 422, response.text
    assert db_session.query(User).count() == 0


def test_password_at_minimum_length_is_accepted(client, db_session):
    response = _create_user(client, password="12345678")
    assert response.status_code == 200, response.text

    stored = (
        db_session.query(User).filter(User.email == "new@example.com").one()
    )
    assert verify_password("12345678", stored.hashed_password)


def test_unauthenticated_request_gets_401():
    saved_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = TestClient(app).get("/api/users/")
        assert response.status_code == 401
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_current_user] = saved_override
