"""Tests for the SMTP config routes (issue #482).

Covers create and list never exposing the password, encrypted storage of
the password on create and on update, duplicate host plus username handling,
update, delete and activate behaviour including unknown id 404s, activate
deactivating all other configs, the admin only role gate on every route, and
POST /test with the mail sender mocked, using the shared TestClient plus
db_session fixtures from tests/conftest.py and the smtplib patch style from
tests/services/test_mail.py.
"""

from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from app_main import app
from src.api.deps import get_current_user
from src.models.smtp_config import SMTPConfig
from src.models.user import User, UserRole


def _payload(name="Primary SMTP", host="smtp.example.com", username="user"):
    return {
        "name": name,
        "host": host,
        "port": 587,
        "username": username,
        "password": "secret-password",
        "from_email": "billing@example.com",
        "from_name": "Example Billing",
        "use_starttls": True,
    }


def _create_config(client, **overrides):
    payload = _payload(**overrides)
    response = client.post("/api/smtp-configs/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _stored_config(db_session, config_id):
    db_session.expire_all()
    return (
        db_session.query(SMTPConfig).filter(SMTPConfig.id == config_id).first()
    )


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


def test_create_returns_config_without_password_and_stores_it_encrypted(
    client, db_session
):
    created = _create_config(client)

    assert created["name"] == "Primary SMTP"
    assert created["host"] == "smtp.example.com"
    assert created["port"] == 587
    assert created["username"] == "user"
    assert created["from_email"] == "billing@example.com"
    assert created["from_name"] == "Example Billing"
    assert created["use_starttls"] is True
    assert created["is_active"] is False
    assert "password" not in created
    assert "_password" not in created

    stored = _stored_config(db_session, created["id"])
    assert stored is not None
    assert stored._password != "secret-password"
    assert "secret-password" not in stored._password
    assert stored.password == "secret-password"


def test_list_never_exposes_password(client, db_session):
    first = _create_config(client, name="First", username="first")
    second = _create_config(
        client, name="Second", host="smtp2.example.com", username="second"
    )

    response = client.get("/api/smtp-configs/")
    assert response.status_code == 200, response.text
    listed = response.json()
    assert len(listed) == 2
    assert {item["id"] for item in listed} == {first["id"], second["id"]}
    assert all("password" not in item for item in listed)
    assert all("_password" not in item for item in listed)


def test_create_duplicate_host_and_username_returns_400(client):
    _create_config(client)

    response = client.post("/api/smtp-configs/", json=_payload(name="Copy"))
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_update_changes_fields_and_keeps_password_hidden(client):
    created = _create_config(client)

    response = client.put(
        f"/api/smtp-configs/{created['id']}",
        json={"name": "Renamed SMTP", "port": 465},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["name"] == "Renamed SMTP"
    assert updated["port"] == 465
    assert updated["host"] == "smtp.example.com"
    assert "password" not in updated
    assert "_password" not in updated


def test_update_password_is_stored_encrypted(client, db_session):
    created = _create_config(client)

    response = client.put(
        f"/api/smtp-configs/{created['id']}",
        json={"password": "rotated-password"},
    )
    assert response.status_code == 200, response.text
    assert "password" not in response.json()

    stored = _stored_config(db_session, created["id"])
    assert stored._password != "rotated-password"
    assert "rotated-password" not in stored._password
    assert stored.password == "rotated-password"


def test_update_duplicate_host_and_username_returns_400(client):
    _create_config(client, name="First", username="first")
    second = _create_config(
        client,
        name="Second",
        host="smtp2.example.com",
        username="second",
    )

    response = client.put(
        f"/api/smtp-configs/{second['id']}",
        json={"host": "smtp.example.com", "username": "first"},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_update_unknown_id_returns_404(client):
    response = client.put("/api/smtp-configs/999999", json={"name": "Nope"})
    assert response.status_code == 404
    assert response.json()["detail"] == "SMTP configuration not found"


def test_delete_inactive_config(client, db_session):
    created = _create_config(client)

    response = client.delete(f"/api/smtp-configs/{created['id']}")
    assert response.status_code == 200
    assert response.json()["detail"] == "SMTP configuration deleted successfully"
    assert _stored_config(db_session, created["id"]) is None


def test_delete_active_config_returns_400(client, db_session):
    created = _create_config(client)

    activate = client.post(f"/api/smtp-configs/{created['id']}/activate")
    assert activate.status_code == 200, activate.text

    response = client.delete(f"/api/smtp-configs/{created['id']}")
    assert response.status_code == 400
    assert "active" in response.json()["detail"]
    assert _stored_config(db_session, created["id"]) is not None


def test_delete_unknown_id_returns_404(client):
    response = client.delete("/api/smtp-configs/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "SMTP configuration not found"


def test_activate_makes_one_config_active_and_deactivates_others(client):
    first = _create_config(client, name="First", username="first")
    second = _create_config(
        client,
        name="Second",
        host="smtp2.example.com",
        username="second",
    )

    response = client.post(f"/api/smtp-configs/{first['id']}/activate")
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True

    listed = client.get("/api/smtp-configs/").json()
    by_id = {item["id"]: item for item in listed}
    assert by_id[first["id"]]["is_active"] is True
    assert by_id[second["id"]]["is_active"] is False

    response = client.post(f"/api/smtp-configs/{second['id']}/activate")
    assert response.status_code == 200, response.text

    listed = client.get("/api/smtp-configs/").json()
    by_id = {item["id"]: item for item in listed}
    assert by_id[first["id"]]["is_active"] is False
    assert by_id[second["id"]]["is_active"] is True


def test_activate_unknown_id_returns_404(client):
    response = client.post("/api/smtp-configs/999999/activate")
    assert response.status_code == 404
    assert response.json()["detail"] == "SMTP configuration not found"


def test_non_admin_gets_403_on_every_route(client, db_session):
    created = _create_config(client)

    with _as_role(UserRole.staff):
        create_response = client.post("/api/smtp-configs/", json=_payload())
        assert create_response.status_code == 403

        list_response = client.get("/api/smtp-configs/")
        assert list_response.status_code == 403

        update_response = client.put(
            f"/api/smtp-configs/{created['id']}", json={"name": "Staff edit"}
        )
        assert update_response.status_code == 403

        activate_response = client.post(
            f"/api/smtp-configs/{created['id']}/activate"
        )
        assert activate_response.status_code == 403

        test_response = client.post(
            "/api/smtp-configs/test",
            json={"id": created["id"], "to": "to@example.com"},
        )
        assert test_response.status_code == 403

        delete_response = client.delete(f"/api/smtp-configs/{created['id']}")
        assert delete_response.status_code == 403

    assert _stored_config(db_session, created["id"]) is not None


def test_unauthenticated_request_gets_401():
    saved_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = TestClient(app).get("/api/smtp-configs/")
        assert response.status_code == 401
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_current_user] = saved_override


def test_post_test_sends_with_mocked_smtp(client):
    created = _create_config(client)

    with patch("smtplib.SMTP") as mock_smtp_cls, patch(
        "smtplib.SMTP_SSL"
    ) as mock_smtp_ssl_cls:
        mock_server = mock_smtp_cls.return_value

        response = client.post(
            "/api/smtp-configs/test",
            json={"id": created["id"], "to": "to@example.com"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["detail"] == "Test email sent successfully"
        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
        mock_smtp_ssl_cls.assert_not_called()
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "secret-password")
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()


def test_post_test_unknown_id_returns_404(client):
    response = client.post(
        "/api/smtp-configs/test", json={"id": 999999, "to": "to@example.com"}
    )
    assert response.status_code == 404


def test_post_test_sender_failure_returns_400(client):
    created = _create_config(client)

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.side_effect = Exception("connection refused")
        response = client.post(
            "/api/smtp-configs/test",
            json={"id": created["id"], "to": "to@example.com"},
        )

    assert response.status_code == 400
    assert "Failed to send test email" in response.json()["detail"]


def test_post_test_template_unknown_id_returns_404(client):
    response = client.post(
        "/api/smtp-configs/test-template",
        json={
            "id": 999999,
            "to": "to@example.com",
            "template_name": "invoice_email",
        },
    )
    assert response.status_code == 404
