from decimal import Decimal

import pytest

from src.models.bom import BillOfMaterial
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.product import Product


def _make_producible_setup(db_session):
    """Create a company, a producable product, its BOM, and component stock."""
    company = CompanyProfile(name="Notes Test Co", address="123 Test St")
    db_session.add(company)
    db_session.flush()

    finished = Product(
        company_id=company.id,
        sku="NOTESFIN01",
        name="Finished Goods",
        price=Decimal("10"),
        is_producable=True,
    )
    component = Product(
        company_id=company.id,
        sku="NOTESRAW01",
        name="Raw Material",
        price=Decimal("2"),
    )
    db_session.add_all([finished, component])
    db_session.flush()

    db_session.add(
        BillOfMaterial(
            company_id=company.id,
            product_id=finished.id,
            component_product_id=component.id,
            quantity_required=Decimal("1"),
        )
    )
    db_session.add(
        Inventory(company_id=company.id, product_id=component.id, quantity=Decimal("5"))
    )
    db_session.commit()
    return finished


def test_inventory_list_includes_products_without_inventory_rows(client, db_session):
    create_response = client.post(
        "/api/products/",
        json={
            "sku": "INVLIST01",
            "name": "Inventoryless Product",
            "price": 10,
            "gst_rate": 18,
        },
    )

    assert create_response.status_code == 200
    product_id = create_response.json()["id"]

    inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
    assert inventory is not None
    db_session.delete(inventory)
    db_session.commit()

    response = client.get("/api/inventory/?search=Inventoryless&page=1&page_size=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["product_id"] == product_id
    assert payload["items"][0]["maintain_inventory"] is True
    assert payload["items"][0]["quantity"] == 0


def test_inventory_list_marks_untracked_products(client):
    create_response = client.post(
        "/api/products/",
        json={
            "sku": "UNTRACKED01",
            "name": "Consulting Service",
            "price": 150,
            "gst_rate": 18,
            "maintain_inventory": False,
        },
    )
    assert create_response.status_code == 200
    product_id = create_response.json()["id"]

    response = client.get("/api/inventory/?search=Consulting&page=1&page_size=20")
    assert response.status_code == 200

    item = response.json()["items"][0]
    assert item["product_id"] == product_id
    assert item["maintain_inventory"] is False
    assert item["quantity"] == 0
    assert item["unit"] == "Pieces"
    assert item["allow_decimal"] is False


@pytest.mark.parametrize("maintained,expected_total,first_name", [
    (None, 3, "A Service"),
    (True, 2, "B Stock"),
    (False, 1, "A Service"),
])
def test_inventory_tracking_filter_applies_before_pagination(client, maintained, expected_total, first_name):
    for index, (name, tracked) in enumerate([("A Service", False), ("B Stock", True), ("C Stock", True)]):
        created = client.post("/api/products/", json={
            "sku": f"FILTER-{index}", "name": name, "price": 10, "gst_rate": 0,
            "maintain_inventory": tracked,
        })
        assert created.status_code == 200, created.text

    params = {"page_size": 1, "sort_by": "name"}
    if maintained is not None:
        params["maintain_inventory"] = maintained
    response = client.get("/api/inventory/", params=params)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == result["total_pages"] == expected_total
    assert [row["product_name"] for row in result["items"]] == [first_name]
    if maintained is not None:
        assert result["items"][0]["maintain_inventory"] is maintained


@pytest.mark.parametrize("attention_stock,expected", [
    ([], [1, 2, 3, 4, 5]),
    ([(50, 100)], [50, 1, 2, 3, 4]),
    ([(50, 50), (0, 0)], [0, 50, 1, 2, 3]),
])
def test_inventory_attention_sort_prioritizes_reorder_level_before_pagination(
    client, attention_stock, expected,
):
    stock = [(quantity, 0) for quantity in range(1, 6)] + attention_stock
    for index, (quantity, reorder_level) in enumerate(stock):
        created = client.post("/api/products/", json={
            "sku": f"ATTENTION-{index}", "name": f"Stock {index}", "price": 10,
            "gst_rate": 0, "initial_quantity": quantity, "reorder_level": reorder_level,
        })
        assert created.status_code == 200, created.text

    params = {"maintain_inventory": True, "sort_order": "asc", "page_size": 5}
    legacy = client.get("/api/inventory/", params={**params, "sort_by": "quantity"})
    assert legacy.status_code == 200, legacy.text
    assert [row["quantity"] for row in legacy.json()["items"]] == sorted(qty for qty, _ in stock)[:5]

    response = client.get("/api/inventory/", params={**params, "sort_by": "attention"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == len(stock)
    assert [row["quantity"] for row in response.json()["items"]] == expected


def test_inventory_list_returns_each_products_reorder_level(client):
    created = client.post("/api/products/", json={
        "sku": "REORDER-50", "name": "Custom Reorder", "price": 10, "gst_rate": 0,
        "reorder_level": 50,
    })
    assert created.status_code == 200, created.text
    adjusted = client.post("/api/inventory/adjust", json={
        "product_id": created.json()["id"], "quantity": 20,
    })
    assert adjusted.status_code == 200, adjusted.text

    response = client.get("/api/inventory/", params={"search": "REORDER-50"})

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["reorder_level"] == 50
    assert response.json()["items"][0]["quantity"] == 20
    metrics = client.get("/api/dashboard/metrics")
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["inventory"]["low_stock_count"] == 1
    assert metrics.json()["inventory"]["out_of_stock_count"] == 0


def test_adjust_inventory_rejects_untracked_product(client):
    create_response = client.post(
        "/api/products/",
        json={
            "sku": "UNTRACKED02",
            "name": "Subscription Setup",
            "price": 200,
            "gst_rate": 18,
            "maintain_inventory": False,
        },
    )
    assert create_response.status_code == 200

    product_id = create_response.json()["id"]
    adjust_response = client.post(
        "/api/inventory/adjust",
        json={"product_id": product_id, "quantity": 1},
    )
    assert adjust_response.status_code == 400
    assert adjust_response.json()["detail"] == "Inventory is disabled for this product"


def test_adjust_inventory_rejects_fractional_quantity_for_whole_number_product(client):
    create_response = client.post(
        "/api/products/",
        json={
            "sku": "WHOLEINV1",
            "name": "Whole Count Item",
            "price": 120,
            "gst_rate": 18,
            "allow_decimal": False,
        },
    )
    assert create_response.status_code == 200

    product_id = create_response.json()["id"]
    adjust_response = client.post(
        "/api/inventory/adjust",
        json={"product_id": product_id, "quantity": 1.5},
    )
    assert adjust_response.status_code == 400
    assert adjust_response.json()["detail"] == "Quantity must be a whole number for this product"


def test_adjust_inventory_accepts_fractional_quantity_for_decimal_product(client):
    create_response = client.post(
        "/api/products/",
        json={
            "sku": "DECINV1",
            "name": "Liquid Product",
            "price": 90,
            "gst_rate": 18,
            "unit": "l",
            "allow_decimal": True,
        },
    )
    assert create_response.status_code == 200

    product_id = create_response.json()["id"]
    adjust_response = client.post(
        "/api/inventory/adjust",
        json={"product_id": product_id, "quantity": 1.5},
    )
    assert adjust_response.status_code == 200

    list_response = client.get("/api/inventory/?search=Liquid&page=1&page_size=20")
    assert list_response.status_code == 200
    item = list_response.json()["items"][0]
    assert item["unit"] == "l"
    assert item["allow_decimal"] is True
    assert item["quantity"] == 1.5


def _decimal_product(client, sku: str = "DECINVNF"):
    created = client.post(
        "/api/products/",
        json={
            "sku": sku,
            "name": "Liquid Product",
            "price": 90,
            "gst_rate": 18,
            "unit": "l",
            "allow_decimal": True,
            "initial_quantity": 2,
        },
    )
    assert created.status_code == 200
    return created.json()["id"]


def test_adjust_inventory_rejects_nan_quantity(client):
    product_id = _decimal_product(client, "DECINVNAN")
    response = client.post(
        "/api/inventory/adjust",
        content=f'{{"product_id": {product_id}, "quantity": NaN}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    listing = client.get("/api/inventory/?search=Liquid&page=1&page_size=50")
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["sku"] == "DECINVNAN")
    assert item["quantity"] == 2


def test_adjust_inventory_rejects_infinity_quantity(client):
    product_id = _decimal_product(client, "DECINVINF")
    response = client.post(
        "/api/inventory/adjust",
        content=f'{{"product_id": {product_id}, "quantity": Infinity}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    listing = client.get("/api/inventory/?search=Liquid&page=1&page_size=50")
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["sku"] == "DECINVINF")
    assert item["quantity"] == 2


def test_adjust_inventory_rejects_negative_infinity_quantity(client):
    product_id = _decimal_product(client, "DECINVNINF")
    response = client.post(
        "/api/inventory/adjust",
        content=f'{{"product_id": {product_id}, "quantity": -Infinity}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    listing = client.get("/api/inventory/?search=Liquid&page=1&page_size=50")
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["sku"] == "DECINVNINF")
    assert item["quantity"] == 2


def test_produce_saves_notes_in_production_history(client, db_session):
    finished = _make_producible_setup(db_session)

    produce_response = client.post(
        "/api/inventory/produce",
        json={"product_id": finished.id, "quantity": 1, "notes": "Batch 7"},
    )
    assert produce_response.status_code == 200, produce_response.text

    history_response = client.get("/api/inventory/production-history")
    assert history_response.status_code == 200

    items = history_response.json()["items"]
    assert len(items) == 1
    assert items[0]["notes"] == "Batch 7"


def test_produce_stores_blank_notes_as_null(client, db_session):
    finished = _make_producible_setup(db_session)

    produce_response = client.post(
        "/api/inventory/produce",
        json={"product_id": finished.id, "quantity": 1, "notes": "   "},
    )
    assert produce_response.status_code == 200, produce_response.text

    history_response = client.get("/api/inventory/production-history")
    assert history_response.status_code == 200
    assert history_response.json()["items"][0]["notes"] is None


def test_produce_without_notes_field_still_works(client, db_session):
    finished = _make_producible_setup(db_session)

    produce_response = client.post(
        "/api/inventory/produce",
        json={"product_id": finished.id, "quantity": 2},
    )
    assert produce_response.status_code == 200, produce_response.text

    history_response = client.get("/api/inventory/production-history")
    assert history_response.status_code == 200
    items = history_response.json()["items"]
    assert len(items) == 1
    assert items[0]["notes"] is None
    assert items[0]["quantity_produced"] == 2


def test_sale_with_no_stock_says_how_much_is_short_and_names_the_product(client):
    product = client.post(
        "/api/products/",
        json={"sku": "NOSTOCK1", "name": "Cordless Drill 500W", "price": 100, "gst_rate": 18,
              "maintain_inventory": True, "initial_quantity": 0},
    ).json()
    ledger = client.post(
        "/api/ledgers/",
        json={"name": "Walk-in", "address": "1 Main St", "gst": "27AADCB2230M1ZT",
              "phone_number": "9876543210", "email": "a@example.com", "website": "",
              "bank_name": "", "branch_name": "", "account_name": "", "account_number": "",
              "ifsc_code": "", "opening_balance": 0},
    ).json()

    response = client.post(
        "/api/invoices/",
        json={"ledger_id": ledger["id"], "voucher_type": "sales", "tax_inclusive": False,
              "apply_round_off": False,
              "items": [{"product_id": product["id"], "quantity": 3, "unit_price": 100}]},
    )

    assert response.status_code == 400
    body = response.json()
    assert "Cordless Drill 500W: only 0 in stock, and this invoice needs 3" in body["detail"]
    assert body["code"] == "insufficient_stock"
    assert body["product_id"] == product["id"]
    assert (body["available"], body["required"]) == ("0", "3")
