"""
Tests for #371 — Display Item Names Instead of Product IDs/SKUs in Invoice Views and PDFs.

Covers:
- product_name enrichment on invoice item API responses
- PDF SKU column visibility controlled by show_sku setting
- company profile show_sku_on_pdf setting (default and update)
"""
from datetime import datetime
from pathlib import Path
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

import pytest

from src.api.routes.invoices import _enrich_items_with_product_names
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.user import User, UserRole
from src.services.pdf_templates.builders import _build_pdf_table_colgroup
from src.services.pdf_templates.invoice_template import _build_invoice_html


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_product(db_session, sku="SKU01", name="Test Product", price=100.0, gst_rate=18.0, company_id=1):
    """Create a product with inventory."""
    p = Product(
        sku=sku, name=name, price=price, gst_rate=gst_rate,
        company_id=company_id,
    )
    db_session.add(p)
    db_session.flush()
    inv = Inventory(product_id=p.id, quantity=100, company_id=company_id)
    db_session.add(inv)
    db_session.flush()
    return p


def _make_invoice_item(product_id=1, quantity=2.0, unit_price=100.0,
                       taxable_amount=200.0, tax_amount=36.0,
                       cgst_amount=18.0, sgst_amount=18.0,
                       line_total=236.0, gst_rate=18.0, description=None):
    """Create an InvoiceItem for testing."""
    item = InvoiceItem()
    item.id = product_id
    item.product_id = product_id
    item.quantity = quantity
    item.unit_price = unit_price
    item.taxable_amount = taxable_amount
    item.tax_amount = tax_amount
    item.cgst_amount = cgst_amount
    item.sgst_amount = sgst_amount
    item.igst_amount = 0.0
    item.line_total = line_total
    item.gst_rate = gst_rate
    item.description = description
    return item


# ─────────────────────────────────────────────────────────────────────────────
# product_name enrichment tests (unit tests using db_session)
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrichItemsWithProductNames:
    """Test the _enrich_items_with_product_names helper."""

    def test_enriches_items_with_product_names(self, db_session):
        """Items get product_name from the products table."""
        company = CompanyProfile(name="Test", address="A", currency_code="INR")
        db_session.add(company)
        db_session.flush()
        product = _make_product(db_session, sku="SKU01", name="Samsung LED TV", company_id=company.id)
        invoice = Invoice(total_amount=100, created_by=1, company_id=company.id)
        db_session.add(invoice)
        db_session.flush()
        item = InvoiceItem(
            invoice_id=invoice.id, product_id=product.id,
            quantity=1, unit_price=100, line_total=100,
        )
        db_session.add(item)
        db_session.flush()

        _enrich_items_with_product_names([invoice], db_session, company.id)

        assert getattr(invoice.items[0], "product_name") == "Samsung LED TV"

    def test_handles_missing_product_gracefully(self, db_session):
        """When product doesn't exist, product_name is None."""
        company = CompanyProfile(name="Test", address="A", currency_code="INR")
        db_session.add(company)
        db_session.flush()
        invoice = Invoice(total_amount=100, created_by=1, company_id=company.id)
        db_session.add(invoice)
        db_session.flush()
        item = InvoiceItem(
            invoice_id=invoice.id, product_id=9999,
            quantity=1, unit_price=100, line_total=100,
        )
        db_session.add(item)
        db_session.flush()

        _enrich_items_with_product_names([invoice], db_session, company.id)

        assert getattr(invoice.items[0], "product_name") is None

    def test_handles_empty_items(self, db_session):
        """Invoice with no items doesn't fail."""
        company = CompanyProfile(name="Test", address="A", currency_code="INR")
        db_session.add(company)
        db_session.flush()
        invoice = Invoice(total_amount=0, created_by=1, company_id=company.id)
        db_session.add(invoice)
        db_session.flush()

        # Should not raise
        _enrich_items_with_product_names([invoice], db_session, company.id)
        assert invoice.items == []


# ─────────────────────────────────────────────────────────────────────────────
# PDF SKU column visibility tests
# ─────────────────────────────────────────────────────────────────────────────

def _pdf_test_prod():
    return SimpleNamespace(
        id=1, name="Samsung LED TV", sku="SKU123",
        hsn_sac="8528", unit="Pieces", allow_decimal=False,
    )


