"""Validation of quantities in production and BOM requests (issue #553).

Zero, negative and non-finite quantities must be rejected with 422
before any stock movement happens; positive and fractional values
must keep working.
"""

from decimal import Decimal

import pytest

from src.models.bom import BillOfMaterial
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.product import Product


def _make_setup(db_session):
    """Create a company, a producable product, a component and stock."""
    company = CompanyProfile(name="BOM Validation Co", address="123 Test St")
    db_session.add(company)
    db_session.flush()

    finished = Product(
        company_id=company.id,
        sku="BOMVALFIN01",
        name="Finished Goods",
        price=Decimal("10"),
        is_producable=True,
        allow_decimal=True,
    )
    component = Product(
        company_id=company.id,
        sku="BOMVALRAW01",
        name="Raw Material",
        price=Decimal("2"),
    )
    db_session.add_all([finished, component])
    db_session.flush()

    bom_entry = BillOfMaterial(
        company_id=company.id,
        product_id=finished.id,
        component_product_id=component.id,
        quantity_required=Decimal("1"),
    )
    db_session.add(bom_entry)
    db_session.add(
        Inventory(company_id=company.id, product_id=component.id, quantity=Decimal("5"))
    )
    db_session.commit()
    return finished, component, bom_entry


@pytest.mark.parametrize("quantity", [0, -1])
def test_produce_rejects_non_positive_quantity(client, db_session, quantity):
    finished, _, _ = _make_setup(db_session)

    response = client.post(
        "/api/inventory/produce",
        json={"product_id": finished.id, "quantity": quantity},
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("quantity", [0.5, 1])
def test_produce_accepts_positive_quantity(client, db_session, quantity):
    finished, _, _ = _make_setup(db_session)

    response = client.post(
        "/api/inventory/produce",
        json={"product_id": finished.id, "quantity": quantity},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("quantity", [0, -1])
def test_bom_create_rejects_non_positive_quantity(client, db_session, quantity):
    finished, component, _ = _make_setup(db_session)

    response = client.post(
        "/api/bom/",
        json={
            "product_id": finished.id,
            "component_product_id": component.id,
            "quantity_required": quantity,
        },
    )
    # The entry already exists for this pair, but request validation (422)
    # runs before the handler, so it must win over the 400 duplicate check.
    assert response.status_code == 422, response.text


def test_bom_create_accepts_fractional_quantity(client, db_session):
    finished, component, _ = _make_setup(db_session)
    other = Product(
        company_id=finished.company_id,
        sku="BOMVALRAW02",
        name="Second Material",
        price=Decimal("3"),
    )
    db_session.add(other)
    db_session.commit()

    response = client.post(
        "/api/bom/",
        json={
            "product_id": finished.id,
            "component_product_id": other.id,
            "quantity_required": 0.5,
        },
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("quantity", [0, -1])
def test_bom_update_rejects_non_positive_quantity(client, db_session, quantity):
    _, _, bom_entry = _make_setup(db_session)

    response = client.put(
        f"/api/bom/{bom_entry.id}",
        json={"quantity_required": quantity},
    )
    assert response.status_code == 422, response.text


def test_bom_update_accepts_fractional_quantity(client, db_session):
    _, _, bom_entry = _make_setup(db_session)

    response = client.put(
        f"/api/bom/{bom_entry.id}",
        json={"quantity_required": 0.5},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "raw_value",
    ["NaN", "Infinity"],
)
def test_produce_rejects_non_finite_quantity(client, db_session, raw_value):
    finished, _, _ = _make_setup(db_session)

    response = client.post(
        "/api/inventory/produce",
        content=(
            '{"product_id": %d, "quantity": %s}' % (finished.id, raw_value)
        ),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("quantity", [1e10, 999_999_999.9996])
def test_bom_create_rejects_overflowing_quantity(client, db_session, quantity):
    finished, component, _ = _make_setup(db_session)

    response = client.post(
        "/api/bom/",
        json={
            "product_id": finished.id,
            "component_product_id": component.id,
            "quantity_required": quantity,
        },
    )
    # Validation (422) runs before the duplicate-pair check.
    assert response.status_code == 422, response.text


def test_bom_create_accepts_quantity_just_below_storage_cutoff(client, db_session):
    finished, _, _ = _make_setup(db_session)
    other = Product(
        company_id=finished.company_id,
        sku="BOMVALRAW04",
        name="Near Limit Material",
        price=Decimal("3"),
    )
    db_session.add(other)
    db_session.commit()

    response = client.post(
        "/api/bom/",
        json={
            "product_id": finished.id,
            "component_product_id": other.id,
            "quantity_required": 999_999_999.999,
        },
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("quantity", [1e10, 999_999_999.9996])
def test_bom_update_rejects_overflowing_quantity(client, db_session, quantity):
    _, _, bom_entry = _make_setup(db_session)

    response = client.put(
        f"/api/bom/{bom_entry.id}",
        json={"quantity_required": quantity},
    )
    assert response.status_code == 422, response.text
