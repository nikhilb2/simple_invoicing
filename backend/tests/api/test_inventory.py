from src.models.inventory import Inventory


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