def _pdf_test_invoice(voucher_type="sales"):
    inv = Invoice(
        id=1,
        invoice_number="INV-001",
        ledger_name="Buyer One",
        ledger_address="Buyer Address",
        ledger_gst="07AABB1234C1Z5",
        company_name="Seller One",
        company_address="Seller Address",
        company_gst="07AAMPB1274B1Z8",
        company_currency_code="INR",
        voucher_type=voucher_type,
        created_by=1,
        taxable_amount=200,
        total_tax_amount=36,
        cgst_amount=18,
        sgst_amount=18,
        igst_amount=0,
        total_amount=236,
        invoice_date=datetime(2026, 4, 15),
    )
    item = _make_invoice_item(
        product_id=1, quantity=2.0, unit_price=100.0,
        taxable_amount=200.0, tax_amount=36.0,
        cgst_amount=18.0, sgst_amount=18.0, line_total=236.0,
    )
    inv.items = [item]
    return inv


class TestPdfSkuColumnVisibility:
    """Test that the PDF template respects show_sku parameter."""

    def test_sku_column_present_when_show_sku_true(self):
        """SKU column header and SKU data appear when show_sku=True."""
        inv = _pdf_test_invoice()
        prod = _pdf_test_prod()
        html = _build_invoice_html(inv, [prod], show_sku=True)
        assert "<th>SKU</th>" in html
        assert "<td>SKU123</td>" in html

    def test_sku_column_absent_when_show_sku_false(self):
        """SKU column header and SKU data are absent when show_sku=False."""
        inv = _pdf_test_invoice()
        prod = _pdf_test_prod()
        html = _build_invoice_html(inv, [prod], show_sku=False)
        assert "<th>SKU</th>" not in html
        assert "<td>SKU123</td>" not in html

    def test_sku_hidden_does_not_remove_hsn_column(self):
        """HSN/SAC column still present even when SKU is hidden."""
        inv = _pdf_test_invoice()
        prod = _pdf_test_prod()
        html = _build_invoice_html(inv, [prod], show_sku=False)
        assert "<th>HSN/SAC</th>" in html
        assert "<td>8528</td>" in html

    def test_item_description_wider_when_sku_hidden_intrastate(self):
        """Item description col gets extra width from SKU when hidden (intrastate)."""
        colgroup_without = _build_pdf_table_colgroup(interstate_supply=False, show_sku=False)
        # Intrastate: Item col goes from 16% to 22% (SKU 6% redistributed)
        assert "width: 22%" in colgroup_without

    def test_item_description_wider_when_sku_hidden_interstate(self):
        """Item description col gets extra width from SKU when hidden (interstate)."""
        colgroup_without = _build_pdf_table_colgroup(interstate_supply=True, show_sku=False)
        # Interstate: Item col goes from 20% to 27% (SKU 7% redistributed)
        assert "width: 27%" in colgroup_without


# ─────────────────────────────────────────────────────────────────────────────
# Helper for API-level tests (creating invoices through the client)
# ─────────────────────────────────────────────────────────────────────────────

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


