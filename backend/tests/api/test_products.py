

def test_create_product(client):
    response = client.post("/api/products/", json={
        "sku": "SKU01",
        "name": "Test",
        "price": 10,
        "gst_rate": 18
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["unit"] == "Pieces"
    assert payload["allow_decimal"] is False
 

def test_duplicate_sku(client):
    data = {
        "sku": "DUP1",
        "name": "Test",
        "price": 10,
        "gst_rate": 18
    }

    client.post("/api/products/", json=data)
    response = client.post("/api/products/", json=data)

    assert response.status_code == 400

# Returns 400 when GST value is wrong for higher and lower ends
def test_invalid_gst(client):
    response = client.post('/api/products/', json={
        "sku": "PRO100",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": 110
    })

    assert response.status_code == 400

    response = client.post('/api/products/', json={
        "sku": "PRO101",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": -10
    })

    assert response.status_code == 400

# Creates a test product and tries to get the data back.
def test_get_products(client):
    client.post('/api/products/', json={
        "sku": "PRO123",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": 5
    })

    response = client.get("/api/products/")

    assert response.status_code == 200

def test_search_products(client):
    client.post("/api/products/", json={
        "sku": "S1",
        "name": "Apple",
        "price": 10,
        "gst_rate": 5
    })

    response = client.get("/api/products/?search=Apple")

    assert response.status_code == 200


def test_create_untracked_product_skips_inventory(client, db_session):
    response = client.post(
        "/api/products/",
        json={
            "sku": "SERV001",
            "name": "Service Charge",
            "price": 250,
            "gst_rate": 18,
            "maintain_inventory": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["maintain_inventory"] is False

    from src.models.inventory import Inventory

    inventory = db_session.query(Inventory).filter(Inventory.product_id == payload["id"]).first()
    assert inventory is None


def test_create_untracked_product_rejects_initial_quantity(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "SERV002",
            "name": "Service Charge",
            "price": 100,
            "gst_rate": 18,
            "maintain_inventory": False,
            "initial_quantity": 10,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Initial quantity is only allowed when maintain inventory is enabled"


def test_toggle_untracked_product_on_creates_inventory_row(client, db_session):
    create_response = client.post(
        "/api/products/",
        json={
            "sku": "SERV003",
            "name": "AMC Plan",
            "price": 499,
            "gst_rate": 18,
            "maintain_inventory": False,
        },
    )
    assert create_response.status_code == 200
    product_id = create_response.json()["id"]

    update_response = client.put(
        f"/api/products/{product_id}",
        json={
            "sku": "SERV003",
            "name": "AMC Plan",
            "price": 499,
            "gst_rate": 18,
            "maintain_inventory": True,
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["maintain_inventory"] is True

    from src.models.inventory import Inventory

    inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
    assert inventory is not None
    assert inventory.quantity == 0


def test_create_product_with_custom_unit_and_allow_decimal(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "UNITKG1",
            "name": "Fine Flour",
            "price": 45,
            "gst_rate": 5,
            "unit": "Kg",
            "allow_decimal": True,
            "maintain_inventory": True,
            "initial_quantity": 2.75,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["unit"] == "Kg"
    assert payload["allow_decimal"] is True


def test_reject_fractional_initial_quantity_when_decimal_disabled(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "WHOLEONLY1",
            "name": "Whole Unit Item",
            "price": 30,
            "gst_rate": 5,
            "unit": "Pieces",
            "allow_decimal": False,
            "maintain_inventory": True,
            "initial_quantity": 1.25,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Initial quantity must be a whole number for this product"