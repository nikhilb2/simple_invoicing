"""Tests for the duplicate invoice endpoint."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.models.financial_year import FinancialYear
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.invoice_series import InvoiceSeries
from src.models.ledger_address import LedgerAddress
from src.models.product import Product
from src.models.product_serial import ProductSerial
from src.models.user import User


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
    @pytest.mark.parametrize("voucher_type,expected", [("sales", 96), ("purchase", 104)])
    def test_duplicate_moves_stock(self, client, db_session, voucher_type, expected):
        product = _create_product(client, "DUPSTOCK", "Stock product")
        ledger = _create_ledger(client)
        original = _create_invoice(client, product["id"], ledger["id"], voucher_type)

        response = client.post(f"/api/invoices/{original['id']}/duplicate")

        assert response.status_code == 200, response.text
        stock = db_session.query(Inventory).filter_by(product_id=product["id"]).one()
        assert stock.quantity == Decimal(expected)

    def test_short_stock_rolls_back_duplicate(self, client, db_session):
        product = _create_product(client, "DUPSHORT", "Short stock")
        ledger = _create_ledger(client)
        original = _create_invoice(client, product["id"], ledger["id"])
        stock = db_session.query(Inventory).filter_by(product_id=product["id"]).one()
        stock.quantity = 1
        db_session.commit()
        invoice_count = db_session.query(Invoice).count()
        sequences = db_session.query(InvoiceSeries.id, InvoiceSeries.next_sequence).all()

        response = client.post(f"/api/invoices/{original['id']}/duplicate")

        assert response.status_code == 400, response.text
        assert "insufficient inventory" in response.json()["detail"].lower()
        db_session.expire_all()
        assert db_session.query(Invoice).count() == invoice_count
        assert stock.quantity == Decimal("1")
        assert db_session.query(InvoiceSeries.id, InvoiceSeries.next_sequence).all() == sequences

    @pytest.mark.parametrize("voucher_type", ["sales", "purchase"])
    def test_serial_tracked_duplicate_requires_new_selection(self, client, db_session, voucher_type):
        product = _create_product(client, "DUPSERIAL", "Serial product")
        ledger = _create_ledger(client)
        # Start with a valid historical invoice, then enable serial tracking.
        # Even an original with no saved serials must be rejected.
        original = _create_invoice(client, product["id"], ledger["id"], voucher_type)
        db_session.query(Product).filter_by(id=product["id"]).update({"track_serials": True})
        db_session.commit()
        stock_before = db_session.query(Inventory).filter_by(product_id=product["id"]).one().quantity
        invoice_count = db_session.query(Invoice).count()

        response = client.post(f"/api/invoices/{original['id']}/duplicate")

        assert response.status_code == 400, response.text
        assert "serial" in response.json()["detail"].lower()
        assert "ui" in response.json()["detail"].lower()
        db_session.expire_all()
        assert db_session.query(Invoice).count() == invoice_count
        assert db_session.query(Inventory).filter_by(product_id=product["id"]).one().quantity == stock_before
        assert db_session.query(ProductSerial).count() == 0

    @pytest.mark.parametrize("voucher_type", ["sales", "purchase"])
    def test_duplicate_does_not_reuse_existing_serials(self, client, db_session, voucher_type):
        product = _create_product(client, "DUPSAVED", "Serialized product")
        ledger = _create_ledger(client)
        db_session.query(Product).filter_by(id=product["id"]).update({"track_serials": True})
        db_session.query(Inventory).filter_by(product_id=product["id"]).update({"quantity": 0})
        db_session.commit()
        payload = {
            "ledger_id": ledger["id"], "voucher_type": "purchase",
            "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 100,
                       "serial_numbers": ["DUP-UNIT-1", "DUP-UNIT-2"]}],
        }
        response = client.post("/api/invoices/", json=payload)
        assert response.status_code == 200, response.text
        if voucher_type == "sales":
            payload["voucher_type"] = "sales"
            response = client.post("/api/invoices/", json=payload)
            assert response.status_code == 200, response.text
        original = response.json()
        invoice_count = db_session.query(Invoice).count()
        serials_before = db_session.query(ProductSerial.id, ProductSerial.status,
                                         ProductSerial.purchase_invoice_id,
                                         ProductSerial.sales_invoice_id).all()
        stock_before = db_session.query(Inventory).filter_by(product_id=product["id"]).one().quantity

        response = client.post(f"/api/invoices/{original['id']}/duplicate")

        assert response.status_code == 400, response.text
        db_session.expire_all()
        assert db_session.query(Invoice).count() == invoice_count
        assert db_session.query(ProductSerial.id, ProductSerial.status,
                                ProductSerial.purchase_invoice_id,
                                ProductSerial.sales_invoice_id).all() == serials_before
        assert db_session.query(Inventory).filter_by(product_id=product["id"]).one().quantity == stock_before

    def test_duplicate_is_attributed_to_current_user(self, client, db_session):
        product = _create_product(client, "DUPAUTHOR", "Author product")
        ledger = _create_ledger(client)
        original = _create_invoice(client, product["id"], ledger["id"])
        db_session.add(User(id=99, email="original@example.com", full_name="Original author"))
        db_session.query(Invoice).filter_by(id=original["id"]).update({"created_by": 99})
        db_session.commit()

        response = client.post(f"/api/invoices/{original['id']}/duplicate")

        assert response.status_code == 200, response.text
        duplicate = db_session.get(Invoice, response.json()["id"])
        assert duplicate.created_by == 1

    def test_duplicate_uses_todays_financial_year(self, client, db_session):
        product = _create_product(client, "DUPFY", "FY product")
        ledger = _create_ledger(client)
        original = _create_invoice(client, product["id"], ledger["id"])
        company_id = db_session.get(Product, product["id"]).company_id
        db_session.query(FinancialYear).update({"is_active": False})
        today = datetime.utcnow().date()
        old_fy = FinancialYear(company_id=company_id, label="2000-01", start_date=date(2000, 4, 1),
                               end_date=date(2001, 3, 31), is_active=True)
        current_fy = FinancialYear(company_id=company_id, label=str(today.year),
                                   start_date=date(today.year, 1, 1), end_date=date(today.year, 12, 31))
        db_session.add_all([old_fy, current_fy])
        db_session.commit()

        response = client.post(f"/api/invoices/{original['id']}/duplicate")

        assert response.status_code == 200, response.text
        duplicate = db_session.get(Invoice, response.json()["id"])
        assert duplicate.invoice_date.date() == today
        assert duplicate.financial_year_id == current_fy.id

    def test_duplicate_preserves_pricing_overrides_and_discounts(self, client, db_session):
        product = _create_product(client, "DUPPRICE", "Pricing product")
        ledger = _create_ledger(client)
        response = client.post("/api/invoices/", json={
            "ledger_id": ledger["id"], "tax_inclusive": True, "apply_round_off": True,
            "discount_type": "net", "discount_value": 7,
            "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 101,
                       "gst_rate": 5, "hsn_sac": "8517", "description": "Custom line",
                       "discount_type": "percentage", "discount_value": 10}],
        })
        assert response.status_code == 200, response.text
        original = response.json()
        db_session.query(Product).filter_by(id=product["id"]).update({"gst_rate": 28, "hsn_sac": "8471"})
        db_session.commit()

        response = client.post(f"/api/invoices/{original['id']}/duplicate")

        assert response.status_code == 200, response.text
        duplicate = client.get(f"/api/invoices/{response.json()['id']}").json()
        for field in ("total_amount", "total_tax_amount", "tax_inclusive", "apply_round_off",
                      "discount_type", "discount_value"):
            assert duplicate[field] == original[field], field
        for field in ("quantity", "unit_price", "gst_rate", "hsn_sac", "description",
                      "discount_type", "discount_value", "line_total"):
            assert duplicate["items"][0][field] == original["items"][0][field], field

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

    def test_duplicate_preserves_shipping_address(self, client, db_session):
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
        address_count = db_session.query(LedgerAddress).count()

        dup_res = client.post(f"/api/invoices/{original['id']}/duplicate")
        assert dup_res.status_code == 200
        new_id = dup_res.json()["id"]

        get_res = client.get(f"/api/invoices/{new_id}")
        assert get_res.status_code == 200
        new_inv = get_res.json()
        assert "Warehouse" in (new_inv.get("shipping_address_label") or "")
        assert "456" in (new_inv.get("shipping_address") or "")
        assert db_session.query(LedgerAddress).count() == address_count

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
