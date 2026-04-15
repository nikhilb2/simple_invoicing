

def test_create_product(client):
    response = client.post("/api/products/", json={
        "sku": "SKU01",
        "name": "Test",
        "price": 10,
        "gst_rate": 18
    })
    print(response.json())  # 👈 add this

    assert response.status_code == 200
 

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