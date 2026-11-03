"""The quotation migrations upgrade a real database, whichever way it got there.

Boot runs create_all before migrations, so the new tables usually exist already while
invoices still lacks its column and index. Each migration must cope with that, run
twice harmlessly, and leave an upgraded database shaped like the model.

Runs inside a throwaway schema, in one transaction that is rolled back.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import src.models  # noqa: F401
from src.core.config import settings
from src.db.base import Base

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
MIGRATIONS = [
    "20261104000001_create_quotations_tables",
    "20261104000002_seed_quotation_series",
    "20261104000003_add_source_quotation_id_to_invoices",
]

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="migrations are Postgres DDL",
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn():
    """A connection whose search_path is a fresh schema, rolled back at the end."""
    schema = f"quote_mig_{uuid.uuid4().hex[:10]}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        yield connection
        transaction.rollback()
    engine.dispose()


def _build_pre_quotation_database(conn) -> None:
    """The schema as it stood before this feature: no new tables, no new column."""
    Base.metadata.create_all(bind=conn)
    conn.execute(text("DROP INDEX ux_invoices_active_source_quotation"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN source_quotation_id"))
    conn.execute(text("DROP TABLE quotation_items"))
    conn.execute(text("DROP TABLE quotations"))


def _seed_two_companies(conn) -> dict:
    ids = {}
    for name in ("Alpha", "Beta"):
        company = conn.execute(text(
            "INSERT INTO company_profiles (name, address, gst, phone_number, currency_code) "
            "VALUES (:n, '', '', '', 'INR') RETURNING id"
        ), {"n": name}).scalar()
        fy = conn.execute(text(
            "INSERT INTO financial_years (company_id, label, start_date, end_date, is_active) "
            "VALUES (:c, '2026-27', '2026-04-01', '2027-03-31', true) RETURNING id"
        ), {"c": company}).scalar()
        conn.execute(text(
            "INSERT INTO invoice_series (company_id, voucher_type, financial_year_id, prefix, suffix, "
            "include_year, year_format, separator, next_sequence, pad_digits) "
            "VALUES (:c, 'sales', :f, 'INV', '', false, 'FY', '/', 40, 4)"
        ), {"c": company, "f": fy})
        ids[name] = {"company": company, "fy": fy}
    return ids


def _columns(conn, table: str) -> dict[str, tuple]:
    rows = conn.execute(text(
        "SELECT column_name, data_type, is_nullable, character_maximum_length, numeric_precision, numeric_scale "
        "FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = :t"
    ), {"t": table}).fetchall()
    return {row[0]: tuple(row[1:]) for row in rows}


def _indexes(conn, table: str) -> dict[str, str]:
    rows = conn.execute(text(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = :t"
    ), {"t": table}).fetchall()
    return {row[0]: row[1] for row in rows}


def test_migrations_build_the_same_shape_as_the_models(conn):
    """A database upgraded by migrations and a new one from create_all must agree."""
    Base.metadata.create_all(bind=conn)
    model_shape = {table: _columns(conn, table) for table in ("quotations", "quotation_items")}
    model_indexes = {table: set(_indexes(conn, table)) for table in ("quotations", "quotation_items")}
    model_invoice_index = _indexes(conn, "invoices")["ux_invoices_active_source_quotation"]

    _build_pre_quotation_database(conn)
    for name in MIGRATIONS:
        _load(name).up(conn)

    for table in ("quotations", "quotation_items"):
        assert _columns(conn, table) == model_shape[table], table
        assert set(_indexes(conn, table)) == model_indexes[table], table
    assert _indexes(conn, "invoices")["ux_invoices_active_source_quotation"] == model_invoice_index
    assert "source_quotation_id" in _columns(conn, "invoices")


def test_migrations_run_over_what_create_all_already_made(conn):
    """The boot order: tables exist, the invoices column and index do not."""
    Base.metadata.create_all(bind=conn)
    conn.execute(text("DROP INDEX ux_invoices_active_source_quotation"))
    conn.execute(text("ALTER TABLE invoices DROP COLUMN source_quotation_id"))
    for name in MIGRATIONS:
        _load(name).up(conn)
    assert "source_quotation_id" in _columns(conn, "invoices")
    assert "ux_invoices_active_source_quotation" in _indexes(conn, "invoices")


def test_migrations_can_run_twice(conn):
    _build_pre_quotation_database(conn)
    ids = _seed_two_companies(conn)
    for _ in range(2):
        for name in MIGRATIONS:
            _load(name).up(conn)
    count = conn.execute(text(
        "SELECT count(*) FROM invoice_series WHERE voucher_type IN ('quotation', 'proforma')"
    )).scalar()
    assert count == 2 * len(ids)


def test_series_seed_is_per_company_and_follows_the_sales_format(conn):
    _build_pre_quotation_database(conn)
    ids = _seed_two_companies(conn)
    for name in MIGRATIONS:
        _load(name).up(conn)

    rows = conn.execute(text("""
        SELECT company_id, financial_year_id, voucher_type, prefix, include_year, year_format,
               separator, next_sequence, pad_digits
          FROM invoice_series WHERE voucher_type IN ('quotation', 'proforma')
         ORDER BY company_id, voucher_type
    """)).fetchall()
    expected = []
    for tenant in sorted(ids.values(), key=lambda value: value["company"]):
        expected.append((tenant["company"], tenant["fy"], "proforma", "PI", False, "FY", "/", 1, 4))
        expected.append((tenant["company"], tenant["fy"], "quotation", "QT", False, "FY", "/", 1, 4))
    assert [tuple(row) for row in rows] == expected

    # The sales counter is left exactly where it was.
    assert conn.execute(text("SELECT DISTINCT next_sequence FROM invoice_series WHERE voucher_type = 'sales'")).scalar() == 40


def test_seed_keeps_a_series_someone_already_edited(conn):
    _build_pre_quotation_database(conn)
    ids = _seed_two_companies(conn)
    tenant = ids["Alpha"]
    conn.execute(text(
        "INSERT INTO invoice_series (company_id, voucher_type, financial_year_id, prefix, suffix, "
        "include_year, year_format, separator, next_sequence, pad_digits) "
        "VALUES (:c, 'quotation', :f, 'EST', '', true, 'YYYY', '-', 9, 3)"
    ), tenant | {"c": tenant["company"], "f": tenant["fy"]})
    for name in MIGRATIONS:
        _load(name).up(conn)
    row = conn.execute(text(
        "SELECT prefix, next_sequence FROM invoice_series WHERE voucher_type = 'quotation' AND company_id = :c"
    ), {"c": tenant["company"]}).one()
    assert tuple(row) == ("EST", 9)


def test_down_removes_everything(conn):
    _build_pre_quotation_database(conn)
    _seed_two_companies(conn)
    for name in MIGRATIONS:
        _load(name).up(conn)
    for name in reversed(MIGRATIONS):
        _load(name).down(conn)
    assert "source_quotation_id" not in _columns(conn, "invoices")
    assert _columns(conn, "quotations") == {}
    assert _columns(conn, "quotation_items") == {}
    assert conn.execute(text(
        "SELECT count(*) FROM invoice_series WHERE voucher_type IN ('quotation', 'proforma')"
    )).scalar() == 0
