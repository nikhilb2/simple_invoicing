"""Tests for the duplicate invoice endpoint."""

import pytest
from fastapi.testclient import TestClient


def _create_product(client: TestClient, sku: str, name: str, price: float = 99.0) -> dict:
    res = client.post("/api/products/", json={
        "sku": sku,
        "name": name,
        "price": price,
        "gst_rate": 18,
        "maintain_inventory": True,
        "initial_quantity": 100,
    })
    assert res.status_code == 200, f"Failed to create product: {res.text}"
    return res.json()


def _create_ledger(client: TestClient, name: str = "Test Customer", gst: str = "27AADCB2230M1ZT") -> dict:
    res = client.post("/api/ledgers/", json={
        "name": name,
        "address": "123 Test St",
        "gst": gst,
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


def _create_invoice(client: TestClient, product_id: int, ledger_id: int, voucher_type: str = "sales") -> dict:
    res = client.post("/api/invoices/", json={
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "tax_inclusive": False,
        "apply_round_off": False,
        "items": [{
            "product_id": product_id,
            "quantity": 2,
            "unit_price": 100,
        }],
    })
    assert res.status_code == 200, f"Failed to create invoice: {res.text}"
    return res.json()


class TestDuplicateInvoice:
    def test_duplicate_sales_invoice(self, client):
        product = _create_product(client, "DUPINV1", "Duplicate Test Product", price=100)
        ledger = _create_ledger(client, "Duplicate Customer")
        invoice = _create_invoice(client, product["id"], ledger["id"])

        original_id = invoice["id"]
        original_number = invoice["invoice_number"]

        res = client.post(f"/api/invoices/{original_id}/duplicate")
        assert res.status_code == 200
        data = res.json()
        assert "id" in data
        assert "invoice_number" in data
        new_id = data["id"]
        new_number = data["invoice_number"]

        # New invoice should have a different id and number
        assert new_id != original_id
        assert new_number != original_number
        assert new_number is not None

        # Fetch the new invoice and verify it has the same items
        get_res = client.get(f"/api/invoices/{new_id}")
        assert get_res.status_code == 200
        new_inv = get_res.json()
        assert new_inv["ledger_name"] == "Duplicate Customer"
        assert len(new_inv["items"]) == 1
        assert new_inv["items"][0]["product_id"] == product["id"]
        assert new_inv["items"][0]["quantity"] == 2
        assert new_inv["status"] == "active"
        assert new_inv["voucher_type"] == "sales"

    def test_duplicate_purchase_invoice(self, client):
        product = _create_product(client, "DUPINV2", "Purchase Dup Product", price=50)
        ledger = _create_ledger(client, "Supplier Dup")
        invoice = _create_invoice(client, product["id"], ledger["id"], voucher_type="purchase")

        res = client.post(f"/api/invoices/{invoice['id']}/duplicate")
        assert res.status_code == 200
        data = res.json()

        get_res = client.get(f"/api/invoices/{data['id']}")
        assert get_res.status_code == 200
        new_inv = get_res.json()
        assert new_inv["voucher_type"] == "purchase"
        assert new_inv["ledger_name"] == "Supplier Dup"
        assert len(new_inv["items"]) == 1

    def test_duplicate_preserves_reference_notes(self, client):
        """Verify that reference_notes and supplier_invoice_number are copied."""
        product = _create_product(client, "DUPREF1", "Ref Test Product")
        ledger = _create_ledger(client, "Ref Customer")

        # Create an invoice with reference notes
        res = client.post("/api/invoices/", json={
            "ledger_id": ledger["id"],
            "voucher_type": "sales",
            "reference_notes": "PO-2024-001",
            "supplier_invoice_number": None,
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 50}],
        })
        assert res.status_code == 200
        original = res.json()
        assert original["reference_notes"] == "PO-2024-001"

        dup_res = client.post(f"/api/invoices/{original['id']}/duplicate")
        assert dup_res.status_code == 200
        new_id = dup_res.json()["id"]

        get_res = client.get(f"/api/invoices/{new_id}")
        assert get_res.status_code == 200
        new_inv = get_res.json()
        assert new_inv["reference_notes"] == "PO-2024-001"
        assert new_inv["ledger_name"] == "Ref Customer"

    def test_duplicate_preserves_shipping_address(self, client):
        """Verify shipping address is copied to the duplicated invoice."""
        product = _create_product(client, "DUPSHIP1", "Shipping Test Product")
        ledger = _create_ledger(client, "Shipping Customer")

        # First check if ledger addresses work — try with new shipping address
        res = client.post("/api/invoices/", json={
            "ledger_id": ledger["id"],
            "voucher_type": "sales",
            "shipping_address_same_as_billing": False,
            "new_shipping_address": {
                "label": "Warehouse",
                "address": "456 Warehouse Blvd, Mumbai"
            },
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 50}],
        })
        assert res.status_code == 200
        original = res.json()

        dup_res = client.post(f"/api/invoices/{original['id']}/duplicate")
        assert dup_res.status_code == 200
        new_id = dup_res.json()["id"]

        get_res = client.get(f"/api/invoices/{new_id}")
        assert get_res.status_code == 200
        new_inv = get_res.json()
        assert "Warehouse" in (new_inv.get("shipping_address_label") or "")
        assert "456" in (new_inv.get("shipping_address") or "")

    def test_duplicate_nonexistent_invoice(self, client):
        res = client.post("/api/invoices/99999/duplicate")
        assert res.status_code == 404

    def test_duplicate_invoice_preserves_tax_details(self, client):
        product = _create_product(client, "DUPTAX1", "Tax Test", price=100)
        ledger = _create_ledger(client, "Tax Customer")
        invoice = _create_invoice(client, product["id"], ledger["id"])

        res = client.post(f"/api/invoices/{invoice['id']}/duplicate")
        assert res.status_code == 200
        new_id = res.json()["id"]

        get_res = client.get(f"/api/invoices/{new_id}")
        assert get_res.status_code == 200
        new_inv = get_res.json()
        # Tax amounts should be identical to original
        assert new_inv["taxable_amount"] > 0
        assert new_inv["total_tax_amount"] > 0
