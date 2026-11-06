"""The signup migrations upgrade a pre-signup database without locking anyone out.

Runs the real migration files against Postgres, inside a throwaway schema built
to the pre-signup shape of ``users`` and ``company_profiles``, all in one
transaction that is rolled back. Skipped when DATABASE_URL is not Postgres: the
rest of the suite builds its schema on SQLite, where these migrations never run.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.core.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
SIGNUP_MIGRATIONS = [
    "20261030000001_add_signup_columns_to_users",
    "20261030000002_create_company_memberships",
    "20261030000003_create_user_identities_and_oauth_login_codes",
]

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="signup migrations are Postgres DDL",
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pre_signup_conn():
    """A connection whose search_path is a fresh schema shaped like the DB before signup."""
    engine = create_engine(settings.DATABASE_URL)
    schema = f"signup_mig_{uuid.uuid4().hex[:12]}"
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text("CREATE TYPE userrole AS ENUM ('admin', 'manager', 'staff')"))
            conn.execute(text("CREATE TABLE company_profiles (id SERIAL PRIMARY KEY, name VARCHAR NOT NULL)"))
            conn.execute(text("""
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR NOT NULL UNIQUE,
                    full_name VARCHAR NOT NULL,
                    hashed_password VARCHAR NOT NULL,
                    role userrole NOT NULL,
                    active_company_id INTEGER REFERENCES company_profiles(id)
                )
            """))
            conn.execute(text("INSERT INTO company_profiles (name) VALUES ('Acme'), ('Globex')"))
            conn.execute(text("""
                INSERT INTO users (email, full_name, hashed_password, role) VALUES
                    ('admin@example.com', 'Admin', 'h', 'admin'),
                    ('manager@example.com', 'Manager', 'h', 'manager'),
                    ('staff@example.com', 'Staff', 'h', 'staff')
            """))
            # Fresh schema, so the sequences hand out ids 1, 2, 3.
            yield conn
        finally:
            tx.rollback()
    engine.dispose()


def _apply_all(conn) -> None:
    for name in SIGNUP_MIGRATIONS:
        _load(name).up(conn)


def test_backfills_a_membership_per_user_and_company_with_the_global_role(pre_signup_conn):
    _apply_all(pre_signup_conn)

    rows = pre_signup_conn.execute(text(
        "SELECT user_id, company_id, role::text FROM company_memberships ORDER BY user_id, company_id"
    )).fetchall()
    assert [tuple(r) for r in rows] == [
        (1, 1, "admin"), (1, 2, "admin"),
        (2, 1, "manager"), (2, 2, "manager"),
        (3, 1, "staff"), (3, 2, "staff"),
    ]


def test_existing_users_are_verified_active_and_dated(pre_signup_conn):
    _apply_all(pre_signup_conn)

    rows = pre_signup_conn.execute(text(
        "SELECT email_verified_at IS NOT NULL, is_active, created_at IS NOT NULL FROM users"
    )).fetchall()
    assert len(rows) == 3
    assert all(tuple(r) == (True, True, True) for r in rows)


def test_new_users_after_migration_start_unverified_and_may_lack_a_password(pre_signup_conn):
    _apply_all(pre_signup_conn)

    pre_signup_conn.execute(text(
        "INSERT INTO users (email, full_name, hashed_password, role) "
        "VALUES ('google@example.com', 'G', NULL, 'staff')"
    ))
    row = pre_signup_conn.execute(text(
        "SELECT email_verified_at, is_active FROM users WHERE email = 'google@example.com'"
    )).one()
    assert row.email_verified_at is None
    assert row.is_active is True


def test_migrations_are_idempotent(pre_signup_conn):
    _apply_all(pre_signup_conn)
    _apply_all(pre_signup_conn)

    count = pre_signup_conn.execute(text("SELECT COUNT(*) FROM company_memberships")).scalar()
    assert count == 6


def test_identity_and_login_code_tables_enforce_uniqueness(pre_signup_conn):
    _apply_all(pre_signup_conn)

    pre_signup_conn.execute(text(
        "INSERT INTO user_identities (user_id, provider, provider_subject) VALUES (1, 'google', 'sub-1')"
    ))
    nested = pre_signup_conn.begin_nested()
    with pytest.raises(Exception):
        pre_signup_conn.execute(text(
            "INSERT INTO user_identities (user_id, provider, provider_subject) VALUES (2, 'google', 'sub-1')"
        ))
    nested.rollback()

    pre_signup_conn.execute(text(
        "INSERT INTO oauth_login_codes (code_hash, user_id, expires_at) VALUES ('abc', 1, NOW())"
    ))
    nested = pre_signup_conn.begin_nested()
    with pytest.raises(Exception):
        pre_signup_conn.execute(text(
            "INSERT INTO oauth_login_codes (code_hash, user_id, expires_at) VALUES ('abc', 2, NOW())"
        ))
    nested.rollback()
