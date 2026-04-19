from datetime import datetime, timedelta
from unittest.mock import patch


def _create_ledger(client):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": "Dues Ledger",
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
            "sku": "DUE-001",
            "name": "Due Product",
            "description": "",
            "hsn_sac": "9988",
            "price": 100,
            "gst_rate": 0,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _add_inventory(client, product_id, quantity=50):
    response = client.post(
        "/api/inventory/adjust",
        json={"product_id": product_id, "quantity": quantity},
    )
    assert response.status_code == 200, response.text


def _create_invoice(client, ledger_id, product_id, unit_price, due_date, invoice_date):
    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "sales",
            "tax_inclusive": False,
            "apply_round_off": False,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": unit_price}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_receipt(client, ledger_id, amount, allocations, dt):
    response = client.post(
        "/api/payments/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "receipt",
            "amount": amount,
            "date": dt,
            "mode": "bank",
            "invoice_allocations": allocations,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_dues_endpoint_excludes_fully_paid_invoices(client):
    today = datetime.utcnow().date()
    invoice_date = today.isoformat()

    invoice_numbers = iter(["INV-000001", "INV-000002"])
    with patch(
        "src.api.routes.invoices._generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ), patch(
        "src.api.routes.payments.generate_next_number",
        return_value="PAY-000001",
    ):
        ledger_id = _create_ledger(client)
        product_id = _create_product(client)
        _add_inventory(client, product_id)

        overdue_invoice = _create_invoice(
            client,
            ledger_id,
            product_id,
            100,
            (today - timedelta(days=2)).isoformat(),
            invoice_date,
        )
        fully_paid_invoice = _create_invoice(
            client,
            ledger_id,
            product_id,
            120,
            (today + timedelta(days=3)).isoformat(),
            invoice_date,
        )

        _create_receipt(
            client,
            ledger_id,
            120,
            [{"invoice_id": fully_paid_invoice["id"], "allocated_amount": 120}],
            datetime.utcnow().isoformat(),
        )

        dues_response = client.get(
            "/api/invoices/dues",
            params={
                "page": 1,
                "page_size": 20,
            },
        )
        assert dues_response.status_code == 200, dues_response.text

        body = dues_response.json()
        returned_ids = {item["id"] for item in body["items"]}
        assert overdue_invoice["id"] in returned_ids
        assert fully_paid_invoice["id"] not in returned_ids


def test_unpaid_invoices_returns_oldest_first_suggestions(client):
    today = datetime.utcnow().date()

    invoice_numbers = iter(["INV-000101", "INV-000102"])
    with patch(
        "src.api.routes.invoices._generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ):
        ledger_id = _create_ledger(client)
        product_id = _create_product(client)
        _add_inventory(client, product_id)

        oldest = _create_invoice(
            client,
            ledger_id,
            product_id,
            100,
            (today - timedelta(days=5)).isoformat(),
            (today - timedelta(days=10)).isoformat(),
        )
        newest = _create_invoice(
            client,
            ledger_id,
            product_id,
            100,
            (today + timedelta(days=5)).isoformat(),
            (today - timedelta(days=1)).isoformat(),
        )

        response = client.get(
            f"/api/ledgers/{ledger_id}/unpaid-invoices",
            params={"voucher_type": "receipt", "amount": 150},
        )
        assert response.status_code == 200, response.text

        rows = response.json()
        by_id = {row["id"]: row for row in rows}

        assert by_id[oldest["id"]]["suggested_allocation_amount"] == 100
        assert by_id[newest["id"]]["suggested_allocation_amount"] == 50
