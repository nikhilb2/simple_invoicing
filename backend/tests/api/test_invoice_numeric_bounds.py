"""Reject amounts that would overflow the invoice columns on PostgreSQL."""
import pytest


@pytest.fixture
def sale(client):
    ledger = client.post("/api/ledgers/", json={
        "name": "Bounds customer", "address": "Test", "phone_number": "1234567890",
    })
    assert ledger.status_code == 200, ledger.text
    product = client.post("/api/products/", json={
        "sku": "BOUNDS", "name": "Bounds product", "price": 10, "gst_rate": 0,
        "allow_decimal": True, "initial_quantity": 10000,
    })
    assert product.status_code == 200, product.text
    return ledger.json()["id"], product.json()["id"]


def _invoice(sale, *lines, **fields):
    ledger_id, product_id = sale
    return {
        "ledger_id": ledger_id,
        "items": [
            {"product_id": product_id, "quantity": 1, "unit_price": 10, **line}
            for line in lines or ({},)
        ],
        **fields,
    }


def _inventory(client):
    response = client.get("/api/inventory/")
    assert response.status_code == 200, response.text
    return response.json()["items"][0]["quantity"]


@pytest.mark.parametrize("lines,fields,status", [
    ([{"unit_price": 100_000_000}], {}, 422),
    ([{"unit_price": 99_999_999.995, "discount_type": "net", "discount_value": 1}], {}, 400),
    ([{"quantity": 1_000_000_000, "unit_price": 0}], {}, 422),
    ([{"quantity": 999_999_999.9995, "unit_price": 0}], {}, 400),
    ([{"discount_type": "net", "discount_value": 1_000_000_000}], {}, 422),
    ([{}], {"discount_type": "net", "discount_value": 1_000_000_000}, 422),
    ([{"quantity": 2000, "unit_price": 100_000}], {}, 400),
    ([{"unit_price": 60_000_000}, {"unit_price": 60_000_000}], {}, 400),
    ([{"unit_price": 99_999_999.99}], {"apply_round_off": True}, 400),
])
def test_create_and_edit_reject_invoice_overflow_without_changing_stock(client, sale, lines, fields, status):
    payload = _invoice(sale, *lines, **fields)
    rejected = client.post("/api/invoices/", json=payload)
    assert rejected.status_code == status, rejected.text
    detail = str(rejected.json()["detail"]).replace(",", "")
    assert "100000000" in detail
    assert _inventory(client) == 10000

    valid = client.post("/api/invoices/", json=_invoice(sale))
    assert valid.status_code == 200, valid.text
    saved = valid.json()
    rejected_edit = client.put(f"/api/invoices/{saved['id']}", json=payload)
    assert rejected_edit.status_code == status, rejected_edit.text
    assert _inventory(client) == 9999
    response = client.get(f"/api/invoices/{saved['id']}")
    assert response.status_code == 200, response.text
    unchanged = response.json()
    assert unchanged["total_amount"] == 10
    assert unchanged["invoice_number"] == saved["invoice_number"]


def test_largest_representable_invoice_total_is_accepted(client, sale):
    response = client.post("/api/invoices/", json=_invoice(sale, {"unit_price": 99_999_999.99}))
    assert response.status_code == 200, response.text
    assert response.json()["total_amount"] == 99_999_999.99
