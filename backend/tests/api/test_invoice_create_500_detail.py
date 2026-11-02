"""Regression test for issue #426: the create-invoice 500 response must not
leak raw exception text to the client."""

from fastapi.testclient import TestClient

import src.api.routes.invoices as invoices_module


def _create_product(client: TestClient) -> dict:
    res = client.post("/api/products/", json={
        "sku": "LEAK426",
        "name": "Leak Test Product",
        "price": 100,
        "gst_rate": 18,
        "maintain_inventory": True,
        "initial_quantity": 100,
    })
    assert res.status_code == 200, f"Failed to create product: {res.text}"
    return res.json()


def _create_ledger(client: TestClient) -> dict:
    res = client.post("/api/ledgers/", json={
        "name": "Leak Test Customer",
        "address": "123 Test St",
        "gst": "27AADCB2230M1ZT",
        "phone_number": "9876543210",
        "email": "test@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
        "opening_balance": 0,
    })
    assert res.status_code == 200, f"Failed to create ledger: {res.text}"
    return res.json()


class TestCreateInvoiceDoesNotLeakException:
    def test_create_invoice_500_returns_generic_detail(self, client, monkeypatch):
        product = _create_product(client)
        ledger = _create_ledger(client)

        def _boom(*args, **kwargs):
            raise RuntimeError("SECRET-DB-DETAIL-426")

        monkeypatch.setattr(invoices_module, "get_active_fy", _boom)

        res = client.post("/api/invoices/", json={
            "ledger_id": ledger["id"],
            "voucher_type": "sales",
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [{
                "product_id": product["id"],
                "quantity": 2,
                "unit_price": 100,
            }],
        })

        assert res.status_code == 500
        assert res.json()["detail"] == "Failed to create invoice"
        assert "SECRET-DB-DETAIL-426" not in res.text
