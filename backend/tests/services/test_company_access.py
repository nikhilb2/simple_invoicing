"""company_access answers differently per deployment mode; these pin both answers."""

import pytest

from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.company_membership import CompanyMembership
from src.models.user import User, UserRole
from src.models.buyer import Buyer
from src.services.company_access import (
    accessible_company_ids,
    add_membership,
    can_access_company,
    company_role,
    company_scope,
    is_platform_admin,
    legacy_default_company,
)


@pytest.fixture
def shared_hosting(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")


@pytest.fixture
def single_tenant(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")


def _user(db, email: str, role: UserRole = UserRole.staff) -> User:
    user = User(email=email, full_name=email, role=role, hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _company(db, name: str) -> CompanyProfile:
    company = CompanyProfile(name=name, address="")
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def test_single_tenant_reaches_every_company_with_global_role(db_session, single_tenant):
    user = _user(db_session, "a@example.com", UserRole.manager)
    company = _company(db_session, "Acme")

    assert accessible_company_ids(db_session, user) is None
    assert can_access_company(db_session, user, company.id) is True
    assert company_role(db_session, user, company.id) == UserRole.manager


def test_single_tenant_ignores_membership_role(db_session, single_tenant):
    user = _user(db_session, "a@example.com", UserRole.staff)
    company = _company(db_session, "Acme")
    add_membership(db_session, user, company, UserRole.admin)

    # Global role still decides: memberships only count in shared hosting.
    assert company_role(db_session, user, company.id) == UserRole.staff


def test_shared_hosting_without_membership_reaches_nothing(db_session, shared_hosting):
    user = _user(db_session, "a@example.com", UserRole.admin)
    company = _company(db_session, "Acme")

    assert accessible_company_ids(db_session, user) == set()
    assert can_access_company(db_session, user, company.id) is False
    # A global admin is still nobody in a company they are not a member of.
    assert company_role(db_session, user, company.id) is None


def test_shared_hosting_membership_grants_access_with_membership_role(db_session, shared_hosting):
    user = _user(db_session, "a@example.com", UserRole.staff)
    mine = _company(db_session, "Mine")
    theirs = _company(db_session, "Theirs")

    add_membership(db_session, user, mine, UserRole.admin)
    db_session.commit()

    assert accessible_company_ids(db_session, user) == {mine.id}
    assert can_access_company(db_session, user, mine.id) is True
    assert can_access_company(db_session, user, theirs.id) is False
    assert company_role(db_session, user, mine.id) == UserRole.admin
    assert company_role(db_session, user, theirs.id) is None


def test_shared_hosting_users_are_isolated(db_session, shared_hosting):
    alice = _user(db_session, "alice@example.com")
    bob = _user(db_session, "bob@example.com")
    alice_co = _company(db_session, "Alice Co")
    bob_co = _company(db_session, "Bob Co")
    add_membership(db_session, alice, alice_co, UserRole.admin)
    add_membership(db_session, bob, bob_co, UserRole.admin)
    db_session.commit()

    assert accessible_company_ids(db_session, alice) == {alice_co.id}
    assert accessible_company_ids(db_session, bob) == {bob_co.id}
    assert can_access_company(db_session, bob, alice_co.id) is False


def test_add_membership_is_idempotent_and_updates_role(db_session, shared_hosting):
    user = _user(db_session, "a@example.com")
    company = _company(db_session, "Acme")

    first = add_membership(db_session, user, company, UserRole.staff)
    second = add_membership(db_session, user, company, UserRole.manager)
    db_session.commit()

    assert first.id == second.id
    assert db_session.query(CompanyMembership).count() == 1
    assert company_role(db_session, user, company.id) == UserRole.manager


def _ledger(db, name: str, company_id: int | None) -> Buyer:
    ledger = Buyer(name=name, address="", gst="", phone_number="", company_id=company_id)
    db.add(ledger)
    db.commit()
    return ledger


def _scoped_names(db, company_id):
    return sorted(
        name for (name,) in db.query(Buyer.name).filter(company_scope(Buyer.company_id, company_id))
    )


def test_company_scope_keeps_legacy_null_rows_in_single_tenant(db_session, single_tenant):
    a, b = _company(db_session, "A"), _company(db_session, "B")
    _ledger(db_session, "own", a.id)
    _ledger(db_session, "other", b.id)
    _ledger(db_session, "legacy", None)

    assert _scoped_names(db_session, a.id) == ["legacy", "own"]


def test_company_scope_drops_null_rows_in_shared_hosting(db_session, shared_hosting):
    a, b = _company(db_session, "A"), _company(db_session, "B")
    _ledger(db_session, "own", a.id)
    _ledger(db_session, "other", b.id)
    _ledger(db_session, "legacy", None)

    assert _scoped_names(db_session, a.id) == ["own"]
    # No company at all matches nothing, rather than "company_id IS NULL".
    assert _scoped_names(db_session, None) == []


def test_platform_admin_is_an_allowlist_and_empty_means_nobody(db_session, monkeypatch):
    admin = _user(db_session, "Ops@Example.com", UserRole.admin)

    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    assert is_platform_admin(admin) is False

    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", " someone@example.com , ops@example.com ")
    assert is_platform_admin(admin) is True


def test_legacy_default_company_only_exists_in_single_tenant(db_session, monkeypatch):
    first = _company(db_session, "First")
    _company(db_session, "Second")

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    assert legacy_default_company(db_session).id == first.id

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    assert legacy_default_company(db_session) is None
