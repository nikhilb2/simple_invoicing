def _create_ledger(client):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": "Round Off Ledger",
            "address": "Mumbai",
            "gst": "27ABCDE1234F1Z5",
            "phone_number": "9999999999",
            "email": "ledger@example.com",
            "website": "",
            "bank_name": "",
            "branch_name": "",
            "account_name": "",
            "account_number": "",
            "ifsc_code": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_product(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "RO-001",
            "name": "Round Product",
            "description": "",
            "hsn_sac": "9988",
            "price": 100,
            "gst_rate": 18,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _add_inventory(client, product_id, quantity=10):
    response = client.post(
        "/api/inventory/adjust",
        json={"product_id": product_id, "quantity": quantity},
    )
    assert response.status_code == 200, response.text


def test_create_invoice_applies_round_off_when_enabled(client):
    ledger_id = _create_ledger(client)
    product_id = _create_product(client)
    _add_inventory(client, product_id)

    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "sales",
            "tax_inclusive": False,
            "apply_round_off": True,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": 99.99}],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["apply_round_off"] is True
    assert body["total_amount"] == 118
    assert body["round_off_amount"] == 0.01


def test_create_invoice_keeps_exact_total_when_round_off_disabled(client):
    ledger_id = _create_ledger(client)
    product_id = _create_product(client)
    _add_inventory(client, product_id)

    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "sales",
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": 99.99}],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["apply_round_off"] is False
    assert body["total_amount"] == 117.99
    assert body["round_off_amount"] == 0
