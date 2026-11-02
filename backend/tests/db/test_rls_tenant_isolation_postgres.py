"""The whole tenant-isolation suite again, on Postgres, as the RLS-constrained role.

tests/api/test_tenant_isolation.py drives every shared-hosting flow through the
app -- signup into a company, one of every document, API keys, share links,
OAuth consent -- on SQLite, where row-level security does not exist. Collected
here with get_db pointed at the restricted role, the same tests prove those
flows also work when the database enforces the tenant: any request path that
queried a protected table without setting the company would see nothing, or be
refused on write, and fail here.

Its single-tenant tests run on the owner connection instead, as a single-tenant
deployment does. ``db_session`` (used by the tests for setup and for checking
the database directly) is always the owner, so it sees every row.

Skipped when DATABASE_URL is not Postgres.
"""

import sys
from pathlib import Path

import pytest

from app_main import app
from src.core.config import settings
from src.db.session import get_db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from test_tenant_isolation import *  # noqa: E402,F401,F403 -- tests and fixtures, collected again here
import test_tenant_isolation as _iso  # noqa: E402

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
    """Serve each request from the right role; records which role served it."""
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


def test_the_isolation_suite_was_collected_here():
    collected = [name for name in vars(_iso) if name.startswith("test_")]
    assert len(collected) > 20


def test_shared_hosting_requests_really_ran_as_the_restricted_role(tenants, request_roles, clean_rls_db):
    assert request_roles and set(request_roles) == {clean_rls_db.role}
