"""The place of supply migration on a real Postgres: backfill, re-run, rollback.

Runs the real migration file inside a throwaway schema, in one transaction that
is rolled back. Skipped when DATABASE_URL is not Postgres: the rest of the suite
builds its schema on SQLite, where these migrations never run.
"""

import importlib.util
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.core.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
MIGRATION = "20261103000002_add_place_of_supply_and_credit_note_date"

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="this migration is Postgres DDL",
)

# What the previous image writes: every column but the new one.
OLD_IMAGE_INSERT = text("INSERT INTO credit_notes (credit_note_number, created_at) VALUES (:number, :created_at)")


def _load():
    spec = importlib.util.spec_from_file_location(MIGRATION, MIGRATIONS_DIR / f"{MIGRATION}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load()


def _connection(created_at_type: str):
    engine = create_engine(settings.DATABASE_URL)
    schema = f"pos_mig_{uuid.uuid4().hex[:12]}"
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text("CREATE TABLE invoices (id SERIAL PRIMARY KEY)"))
            conn.execute(text(
                "CREATE TABLE credit_notes "
                f"(id SERIAL PRIMARY KEY, credit_note_number VARCHAR, created_at {created_at_type})"
            ))
            yield conn
        finally:
            tx.rollback()
    engine.dispose()


@pytest.fixture
def conn():
    """created_at as a migrated database has it."""
    yield from _connection("TIMESTAMPTZ")


@pytest.fixture
def naive_conn():
    """created_at as a database built from the models has it: naive UTC."""
    yield from _connection("TIMESTAMP")


def _note_date(conn, number):
    return conn.execute(
        text("SELECT credit_note_date FROM credit_notes WHERE credit_note_number = :n"), {"n": number}
    ).scalar()


def _india_today(conn):
    return conn.execute(text("SELECT (now() AT TIME ZONE 'Asia/Kolkata')::date")).scalar()


def test_backfill_gives_each_note_its_issue_date_in_india(conn):
    conn.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    conn.execute(OLD_IMAGE_INSERT, {"number": "morning", "created_at": "2026-01-01 05:00:00+00"})
    conn.execute(OLD_IMAGE_INSERT, {"number": "after-midnight-ist", "created_at": "2026-01-01 19:00:00+00"})

    migration.up(conn)

    assert _note_date(conn, "morning") == datetime(2026, 1, 1)
    assert _note_date(conn, "after-midnight-ist") == datetime(2026, 1, 2)


@pytest.mark.parametrize("session_zone", ["America/New_York", "Asia/Tokyo"])
def test_backfill_does_not_depend_on_the_session_time_zone(conn, session_zone):
    conn.execute(text(f"SET LOCAL TIME ZONE '{session_zone}'"))
    conn.execute(OLD_IMAGE_INSERT, {"number": "n", "created_at": "2026-01-01 19:00:00+00"})

    migration.up(conn)

    assert _note_date(conn, "n") == datetime(2026, 1, 2)


@pytest.mark.parametrize("session_zone", ["UTC", "Europe/Zurich", "Asia/Tokyo"])
def test_backfill_reads_a_naive_utc_created_at(naive_conn, session_zone):
    naive_conn.execute(text(f"SET LOCAL TIME ZONE '{session_zone}'"))
    naive_conn.execute(OLD_IMAGE_INSERT, {"number": "n", "created_at": "2026-01-01 19:00:00"})

    migration.up(naive_conn)

    assert _note_date(naive_conn, "n") == datetime(2026, 1, 2)


def test_a_null_created_at_does_not_abort_the_backfill(naive_conn):
    naive_conn.execute(OLD_IMAGE_INSERT, {"number": "no-created-at", "created_at": None})

    migration.up(naive_conn)

    assert _note_date(naive_conn, "no-created-at").date() == _india_today(naive_conn)


def test_the_previous_image_can_still_insert_after_the_migration(conn):
    migration.up(conn)

    conn.execute(OLD_IMAGE_INSERT, {"number": "old-image", "created_at": "2026-01-01 19:00:00+00"})

    written = _note_date(conn, "old-image")
    assert written.date() == _india_today(conn)
    assert (written.hour, written.minute, written.second) == (0, 0, 0)


def test_the_migration_can_run_twice_and_keeps_a_chosen_date(conn):
    conn.execute(OLD_IMAGE_INSERT, {"number": "n", "created_at": "2026-01-01 05:00:00+00"})
    migration.up(conn)
    conn.execute(text("UPDATE credit_notes SET credit_note_date = '2025-12-25' WHERE credit_note_number = 'n'"))

    migration.up(conn)

    assert _note_date(conn, "n") == datetime(2025, 12, 25)


def test_rollback_and_upgrade_again(conn):
    conn.execute(OLD_IMAGE_INSERT, {"number": "n", "created_at": "2026-01-01 05:00:00+00"})
    migration.up(conn)

    migration.down(conn)

    columns = {
        row[0] for row in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name IN ('credit_notes', 'invoices')"
        ))
    }
    assert not columns & {"credit_note_date", "place_of_supply"}
    conn.execute(OLD_IMAGE_INSERT, {"number": "during-rollback", "created_at": "2026-01-02 05:00:00+00"})

    migration.up(conn)

    assert _note_date(conn, "n").date() == date(2026, 1, 1)
    assert _note_date(conn, "during-rollback").date() == date(2026, 1, 2)
