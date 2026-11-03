"""Figures and dates too large for their columns: refused, not a database error.

SQLite stores whatever it is handed, so a NUMERIC overflow only shows here. The columns
are NUMERIC(10, 2) for money and NUMERIC(12, 3) for quantity, on quotations and on the
invoices they convert to. Skipped when DATABASE_URL is not Postgres.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app_main import app
from src.core.config import settings
# Fixtures, imported by name so pytest finds them here too.
from test_quotation_convert_postgres import _create_quote, _seed_company, app_db, deployment, signed_in  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import test_tenant_isolation as iso  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="column limits need Postgres",
)


@pytest.fixture
def tenant(app_db, signed_in):  # noqa: F811
    client = TestClient(app)
    seeded = _seed_company(client, signed_in, app_db, "alice@alpha.example", "Alpha Traders", "ALPHA-1")
    # No GST, so a line's total is exactly its price times its quantity.
    seeded["untaxed"] = iso._ok(client.post("/api/products/", json={
        "sku": "ALPHA-0",
        "name": "Untaxed",
        "price": 100,
        "gst_rate": 0,
        "maintain_inventory": False,
        "allow_decimal": True,
    }))["id"]
    seeded["client"] = client
    return seeded


def _body(tenant: dict, *lines: dict, product: str = "product", **fields) -> dict:
    return {
        "ledger_id": tenant["ledger"],
        "items": [{"product_id": tenant[product], "quantity": 1, "unit_price": 100, **line} for line in lines or ({},)],
        **fields,
    }


def _quotation_count(db) -> int:
    with db.owner_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM quotations")).scalar()


TOO_LARGE_FIELDS = [
    pytest.param({"items": [{"unit_price": 1e9}]}, id="unit_price"),
    pytest.param({"items": [{"unit_price": 100_000_000}]}, id="unit_price_at_the_limit"),
    pytest.param({"items": [{"quantity": 1e10}]}, id="quantity"),
    pytest.param({"items": [{"quantity": 1_000_000_000}]}, id="quantity_at_the_limit"),
    pytest.param({"items": [{"discount_type": "net", "discount_value": 1e9}]}, id="line_discount"),
    pytest.param({"discount_type": "net", "discount_value": 1e9}, id="document_discount"),
    pytest.param({"quotation_date": "9999-12-20"}, id="quotation_date_far_future"),
    pytest.param({"quotation_date": "0001-01-01", "valid_until": None}, id="quotation_date_far_past"),
    pytest.param({"valid_until": "9999-12-31"}, id="valid_until_far_future"),
]


def _with_fields(tenant: dict, fields: dict) -> dict:
    lines = fields.get("items", [{}])
    others = {key: value for key, value in fields.items() if key != "items"}
    return _body(tenant, *lines, **others)


@pytest.mark.parametrize("fields", TOO_LARGE_FIELDS)
def test_create_refuses_what_the_columns_cannot_hold(tenant, app_db, fields):
    response = tenant["client"].post("/api/quotations/", json=_with_fields(tenant, fields))
    assert response.status_code == 422, response.text[:300]
    assert _quotation_count(app_db) == 0


@pytest.mark.parametrize("fields", TOO_LARGE_FIELDS)
def test_edit_refuses_what_the_columns_cannot_hold(tenant, fields):
    quote = _create_quote(tenant["client"], tenant)
    response = tenant["client"].put(f"/api/quotations/{quote['id']}", json=_with_fields(tenant, fields))
    assert response.status_code == 422, response.text[:300]


def test_infinity_and_nan_are_still_refused(tenant):
    for bad in ("Infinity", "NaN"):
        for line in ({"unit_price": bad}, {"quantity": bad}):
            response = tenant["client"].post("/api/quotations/", json=_body(tenant, line))
            assert response.status_code == 422, response.text[:300]


def test_the_largest_values_that_fit_are_stored(tenant):
    client = tenant["client"]
    price = iso._ok(client.post("/api/quotations/", json=_body(tenant, {"unit_price": 99_999_999.99}, product="untaxed")))
    assert price["total_amount"] == 99_999_999.99

    quantity = iso._ok(client.post("/api/quotations/", json=_body(tenant, {"quantity": 999_999_999.999, "unit_price": 0}, product="untaxed")))
    assert quantity["items"][0]["quantity"] == 999_999_999.999

    # A net discount larger than the document just clears it, as it does on an invoice.
    discounted = iso._ok(client.post("/api/quotations/", json=_body(
        tenant, {"unit_price": 100}, product="untaxed", discount_type="net", discount_value=99_999_999.99,
    )))
    assert discounted["discount_value"] == 99_999_999.99
    assert discounted["total_amount"] == 0

    far = iso._ok(client.post("/api/quotations/", json=_body(tenant, quotation_date="2099-12-31", valid_until="2099-12-31")))
    assert far["valid_until"] == "2099-12-31"

    # The default validity must not push a document past the range either.
    defaulted = iso._ok(client.post("/api/quotations/", json=_body(tenant, quotation_date="2099-12-31")))
    assert defaulted["valid_until"] == "2099-12-31"


TOTALS_TOO_LARGE = [
    pytest.param(dict(lines=[{"quantity": 99_999, "unit_price": 99_999}]), id="price_times_quantity"),
    pytest.param(dict(lines=[{"unit_price": 99_999_999}], product="product"), id="tax_on_top"),
    pytest.param(dict(lines=[{"unit_price": 60_000_000}, {"unit_price": 60_000_000}]), id="sum_of_lines"),
    pytest.param(dict(lines=[{"unit_price": 99_999_999.99}], apply_round_off=True), id="rounded_up"),
]


@pytest.mark.parametrize("case", TOTALS_TOO_LARGE)
def test_totals_that_do_not_fit_are_a_400(tenant, app_db, case):
    fields = dict(case)
    lines = fields.pop("lines")
    product = fields.pop("product", "untaxed")
    response = tenant["client"].post("/api/quotations/", json=_body(tenant, *lines, product=product, **fields))
    assert response.status_code == 400, response.text[:300]
    assert "too large" in response.json()["detail"]
    assert _quotation_count(app_db) == 0


def test_an_edit_whose_total_does_not_fit_changes_nothing(tenant):
    client = tenant["client"]
    quote = _create_quote(client, tenant)
    response = client.put(
        f"/api/quotations/{quote['id']}",
        json=_body(tenant, {"quantity": 99_999, "unit_price": 99_999}, product="untaxed"),
    )
    assert response.status_code == 400, response.text[:300]
    after = iso._ok(client.get(f"/api/quotations/{quote['id']}"))
    assert after["total_amount"] == quote["total_amount"]
    assert len(after["items"]) == len(quote["items"])


@pytest.mark.parametrize(
    "quotation_date, valid_until",
    [
        pytest.param("2026-01-01", "9999-12-31", id="stored_before_the_limit_existed"),
        pytest.param("2000-01-01", "2099-12-31", id="the_widest_span_the_limits_allow"),
    ],
)
def test_duplicating_a_very_long_validity_stops_at_the_last_allowed_date(tenant, app_db, quotation_date, valid_until):
    client = tenant["client"]
    quote = _create_quote(client, tenant)
    with app_db.owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE quotations SET quotation_date = :d, valid_until = :v WHERE id = :q"),
            {"d": quotation_date, "v": valid_until, "q": quote["id"]},
        )

    copy = iso._ok(client.post(f"/api/quotations/{quote['id']}/duplicate"))
    assert copy["valid_until"] == "2099-12-31"
