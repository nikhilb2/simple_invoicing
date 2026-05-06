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


def _create_product(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "REF-NOTE-001",
            "name": "Reference Notes Product",
            "description": "",
            "hsn_sac": "9988",
            "price": 100,
            "gst_rate": 18,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _add_inventory(client, product_id: int, quantity: int):
    response = client.post(
        "/api/inventory/adjust",
        json={
            "product_id": product_id,
            "quantity": quantity,
        },
    )
    assert response.status_code == 200, response.text


def test_sales_invoice_reference_notes_round_trip(client):
    with patch("src.services.invoice_processor.generate_next_number", return_value="SAL-000001"):
        ledger_id = _create_ledger(client, name="Sales Ledger", gst="27ABCDE9999F1Z5")
        product_id = _create_product(client)
        _add_inventory(client, product_id=product_id, quantity=20)

        create_response = client.post(
            "/api/invoices/",
            json={
                "ledger_id": ledger_id,
                "voucher_type": "sales",
                "reference_notes": "PO-2026-001",
                "tax_inclusive": False,
                "apply_round_off": False,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 100}],
            },
        )

        assert create_response.status_code == 200, create_response.text
        created_invoice = create_response.json()
        assert created_invoice["reference_notes"] == "PO-2026-001"

        get_response = client.get(f"/api/invoices/{created_invoice['id']}")
        assert get_response.status_code == 200, get_response.text
        assert get_response.json()["reference_notes"] == "PO-2026-001"

        update_response = client.put(
            f"/api/invoices/{created_invoice['id']}",
            json={
                "ledger_id": ledger_id,
                "voucher_type": "sales",
                "reference_notes": "PO-2026-002",
                "tax_inclusive": False,
                "apply_round_off": False,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 100}],
            },
        )

        assert update_response.status_code == 200, update_response.text
        assert update_response.json()["reference_notes"] == "PO-2026-002"
