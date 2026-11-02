"""Non-finite JSON numbers must return 422, not 500."""


def _post_product(client, body: str):
    return client.post(
        "/api/products/",
        content=body,
        headers={"Content-Type": "application/json"},
    )


def test_create_product_rejects_nan_price_with_422(client):
    response = _post_product(
        client,
        '{"sku": "NAN1", "name": "BadPrice", "price": NaN, "gst_rate": 18}',
    )
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    # Response itself must be JSON-serializable (no raw NaN).
    assert "NaN" not in response.text or isinstance(body["detail"], list)

    listing = client.get("/api/products/")
    assert listing.status_code == 200
    assert all(item["sku"] != "NAN1" for item in listing.json()["items"])


def test_create_product_rejects_infinity_price_with_422(client):
    response = _post_product(
        client,
        '{"sku": "INF1", "name": "BadPrice", "price": Infinity, "gst_rate": 18}',
    )
    assert response.status_code == 422
    assert "detail" in response.json()

    listing = client.get("/api/products/")
    assert listing.status_code == 200
    assert all(item["sku"] != "INF1" for item in listing.json()["items"])


def test_create_product_rejects_negative_infinity_price_with_422(client):
    response = _post_product(
        client,
        '{"sku": "NINF1", "name": "BadPrice", "price": -Infinity, "gst_rate": 18}',
    )
    assert response.status_code == 422
    assert "detail" in response.json()

    listing = client.get("/api/products/")
    assert listing.status_code == 200
    assert all(item["sku"] != "NINF1" for item in listing.json()["items"])


def test_create_product_still_rejects_negative_price_with_422(client):
    response = client.post(
        "/api/products/",
        json={"sku": "NEG1", "name": "BadPrice", "price": -1, "gst_rate": 18},
    )
    assert response.status_code == 422
    assert "detail" in response.json()
