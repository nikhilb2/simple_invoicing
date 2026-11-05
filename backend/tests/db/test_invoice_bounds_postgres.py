"""Real PostgreSQL coverage for invoice limits and rollback of stock and numbering."""
import pytest
from sqlalchemy import text

from src.core.config import settings
from test_quotation_bounds_postgres import tenant  # noqa: F401
from test_quotation_convert_postgres import (  # noqa: F401
    _sales_counter,
    _stock,
    app_db,
    deployment,
    signed_in,
)

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="column limits need Postgres",
)


def test_invoice_total_overflow_rolls_back_and_maximum_still_saves(tenant, app_db):
    client = tenant["client"]
    stock_before = _stock(app_db, tenant["product"])
    sequence_before = _sales_counter(app_db, tenant["company"])
    oversized = {
        "ledger_id": tenant["ledger"],
        "items": [{"product_id": tenant["product"], "quantity": 1, "unit_price": 60_000_000}] * 2,
    }

    def reject(response):
        assert response.status_code == 400, response.text
        assert "100,000,000" in response.json()["detail"]

    reject(client.post("/api/invoices/", json=oversized))
    assert _stock(app_db, tenant["product"]) == stock_before
    assert _sales_counter(app_db, tenant["company"]) == sequence_before
    with app_db.owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM invoices")).scalar_one() == 0

    valid = client.post("/api/invoices/", json={
        "ledger_id": tenant["ledger"],
        "items": [{"product_id": tenant["untaxed"], "quantity": 1, "unit_price": 99_999_999.99}],
    })
    assert valid.status_code == 200, valid.text
    invoice_id = valid.json()["id"]
    assert valid.json()["total_amount"] == 99_999_999.99
    assert _sales_counter(app_db, tenant["company"]) == sequence_before + 1

    reject(client.put(f"/api/invoices/{invoice_id}", json=oversized))
    assert _stock(app_db, tenant["product"]) == stock_before
    assert _sales_counter(app_db, tenant["company"]) == sequence_before + 1
    with app_db.owner_engine.connect() as conn:
        assert str(conn.execute(text("SELECT total_amount FROM invoices")).scalar_one()) == "99999999.99"
