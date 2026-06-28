from unittest.mock import patch


def _create_ledger(client, name: str, gst: str):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": name,
            "address": "Mumbai",
            "gst": gst,
            "phone_number": "9999999999",
            "email": f"{name.lower().replace(' ', '')}@example.com",
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


def _create_product(client, *, sku: str, name: str, initial_quantity: int):
    response = client.post(
        "/api/products/",
        json={
            "sku": sku,
            "name": name,
            "price": 10,
            "gst_rate": 18,
            "maintain_inventory": True,
            "initial_quantity": initial_quantity,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_invoice(client, *, ledger_id: int, product_id: int, quantity: int):
    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "sales",
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [{"product_id": product_id, "quantity": quantity, "unit_price": 10}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_dashboard_summary_uses_full_dataset_instead_of_paginated_lists(client):
    first_product_id = None
    for index in range(101):
        product_id = _create_product(
            client,
            sku=f"DASH-{index:03d}",
            name=f"Dashboard Product {index:03d}",
            initial_quantity=1,
        )
        if first_product_id is None:
            first_product_id = product_id

    ledger_id = _create_ledger(client, name="Dashboard Ledger", gst="27ABCDE1234F1Z5")
    invoice_numbers = iter([f"INV-{index:03d}" for index in range(101)])

    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ):
        for _ in range(101):
            _create_invoice(client, ledger_id=ledger_id, product_id=first_product_id, quantity=1)

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["product_count"] == 101
    assert payload["tracked_inventory_rows"] == 101
    assert payload["total_inventory_units"] == 101
    assert payload["low_stock_count"] == 101
    assert payload["active_invoice_total"] == 1010
    assert len(payload["low_stock_items"]) == 5
    assert len(payload["recent_invoices"]) == 6
    assert payload["recent_invoices"][0]["invoice_number"] == "INV-100"