def _create_product(client, sku: str, name: str):
    response = client.post(
        "/api/products/",
        json={
            "sku": sku,
            "name": name,
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


# ─────────────────────────────────────────────────────────────────────────────
# company profile show_sku_on_pdf setting tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCompanyShowSkuSetting:
    """Test the show_sku_on_pdf company setting."""

    def test_new_company_defaults_to_show_sku_false(self, client):
        """A new company profile should have show_sku_on_pdf=False by default."""
        resp = client.get("/api/company/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["show_sku_on_pdf"] is False

    def test_update_company_show_sku_to_true(self, client):
        """Can update show_sku_on_pdf to True."""
        resp = client.put("/api/company/", json={
            "name": "My Company",
            "address": "123 Main St",
            "gst": "",
            "phone_number": "",
            "currency_code": "INR",
            "email": "",
            "website": "",
            "show_sku_on_pdf": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["show_sku_on_pdf"] is True

    def test_update_company_show_sku_to_false(self, client):
        """Can toggle show_sku_on_pdf back to False."""
        # First set to True
        client.put("/api/company/", json={
            "name": "My Company",
            "address": "123 Main St",
            "gst": "",
            "phone_number": "",
            "currency_code": "INR",
            "email": "",
            "website": "",
            "show_sku_on_pdf": True,
        })
        # Then set to False
        resp = client.put("/api/company/", json={
            "name": "My Company",
            "address": "123 Main St",
            "gst": "",
            "phone_number": "",
            "currency_code": "INR",
            "email": "",
            "website": "",
            "show_sku_on_pdf": False,
        })
        assert resp.status_code == 200
        assert resp.json()["show_sku_on_pdf"] is False

    def test_get_company_returns_show_sku_on_pdf(self, client):
        """GET /company/ returns show_sku_on_pdf field."""
        client.put("/api/company/", json={
            "name": "My Company",
            "address": "123 Main St",
            "gst": "",
            "phone_number": "",
            "currency_code": "INR",
            "email": "",
            "website": "",
            "show_sku_on_pdf": True,
        })
        resp = client.get("/api/company/")
        assert resp.status_code == 200
        assert "show_sku_on_pdf" in resp.json()
        assert resp.json()["show_sku_on_pdf"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Invoice API response includes product_name
# ─────────────────────────────────────────────────────────────────────────────

class TestInvoiceApiProductName:
    """API-level tests that invoices return product_name in line items."""

    def test_create_invoice_returns_product_name(self, client):
        """POST /api/invoices returns product_name in items."""
        with patch("src.services.invoice_processor.generate_next_number", return_value="INV-0001"):
            ledger_id = _create_ledger(client, name="ProductName Buyer", gst="27ABCDE9999F1Z5")
            product_id = _create_product(client, sku="TV001", name="OLED TV")
            _add_inventory(client, product_id=product_id, quantity=10)

            resp = client.post("/api/invoices/", json={
                "ledger_id": ledger_id,
                "voucher_type": "sales",
                "items": [{"product_id": product_id, "quantity": 1}],
            })
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["product_name"] == "OLED TV"

    def test_list_invoices_returns_product_name(self, client):
        """GET /api/invoices returns product_name in each item."""
        with patch("src.services.invoice_processor.generate_next_number", return_value="INV-0002"):
            ledger_id = _create_ledger(client, name="List Buyer", gst="27ABCDE9999F1Z6")
            product_id = _create_product(client, sku="CHAIR", name="Office Chair")
            _add_inventory(client, product_id=product_id, quantity=10)

            client.post("/api/invoices/", json={
                "ledger_id": ledger_id,
                "voucher_type": "sales",
                "items": [{"product_id": product_id, "quantity": 2}],
            })

            resp = client.get("/api/invoices/")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) >= 1
            first_invoice = data["items"][0]
            assert len(first_invoice["items"]) == 1
            assert first_invoice["items"][0]["product_name"] == "Office Chair"

    def test_get_single_invoice_returns_product_name(self, client):
        """GET /api/invoices/{id} returns product_name in items."""
        with patch("src.services.invoice_processor.generate_next_number", return_value="INV-0003"):
            ledger_id = _create_ledger(client, name="Single Buyer", gst="27ABCDE9999F1Z7")
            product_id = _create_product(client, sku="DESK", name="Standing Desk")
            _add_inventory(client, product_id=product_id, quantity=10)

            create_resp = client.post("/api/invoices/", json={
                "ledger_id": ledger_id,
                "voucher_type": "sales",
                "items": [{"product_id": product_id, "quantity": 1}],
            })
            invoice_id = create_resp.json()["id"]

            resp = client.get(f"/api/invoices/{invoice_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["product_name"] == "Standing Desk"

    def test_update_invoice_returns_product_name(self, client):
        """PUT /api/invoices/{id} returns product_name after update."""
        with patch("src.services.invoice_processor.generate_next_number", return_value="INV-0004"):
            ledger_id = _create_ledger(client, name="Update Buyer", gst="27ABCDE9999F1Z8")
            old_product_id = _create_product(client, sku="MOUSE", name="Wireless Mouse")
            new_product_id = _create_product(client, sku="KB001", name="Mechanical Keyboard")
            _add_inventory(client, product_id=old_product_id, quantity=10)
            _add_inventory(client, product_id=new_product_id, quantity=10)

            create_resp = client.post("/api/invoices/", json={
                "ledger_id": ledger_id,
                "voucher_type": "sales",
                "items": [{"product_id": old_product_id, "quantity": 1}],
            })
            invoice_id = create_resp.json()["id"]

            resp = client.put(f"/api/invoices/{invoice_id}", json={
                "ledger_id": ledger_id,
                "voucher_type": "sales",
                "items": [{"product_id": new_product_id, "quantity": 2}],
            })
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["product_name"] == "Mechanical Keyboard"

    def test_product_name_none_when_product_deleted(self, client):
        """product_name is None if the product no longer exists."""
        with patch("src.services.invoice_processor.generate_next_number", return_value="INV-0005"):
            ledger_id = _create_ledger(client, name="Del Buyer", gst="27ABCDE9999F1Z9")
            product_id = _create_product(client, sku="TEMP", name="Temporary Item")
            _add_inventory(client, product_id=product_id, quantity=10)

            create_resp = client.post("/api/invoices/", json={
                "ledger_id": ledger_id,
                "voucher_type": "sales",
                "items": [{"product_id": product_id, "quantity": 1}],
            })
            invoice_id = create_resp.json()["id"]

            # Delete the product
            client.delete(f"/api/products/{product_id}")

            # Fetch invoice — should still return but product_name is None
            resp = client.get(f"/api/invoices/{invoice_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["product_name"] is None
