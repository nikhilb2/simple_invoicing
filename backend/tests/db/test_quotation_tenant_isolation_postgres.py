"""The quotation isolation suite again, on Postgres, as the RLS-constrained role.

Same arrangement as test_rls_tenant_isolation_postgres.py: shared-hosting requests run
as the restricted role, so the database itself is enforcing the tenant, and the
single-tenant test runs on the owner connection.

Skipped when DATABASE_URL is not Postgres.
"""

import sys
from pathlib import Path

import pytest

from app_main import app
from src.core.config import settings
from src.db.session import get_db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from test_quotation_tenant_isolation import *  # noqa: E402,F401,F403 -- tests and fixtures, collected again here
from test_tenant_isolation import act_as, shared_hosting  # noqa: E402,F401
from test_quotation_tenant_isolation import _share_on, single_tenant, two, two_companies  # noqa: E402,F401

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="row-level security needs Postgres",
)


@pytest.fixture
def db_session(clean_rls_db):
    session = clean_rls_db.OwnerSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def request_roles(clean_rls_db):
    roles: list[str] = []

    def _get_db():
        factory = clean_rls_db.AppSession if settings.is_shared_hosting else clean_rls_db.OwnerSession
        db = factory()
        roles.append(db.get_bind().url.username)
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db
    try:
        yield roles
    finally:
        app.dependency_overrides[get_db] = previous


def test_shared_hosting_requests_really_ran_as_the_restricted_role(two, request_roles, clean_rls_db):  # noqa: F811
    assert request_roles and set(request_roles) == {clean_rls_db.role}
