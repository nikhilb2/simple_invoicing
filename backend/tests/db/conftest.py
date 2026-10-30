"""A row-level-security database for the Postgres-only tests in this directory.

Builds, inside the DATABASE_URL database, a throwaway schema with the full table
set and the shared-hosting RLS policies, plus a throwaway login role shaped like
production's ``invoicing_app``: not a superuser, no BYPASSRLS, owns nothing,
holds only DML grants. The connecting DATABASE_URL user (a superuser in the dev
container) is the owner, standing in for MIGRATION_DATABASE_URL.

Everything is dropped afterwards, the role included, even when a test fails.
"""

import secrets
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.models  # noqa: F401 -- every table on Base.metadata
from src.core.config import settings
from src.db.base import Base
from src.db.rls import ensure_row_level_security

IS_POSTGRES = settings.DATABASE_URL.startswith("postgres")


def _schema_engine(url, schema: str, **kwargs):
    return create_engine(url, connect_args={"options": f"-csearch_path={schema}"}, **kwargs)


@pytest.fixture(scope="session")
def rls_db():
    if not IS_POSTGRES:
        pytest.skip("row-level security needs Postgres")

    suffix = uuid.uuid4().hex[:10]
    schema = f"rls_test_{suffix}"
    role = f"si_rls_test_app_{suffix}"
    password = secrets.token_hex(16)

    admin = create_engine(settings.DATABASE_URL)
    owner_url = make_url(settings.DATABASE_URL)
    app_url = owner_url.set(username=role, password=password)
    owner_engine = _schema_engine(owner_url, schema)
    app_engine = None
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(
                f'CREATE ROLE "{role}" LOGIN PASSWORD \'{password}\' '
                "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
            ))
            conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))

        # As the owner: the tables, the policies, then the grants the si-common
        # README sets up for invoicing_app.
        with owner_engine.begin() as conn:
            Base.metadata.create_all(bind=conn)
            ensure_row_level_security(conn)
            conn.execute(text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'
            ))
            conn.execute(text(
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"'
            ))

        app_engine = _schema_engine(app_url, schema)
        yield SimpleNamespace(
            schema=schema,
            role=role,
            owner_url=owner_url,
            app_url=app_url,
            owner_engine=owner_engine,
            app_engine=app_engine,
            OwnerSession=sessionmaker(bind=owner_engine, autoflush=False, expire_on_commit=False),
            AppSession=sessionmaker(bind=app_engine, autoflush=False),
            schema_engine=_schema_engine,
        )
    finally:
        if app_engine is not None:
            app_engine.dispose()
        owner_engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = :role"
            ), {"role": role})
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
            if exists:
                conn.execute(text(f'DROP OWNED BY "{role}"'))
                conn.execute(text(f'DROP ROLE "{role}"'))
        admin.dispose()


@pytest.fixture
def clean_rls_db(rls_db):
    """Empty every table (as the owner) before the test, ids reset."""
    with rls_db.owner_engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return rls_db
