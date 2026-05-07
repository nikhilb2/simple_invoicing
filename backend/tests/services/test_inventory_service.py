"""
Unit tests for src.services.inventory_service.InventoryManager.

These tests use the same in-memory SQLite database configured by conftest.py so
they exercise real ORM queries without a running Postgres instance.
"""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from src.services.inventory_service import InventoryManager


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_company(db, *, gst="27AABCU9603R1ZX") -> CompanyProfile:
    company = CompanyProfile(
        name="Test Co",
        address="123 Test St",
        gst=gst,
        phone_number="9999999999",
        currency_code="INR",
    )
    db.add(company)
    db.flush()
    return company


def make_product(
    db,
    company_id,
    *,
    price=100,
    gst_rate=18,
    maintain_inventory=True,
    allow_decimal=False,
    sku="P001",
) -> Product:
    product = Product(
        company_id=company_id,
        sku=sku,
        name="Widget",
        price=price,
        gst_rate=gst_rate,
        maintain_inventory=maintain_inventory,
        allow_decimal=allow_decimal,
    )
    db.add(product)
    db.flush()
    return product


def make_inventory(db, product_id, company_id, quantity=50) -> Inventory:
    inv = Inventory(
        product_id=product_id,
        company_id=company_id,
        quantity=quantity,
    )
    db.add(inv)
    db.flush()
    return inv


def make_user(db) -> User:
    user = User(
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashed",
        role=UserRole.admin,
    )
    db.add(user)
    db.flush()
    return user


def make_invoice(db, company_id, user_id=None, voucher_type="sales") -> Invoice:
    if user_id is None:
        user = make_user(db)
        user_id = user.id
    invoice = Invoice(
        total_amount=0,
        company_id=company_id,
        created_by=user_id,
        voucher_type=voucher_type,
    )
    db.add(invoice)
    db.flush()
    return invoice


def add_item(db, invoice_id, product_id, quantity, unit_price=100) -> InvoiceItem:
    item = InvoiceItem(
        invoice_id=invoice_id,
        product_id=product_id,
        quantity=quantity,
        unit_price=unit_price,
        gst_rate=0,
        taxable_amount=unit_price * quantity,
        tax_amount=0,
        line_total=unit_price * quantity,
    )
    db.add(item)
    db.flush()
    return item


# ---------------------------------------------------------------------------
# InventoryManager.effect_for_voucher_type  (static / pure)
# ---------------------------------------------------------------------------

class TestEffectForVoucherType:
    def test_sales_returns_negative(self):
        assert InventoryManager.effect_for_voucher_type(5, "sales") == Decimal("-5")

    def test_purchase_returns_positive(self):
        assert InventoryManager.effect_for_voucher_type(3, "purchase") == Decimal("3")

    def test_fractional_quantity(self):
        assert InventoryManager.effect_for_voucher_type(1.5, "sales") == Decimal("-1.5")


# ---------------------------------------------------------------------------
# InventoryManager.update_quantity
# ---------------------------------------------------------------------------

