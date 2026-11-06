"""Production costs must fit NUMERIC(12, 2), including after rounding."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app_main import app
from src.core.config import settings
from test_quotation_bounds_postgres import tenant  # noqa: F401
from test_quotation_convert_postgres import app_db, deployment, signed_in  # noqa: F401

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="column limits need Postgres",
)


@pytest.mark.parametrize("method", ["post", "put"])
@pytest.mark.parametrize("value", [1e11, 10_000_000_000, 9_999_999_999.995, 9_999_999_999.996])
def test_production_cost_overflow_is_rejected_without_changing_products(tenant, app_db, method, value):
    client = TestClient(app, raise_server_exceptions=False)
    payload = {"sku": "COST-BOUNDS", "name": "Cost bounds", "price": 10}
    with app_db.owner_engine.connect() as conn:
        count_before = conn.execute(text("SELECT count(*) FROM products")).scalar_one()

    product_id = tenant["product"]
    url = "/api/products/" if method == "post" else f"/api/products/{product_id}"
    response = getattr(client, method)(url, json={**payload, "production_cost": value})
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "production_cost"]
    with app_db.owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM products")).scalar_one() == count_before
        assert conn.execute(
            text("SELECT production_cost FROM products WHERE id = :id"), {"id": product_id},
        ).scalar_one() is None


def test_largest_production_cost_is_stored_on_create_and_update(tenant, app_db):
    client = tenant["client"]
    maximum = 9_999_999_999.99
    payload = {"sku": "COST-MAX", "name": "Maximum cost", "price": 10, "production_cost": maximum}
    created = client.post("/api/products/", json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["production_cost"] == maximum

    # A different product proves the update actually writes the maximum too.
    updated = client.put(f"/api/products/{tenant['product']}", json={**payload, "sku": "COST-EDIT"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["production_cost"] == maximum

    with app_db.owner_engine.connect() as conn:
        for product_id in (created.json()["id"], tenant["product"]):
            stored = conn.execute(
                text("SELECT production_cost FROM products WHERE id = :id"), {"id": product_id},
            ).scalar_one()
            assert stored == Decimal("9999999999.99")
