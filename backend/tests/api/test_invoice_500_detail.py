"""Regression tests for issue #552: unexpected errors in the invoice endpoints
must return a generic 500 detail instead of the raw exception text."""

from fastapi.testclient import TestClient

import src.api.routes.invoices as invoices_module

SECRET = "SECRET-DB-DETAIL-552"


def _boom(*args, **kwargs):
    raise RuntimeError(SECRET)


def _create_invoice(client: TestClient) -> dict:
    product = client.post("/api/products/", json={
        "sku": "LEAK552",
        "name": "Leak Test Product 552",
        "price": 100,
        "gst_rate": 18,
        "maintain_inventory": True,
        "initial_quantity": 100,
    })
    assert product.status_code == 200, f"Failed to create product: {product.text}"

    ledger = client.post("/api/ledgers/", json={
        "name": "Leak Test Customer 552",
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
    assert ledger.status_code == 200, f"Failed to create ledger: {ledger.text}"

    res = client.post("/api/invoices/", json={
        "ledger_id": ledger.json()["id"],
        "voucher_type": "sales",
        "tax_inclusive": False,
        "apply_round_off": False,
        "items": [{
            "product_id": product.json()["id"],
            "quantity": 1,
            "unit_price": 100,
        }],
    })
    assert res.status_code == 200, f"Failed to create invoice: {res.text}"
    return res.json()


class TestInvoiceEndpointsDoNotLeakException:
    def test_list_dues_500_returns_generic_detail(self, client, monkeypatch):
        monkeypatch.setattr(invoices_module, "_outstanding_due_invoices", _boom)

        res = client.get("/api/invoices/dues")

        assert res.status_code == 500
        assert res.json()["detail"] == "Failed to list due invoices"
        assert SECRET not in res.text

    def test_dues_ageing_500_returns_generic_detail(self, client, monkeypatch):
        monkeypatch.setattr(invoices_module, "_outstanding_due_invoices", _boom)

        res = client.get("/api/invoices/dues/ageing")

        assert res.status_code == 500
        assert res.json()["detail"] == "Failed to load dues ageing summary"
        assert SECRET not in res.text

    def test_cancel_invoice_500_returns_generic_detail(self, client, monkeypatch):
        invoice = _create_invoice(client)
        monkeypatch.setattr(invoices_module, "InvoiceProcessor", _boom)

        res = client.delete(f"/api/invoices/{invoice['id']}")

        assert res.status_code == 500
        assert res.json()["detail"] == "Failed to cancel invoice"
        assert SECRET not in res.text

    def test_cancel_missing_invoice_still_returns_404(self, client):
        res = client.delete("/api/invoices/999999999")

        assert res.status_code == 404
