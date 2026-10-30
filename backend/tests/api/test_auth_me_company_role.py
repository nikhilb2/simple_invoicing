"""/auth/me reports the role in the active company and platform-admin status.

A shared-hosting signup is global staff but admin of the company they created, so
the UI cannot gate on `role` alone.
"""

import pytest

from app_main import app
from src.api.deps import get_current_user
from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.user import User, UserRole
from src.services.company_access import add_membership


def _user(db, email, role=UserRole.staff) -> User:
    user = User(email=email, full_name="T", hashed_password="x", role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _company(db, name) -> CompanyProfile:
    company = CompanyProfile(name=name, address="")
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _me(client, user: User) -> dict:
    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = client.get("/api/auth/me")
    finally:
        app.dependency_overrides[get_current_user] = previous
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "ops@example.com")


def test_shared_creator_is_company_admin_but_global_staff(client, db_session, shared):
    user = _user(db_session, "owner@example.com")
    company = _company(db_session, "Acme")
    add_membership(db_session, user, company, UserRole.admin)
    user.active_company_id = company.id
    db_session.commit()

    body = _me(client, user)

    assert body["role"] == "staff"
    assert body["company_role"] == "admin"
    assert body["can_manage_platform"] is False


def test_shared_staff_member_is_company_staff(client, db_session, shared):
    user = _user(db_session, "clerk@example.com")
    company = _company(db_session, "Acme")
    add_membership(db_session, user, company, UserRole.staff)
    user.active_company_id = company.id
    db_session.commit()

    assert _me(client, user)["company_role"] == "staff"


def test_shared_without_company_or_access_has_no_company_role(client, db_session, shared):
    user = _user(db_session, "new@example.com")
    assert _me(client, user)["company_role"] is None

    other = _company(db_session, "Other")
    user.active_company_id = other.id  # no membership
    db_session.commit()
    assert _me(client, user)["company_role"] is None


def test_shared_platform_admin_email_can_manage_platform(client, db_session, shared):
    user = _user(db_session, "Ops@Example.com")

    assert _me(client, user)["can_manage_platform"] is True


def test_single_tenant_values_follow_global_role(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    admin = _user(db_session, "a@example.com", UserRole.admin)
    staff = _user(db_session, "s@example.com", UserRole.staff)

    admin_body = _me(client, admin)
    assert admin_body["role"] == "admin"
    assert admin_body["company_role"] == "admin"
    assert admin_body["can_manage_platform"] is True

    staff_body = _me(client, staff)
    assert staff_body["company_role"] == "staff"
    assert staff_body["can_manage_platform"] is False
