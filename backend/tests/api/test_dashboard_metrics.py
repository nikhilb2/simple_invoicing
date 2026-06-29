from datetime import datetime, timedelta


def _create_product(client, sku, name, price, **extra):
    payload = {"sku": sku, "name": name, "price": price, "gst_rate": 18}
    payload.update(extra)
    response = client.post("/api/products/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_ledger(client, name):
    response = client.post(
        "/api/ledgers/",
        json={"name": name, "address": "1 Market St", "phone_number": "1234567890"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_dashboard_metrics_aggregates_across_all_invoices(client):
    # Two products, one with a reorder level so we can exercise low-stock logic.
    low_product = _create_product(client, "DASH-LOW", "Low Stock Widget", 100, reorder_level=10)
    ok_product = _create_product(client, "DASH-OK", "Healthy Widget", 50, reorder_level=0)

    # Drive stock below the reorder level on the first product.
    assert client.post("/api/inventory/adjust", json={"product_id": low_product, "quantity": 5}).status_code == 200
    assert client.post("/api/inventory/adjust", json={"product_id": ok_product, "quantity": 80}).status_code == 200

    # Create a sales invoice with two line items.
    ledger_id = _create_ledger(client, "Acme Buyer")
    invoice_payload = {
        "voucher_type": "sales",
        "ledger_id": ledger_id,
        "items": [
            {"product_id": low_product, "quantity": 2, "unit_price": 100, "gst_rate": 18},
            {"product_id": ok_product, "quantity": 4, "unit_price": 50, "gst_rate": 18},
        ],
    }
    inv_res = client.post("/api/invoices/", json=invoice_payload)
    assert inv_res.status_code == 200, inv_res.text

    res = client.get("/api/dashboard/metrics")
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["catalog"]["total_products"] == 2
    assert data["inventory"]["tracked_products"] == 2
    assert data["inventory"]["low_stock_count"] == 1  # only the reorder-level product
    assert data["sales"]["sales_invoice_count"] == 1
    assert data["sales"]["total_sales"] > 0
    assert data["receivables"]["unpaid_count"] == 1
    assert data["receivables"]["outstanding_amount"] > 0

    # Charts always span the trailing 12 months and surface the sold products.
    assert len(data["charts"]["monthly"]) == 12
    assert any(point["sales"] > 0 for point in data["charts"]["monthly"])
    top_names = {p["name"] for p in data["charts"]["top_products"]}
    assert "Low Stock Widget" in top_names


def test_dashboard_metrics_empty_company(client):
    res = client.get("/api/dashboard/metrics")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["catalog"]["total_products"] == 0
    assert data["sales"]["total_sales"] == 0
    assert data["receivables"]["outstanding_amount"] == 0
    assert len(data["charts"]["monthly"]) == 12
    assert data["charts"]["top_products"] == []