class TestUpdateQuantity:
    def test_reduces_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        make_inventory(db_session, product.id, company.id, quantity=10)

        mgr = InventoryManager(db_session)
        mgr.update_quantity(product.id, Decimal("-3"), company_id=company.id, context="test")

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("7")

    def test_increases_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        make_inventory(db_session, product.id, company.id, quantity=5)

        mgr = InventoryManager(db_session)
        mgr.update_quantity(product.id, Decimal("10"), company_id=company.id, context="test")

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("15")

    def test_creates_inventory_row_if_missing(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)

        mgr = InventoryManager(db_session)
        mgr.update_quantity(product.id, Decimal("5"), company_id=company.id, context="test")

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert inv is not None
        assert Decimal(str(inv.quantity)) == Decimal("5")

    def test_raises_on_negative_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        make_inventory(db_session, product.id, company.id, quantity=2)

        mgr = InventoryManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.update_quantity(
                product.id, Decimal("-5"), company_id=company.id, context="selling"
            )
        assert exc_info.value.status_code == 400
        assert "Insufficient inventory" in exc_info.value.detail

    def test_allows_exact_zero_remaining(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        make_inventory(db_session, product.id, company.id, quantity=3)

        mgr = InventoryManager(db_session)
        mgr.update_quantity(product.id, Decimal("-3"), company_id=company.id, context="test")

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("0")


# ---------------------------------------------------------------------------
# InventoryManager.check_availability
# ---------------------------------------------------------------------------

class TestCheckAvailability:
    def test_passes_when_stock_sufficient(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        make_inventory(db_session, product.id, company.id, quantity=10)

        mgr = InventoryManager(db_session)
        # Should not raise
        mgr.check_availability(
            product.id, Decimal("10"), company_id=company.id, product_name=product.name
        )

    def test_raises_when_stock_insufficient(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        make_inventory(db_session, product.id, company.id, quantity=2)

        mgr = InventoryManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.check_availability(
                product.id, Decimal("5"), company_id=company.id, product_name=product.name
            )
        assert exc_info.value.status_code == 400
        assert "Insufficient inventory" in exc_info.value.detail

    def test_raises_when_no_inventory_row(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)

        mgr = InventoryManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.check_availability(
                product.id, Decimal("1"), company_id=company.id, product_name=product.name
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# InventoryManager.reverse_invoice_inventory
# ---------------------------------------------------------------------------

class TestReverseInvoiceInventory:
    def test_reverses_sales_invoice(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-REV1")
        make_inventory(db_session, product.id, company.id, quantity=7)

        invoice = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, invoice.id, product.id, quantity=3)

        mgr = InventoryManager(db_session)
        mgr.reverse_invoice_inventory(invoice)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        # Reversal of a sales invoice should add stock back
        assert Decimal(str(inv.quantity)) == Decimal("10")

    def test_reverses_purchase_invoice(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-REV2")
        make_inventory(db_session, product.id, company.id, quantity=10)

        invoice = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, invoice.id, product.id, quantity=4)

        mgr = InventoryManager(db_session)
        mgr.reverse_invoice_inventory(invoice)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        # Reversal of a purchase invoice should reduce stock
        assert Decimal(str(inv.quantity)) == Decimal("6")

    def test_skips_products_without_inventory_tracking(self, db_session):
        company = make_company(db_session)
        product = make_product(
            db_session, company.id, sku="P-REV3", maintain_inventory=False
        )

        invoice = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, invoice.id, product.id, quantity=5)

        mgr = InventoryManager(db_session)
        # Should not raise and should not create an inventory row
        mgr.reverse_invoice_inventory(invoice)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert inv is None

    def test_raises_404_for_missing_product(self, db_session):
        company = make_company(db_session)
        invoice = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, invoice.id, product_id=9999, quantity=1)

        mgr = InventoryManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.reverse_invoice_inventory(invoice)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# InventoryManager.restore_invoice_inventory
# ---------------------------------------------------------------------------

class TestRestoreInvoiceInventory:
    def test_restores_sales_invoice(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-RST1")
        make_inventory(db_session, product.id, company.id, quantity=10)

        invoice = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, invoice.id, product.id, quantity=5)

        mgr = InventoryManager(db_session)
        mgr.restore_invoice_inventory(invoice, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        # Restoring (re-applying) a sales invoice should reduce stock
        assert Decimal(str(inv.quantity)) == Decimal("5")

    def test_restores_purchase_invoice(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-RST2")
        make_inventory(db_session, product.id, company.id, quantity=3)

        invoice = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, invoice.id, product.id, quantity=7)

        mgr = InventoryManager(db_session)
        mgr.restore_invoice_inventory(invoice, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("10")

    def test_skips_untracked_products(self, db_session):
        company = make_company(db_session)
        product = make_product(
            db_session, company.id, sku="P-RST3", maintain_inventory=False
        )
        invoice = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, invoice.id, product.id, quantity=2)

        mgr = InventoryManager(db_session)
        mgr.restore_invoice_inventory(invoice, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert inv is None


# ---------------------------------------------------------------------------
# InventoryManager.apply_invoice_changes
# ---------------------------------------------------------------------------

class TestApplyInvoiceChanges:
    def _payload(self, ledger_id, product_id, quantity, voucher_type="sales"):
        return InvoiceCreate(
            ledger_id=ledger_id,
            voucher_type=voucher_type,
            items=[InvoiceItemCreate(product_id=product_id, quantity=quantity)],
        )

    def test_net_reduction_on_quantity_increase(self, db_session):
        company = make_company(db_session)
        ledger = Buyer(
            company_id=company.id,
            name="L1",
            address="A",
            gst="29AABCU9603R1ZX",
            phone_number="11",
        )
        db_session.add(ledger)
        db_session.flush()

        product = make_product(db_session, company.id, sku="P-CHG1")
        make_inventory(db_session, product.id, company.id, quantity=20)

        invoice = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, invoice.id, product.id, quantity=5)

        payload = self._payload(ledger.id, product.id, 8, voucher_type="sales")
        mgr = InventoryManager(db_session)
        mgr.apply_invoice_changes(invoice, payload, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        # was 20, existing effect was -5, new effect is -8 → delta = -3
        assert Decimal(str(inv.quantity)) == Decimal("17")

    def test_net_increase_on_quantity_decrease(self, db_session):
        company = make_company(db_session)
        ledger = Buyer(
            company_id=company.id,
            name="L2",
            address="A",
            gst="29AABCU9603R1ZX",
            phone_number="11",
        )
        db_session.add(ledger)
        db_session.flush()

        product = make_product(db_session, company.id, sku="P-CHG2")
        make_inventory(db_session, product.id, company.id, quantity=5)

        invoice = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, invoice.id, product.id, quantity=5)

        # New quantity is 3 → delta = (-3) - (-5) = +2
        payload = self._payload(ledger.id, product.id, 3, voucher_type="sales")
        mgr = InventoryManager(db_session)
        mgr.apply_invoice_changes(invoice, payload, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("7")

    def test_skips_zero_delta_products(self, db_session):
        company = make_company(db_session)
        ledger = Buyer(
            company_id=company.id,
            name="L3",
            address="A",
            gst="29AABCU9603R1ZX",
            phone_number="11",
        )
        db_session.add(ledger)
        db_session.flush()

        product = make_product(db_session, company.id, sku="P-CHG3")
        make_inventory(db_session, product.id, company.id, quantity=10)

        invoice = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, invoice.id, product.id, quantity=4)

        # Same quantity → no change
        payload = self._payload(ledger.id, product.id, 4, voucher_type="sales")
        mgr = InventoryManager(db_session)
        mgr.apply_invoice_changes(invoice, payload, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("10")


# ---------------------------------------------------------------------------
# InventoryManager.apply_new_items
# ---------------------------------------------------------------------------

class TestApplyNewItems:
    def test_applies_sales_items_reduces_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-NEW1")
        make_inventory(db_session, product.id, company.id, quantity=10)

        # Simulate the tuple format from InvoiceProcessor.validate_items
        item_schema = InvoiceItemCreate(product_id=product.id, quantity=3)
        validated = [(item_schema, product, Decimal("3"))]

        mgr = InventoryManager(db_session)
        mgr.apply_new_items(
            validated, "sales", company_id=company.id, invoice_id=1
        )

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("7")

    def test_applies_purchase_items_increases_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-NEW2")
        make_inventory(db_session, product.id, company.id, quantity=2)

        item_schema = InvoiceItemCreate(product_id=product.id, quantity=5)
        validated = [(item_schema, product, Decimal("5"))]

        mgr = InventoryManager(db_session)
        mgr.apply_new_items(
            validated, "purchase", company_id=company.id, invoice_id=1
        )

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("7")

    def test_skips_untracked_products(self, db_session):
        company = make_company(db_session)
        product = make_product(
            db_session, company.id, sku="P-NEW3", maintain_inventory=False
        )

        item_schema = InvoiceItemCreate(product_id=product.id, quantity=5)
        validated = [(item_schema, product, Decimal("5"))]

        mgr = InventoryManager(db_session)
        mgr.apply_new_items(
            validated, "sales", company_id=company.id, invoice_id=1
        )

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert inv is None
