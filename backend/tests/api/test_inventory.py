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
    assert payload["items"][0]["quantity"] == 0