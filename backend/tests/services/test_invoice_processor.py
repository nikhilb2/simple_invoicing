"""
Unit tests for src.services.invoice_processor.

These tests use an in-memory SQLite database (the same one configured in
conftest.py via autouse fixture) so they exercise real ORM queries without
needing a running Postgres instance.
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
from src.services.invoice_processor import (
    InvoiceProcessor,
    change_inventory_quantity,
    inventory_effect_for_voucher_type,
)


# ---------------------------------------------------------------------------
# Helpers
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


def make_ledger(db, company_id, *, gst="29AABCU9603R1ZX") -> Buyer:
    ledger = Buyer(
        company_id=company_id,
        name="Test Ledger",
        address="456 Ledger Ave",
        gst=gst,
        phone_number="8888888888",
    )
    db.add(ledger)
    db.flush()
    return ledger


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


def make_invoice(db, company_id, user_id=None) -> Invoice:
    if user_id is None:
        user = make_user(db)
        user_id = user.id
    invoice = Invoice(total_amount=0, company_id=company_id, created_by=user_id)
    db.add(invoice)
    db.flush()
    return invoice


# ---------------------------------------------------------------------------
# inventory_effect_for_voucher_type (pure function)
# ---------------------------------------------------------------------------

class TestInventoryEffectForVoucherType:
    def test_sales_returns_negative(self):
        assert inventory_effect_for_voucher_type(5, "sales") == Decimal("-5")

    def test_purchase_returns_positive(self):
        assert inventory_effect_for_voucher_type(3, "purchase") == Decimal("3")

    def test_fractional_quantity(self):
        assert inventory_effect_for_voucher_type(1.5, "sales") == Decimal("-1.5")


# ---------------------------------------------------------------------------
# change_inventory_quantity
# ---------------------------------------------------------------------------

class TestChangeInventoryQuantity:
    def test_reduces_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        make_inventory(db_session, product.id, company.id, quantity=10)

        change_inventory_quantity(
            db_session, product.id, Decimal("-3"), company_id=company.id, context="test"
        )

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("7")

    def test_creates_inventory_row_if_missing(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)

        change_inventory_quantity(
            db_session, product.id, Decimal("5"), company_id=company.id, context="test"
        )

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert inv is not None
        assert Decimal(str(inv.quantity)) == Decimal("5")

    def test_raises_on_negative_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        make_inventory(db_session, product.id, company.id, quantity=2)

        with pytest.raises(HTTPException) as exc_info:
            change_inventory_quantity(
                db_session,
                product.id,
                Decimal("-5"),
                company_id=company.id,
                context="selling",
            )
        assert exc_info.value.status_code == 400
        assert "Insufficient inventory" in exc_info.value.detail


# ---------------------------------------------------------------------------
# InvoiceProcessor.require_ledger
# ---------------------------------------------------------------------------

class TestRequireLedger:
    def test_returns_ledger_when_found(self, db_session):
        company = make_company(db_session)
        ledger = make_ledger(db_session, company.id)
        processor = InvoiceProcessor(db_session)
        result = processor.require_ledger(ledger.id, company.id)
        assert result.id == ledger.id

    def test_raises_404_when_not_found(self, db_session):
        company = make_company(db_session)
        processor = InvoiceProcessor(db_session)
        with pytest.raises(HTTPException) as exc_info:
            processor.require_ledger(9999, company.id)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# InvoiceProcessor.validate_items
# ---------------------------------------------------------------------------

class TestValidateItems:
    def test_raises_on_empty_items(self, db_session):
        company = make_company(db_session)
        processor = InvoiceProcessor(db_session)
        with pytest.raises(HTTPException) as exc_info:
            processor.validate_items([], company.id, "sales")
        assert exc_info.value.status_code == 400
        assert "at least one line item" in exc_info.value.detail

    def test_raises_on_zero_quantity(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id)
        items = [InvoiceItemCreate(product_id=product.id, quantity=0)]
        processor = InvoiceProcessor(db_session)
        with pytest.raises(HTTPException) as exc_info:
            processor.validate_items(items, company.id, "sales")
        assert exc_info.value.status_code == 400
        assert "greater than zero" in exc_info.value.detail

    def test_raises_on_missing_product(self, db_session):
        company = make_company(db_session)
        items = [InvoiceItemCreate(product_id=99999, quantity=1)]
        processor = InvoiceProcessor(db_session)
        with pytest.raises(HTTPException) as exc_info:
            processor.validate_items(items, company.id, "sales")
        assert exc_info.value.status_code == 404

    def test_raises_on_decimal_quantity_for_whole_number_product(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, allow_decimal=False)
        items = [InvoiceItemCreate(product_id=product.id, quantity=1.5)]
        processor = InvoiceProcessor(db_session)
        with pytest.raises(HTTPException) as exc_info:
            processor.validate_items(items, company.id, "sales", apply_inventory_changes=False)
        assert exc_info.value.status_code == 400
        assert "whole number" in exc_info.value.detail

    def test_raises_insufficient_inventory_for_sales(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, maintain_inventory=True)
        make_inventory(db_session, product.id, company.id, quantity=2)
        items = [InvoiceItemCreate(product_id=product.id, quantity=5)]
        processor = InvoiceProcessor(db_session)
        with pytest.raises(HTTPException) as exc_info:
            processor.validate_items(items, company.id, "sales", apply_inventory_changes=True)
        assert exc_info.value.status_code == 400
        assert "Insufficient inventory" in exc_info.value.detail

    def test_returns_validated_tuples(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, maintain_inventory=False)
        items = [InvoiceItemCreate(product_id=product.id, quantity=3)]
        processor = InvoiceProcessor(db_session)
        result = processor.validate_items(items, company.id, "sales", apply_inventory_changes=False)
        assert len(result) == 1
        item_schema, prod, qty = result[0]
        assert prod.id == product.id
        assert qty == Decimal("3")


# ---------------------------------------------------------------------------
# InvoiceProcessor.calculate_totals
# ---------------------------------------------------------------------------

class TestCalculateTotals:
    def _make_validated(self, product, quantity, unit_price=None):
        item_schema = InvoiceItemCreate(
            product_id=product.id,
            quantity=float(quantity),
            unit_price=float(unit_price) if unit_price else None,
        )
        return [(item_schema, product, Decimal(str(quantity)))]

    def test_tax_exclusive_calculation(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, price=100, gst_rate=18)
        validated = self._make_validated(product, 2)
        processor = InvoiceProcessor(db_session)
        results = processor.calculate_totals(validated, tax_inclusive=False)
        r = results[0]
        assert r["taxable_amount"] == Decimal("200.00")
        assert r["tax_amount"] == Decimal("36.00")
        assert r["line_total"] == Decimal("236.00")

    def test_tax_inclusive_back_calculation(self, db_session):
        company = make_company(db_session)
        # Price of 118 includes 18% GST → taxable = 100, tax = 18
        product = make_product(db_session, company.id, price=118, gst_rate=18)
        validated = self._make_validated(product, 1)
        processor = InvoiceProcessor(db_session)
        results = processor.calculate_totals(validated, tax_inclusive=True)
        r = results[0]
        assert r["line_total"] == Decimal("118.00")
        assert r["taxable_amount"] == Decimal("100.00")
        assert r["tax_amount"] == Decimal("18.00")

    def test_custom_unit_price_overrides_product_price(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, price=100, gst_rate=0)
        validated = self._make_validated(product, 1, unit_price=200)
        processor = InvoiceProcessor(db_session)
        results = processor.calculate_totals(validated, tax_inclusive=False)
        assert results[0]["taxable_amount"] == Decimal("200.00")

    def test_zero_gst_rate(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, price=100, gst_rate=0)
        validated = self._make_validated(product, 1)
        processor = InvoiceProcessor(db_session)
        results = processor.calculate_totals(validated, tax_inclusive=False)
        r = results[0]
        assert r["tax_amount"] == Decimal("0.00")
        assert r["taxable_amount"] == r["line_total"]


# ---------------------------------------------------------------------------
# InvoiceProcessor.apply_payload (integration-style, uses DB)
# ---------------------------------------------------------------------------

class TestApplyPayload:
    def _make_payload(self, ledger_id, product_id, quantity=1, voucher_type="sales"):
        return InvoiceCreate(
            ledger_id=ledger_id,
            voucher_type=voucher_type,
            items=[InvoiceItemCreate(product_id=product_id, quantity=quantity)],
        )

    def test_creates_invoice_items_and_total(self, db_session):
        company = make_company(db_session)
        ledger = make_ledger(db_session, company.id)
        product = make_product(db_session, company.id, price=100, gst_rate=18, maintain_inventory=False)
        invoice = make_invoice(db_session, company.id)

        payload = self._make_payload(ledger.id, product.id, quantity=2)
        processor = InvoiceProcessor(db_session)
        processor.apply_payload(
            invoice, payload, company, apply_inventory_changes=False
        )

        assert invoice.ledger_id == ledger.id
        assert invoice.total_amount == pytest.approx(236.0)
        assert invoice.taxable_amount == pytest.approx(200.0)
        items = db_session.query(InvoiceItem).filter_by(invoice_id=invoice.id).all()
        assert len(items) == 1
        assert items[0].quantity == 2.0

    def test_snapshots_company_fields(self, db_session):
        company = make_company(db_session)
        ledger = make_ledger(db_session, company.id)
        product = make_product(db_session, company.id, maintain_inventory=False)
        invoice = make_invoice(db_session, company.id)

        payload = self._make_payload(ledger.id, product.id)
        processor = InvoiceProcessor(db_session)
        processor.apply_payload(invoice, payload, company, apply_inventory_changes=False)

        assert invoice.company_name == company.name
        assert invoice.ledger_name == ledger.name
        assert invoice.company_gst == company.gst

    def test_raises_on_missing_ledger(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, maintain_inventory=False)
        invoice = make_invoice(db_session, company.id)

        payload = self._make_payload(99999, product.id)
        processor = InvoiceProcessor(db_session)
        with pytest.raises(HTTPException) as exc_info:
            processor.apply_payload(invoice, payload, company, apply_inventory_changes=False)
        assert exc_info.value.status_code == 404

    def test_apply_round_off(self, db_session):
        company = make_company(db_session)
        ledger = make_ledger(db_session, company.id)
        # Price that yields a fractional total: 100 * 5% GST = 105.00, no fractions
        # Use 101 * 5% = 106.05 → round off to 106
        product = make_product(db_session, company.id, price=101, gst_rate=5, maintain_inventory=False)
        invoice = make_invoice(db_session, company.id)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            apply_round_off=True,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1)],
        )
        processor = InvoiceProcessor(db_session)
        processor.apply_payload(invoice, payload, company, apply_inventory_changes=False)

        assert invoice.total_amount == pytest.approx(106.0)
        # round_off_amount should be small (−0.05 in this case)
        assert abs(invoice.round_off_amount) < 1.0


# ---------------------------------------------------------------------------
# InvoiceProcessor.apply_inventory_delta_for_update
# ---------------------------------------------------------------------------

class TestApplyInventoryDeltaForUpdate:
    def test_net_delta_for_quantity_increase(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, maintain_inventory=True)
        make_inventory(db_session, product.id, company.id, quantity=10)

        # Simulate an existing invoice with 2 units sold
        invoice = make_invoice(db_session, company.id)
        invoice.voucher_type = "sales"
        item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            quantity=2.0,
            unit_price=100,
            gst_rate=0,
            taxable_amount=200,
            tax_amount=0,
            line_total=200,
        )
        db_session.add(item)
        db_session.flush()
        invoice.items  # load relationship

        # New payload wants 5 units → delta should reduce stock by 3 more
        payload = InvoiceCreate(
            ledger_id=1,
            voucher_type="sales",
            items=[InvoiceItemCreate(product_id=product.id, quantity=5)],
        )
        processor = InvoiceProcessor(db_session)
        processor.apply_inventory_delta_for_update(invoice, payload, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        # Started at 10, sold 2 originally (outside), now delta = -5 - (-2) = -3 more
        assert Decimal(str(inv.quantity)) == Decimal("7")

    def test_no_change_when_quantity_same(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, maintain_inventory=True)
        make_inventory(db_session, product.id, company.id, quantity=10)

        invoice = make_invoice(db_session, company.id)
        invoice.voucher_type = "sales"
        item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            quantity=3.0,
            unit_price=100,
            gst_rate=0,
            taxable_amount=300,
            tax_amount=0,
            line_total=300,
        )
        db_session.add(item)
        db_session.flush()

        payload = InvoiceCreate(
            ledger_id=1,
            voucher_type="sales",
            items=[InvoiceItemCreate(product_id=product.id, quantity=3)],
        )
        processor = InvoiceProcessor(db_session)
        processor.apply_inventory_delta_for_update(invoice, payload, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("10")  # unchanged


# ---------------------------------------------------------------------------
# InvoiceProcessor.reverse_inventory / restore_inventory
# ---------------------------------------------------------------------------

class TestReverseRestoreInventory:
    def test_reverse_increases_stock_for_sales_invoice(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, maintain_inventory=True)
        make_inventory(db_session, product.id, company.id, quantity=5)

        invoice = make_invoice(db_session, company.id)
        invoice.voucher_type = "sales"
        item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            quantity=3.0,
            unit_price=100,
            gst_rate=0,
            taxable_amount=300,
            tax_amount=0,
            line_total=300,
        )
        db_session.add(item)
        db_session.flush()

        processor = InvoiceProcessor(db_session)
        processor.reverse_inventory(invoice)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("8")  # 5 + 3 (reversed)

    def test_restore_reduces_stock_for_sales_invoice(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, maintain_inventory=True)
        make_inventory(db_session, product.id, company.id, quantity=8)

        invoice = make_invoice(db_session, company.id)
        invoice.voucher_type = "sales"
        item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            quantity=3.0,
            unit_price=100,
            gst_rate=0,
            taxable_amount=300,
            tax_amount=0,
            line_total=300,
        )
        db_session.add(item)
        db_session.flush()

        processor = InvoiceProcessor(db_session)
        processor.restore_inventory(invoice, company_id=company.id)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert Decimal(str(inv.quantity)) == Decimal("5")  # 8 - 3 (re-applied)

    def test_skips_products_without_inventory_tracking(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, maintain_inventory=False)

        invoice = make_invoice(db_session, company.id)
        invoice.voucher_type = "sales"
        item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            quantity=10.0,
            unit_price=100,
            gst_rate=0,
            taxable_amount=1000,
            tax_amount=0,
            line_total=1000,
        )
        db_session.add(item)
        db_session.flush()

        processor = InvoiceProcessor(db_session)
        # Neither should raise nor create inventory rows
        processor.reverse_inventory(invoice)

        inv = db_session.query(Inventory).filter_by(product_id=product.id).first()
        assert inv is None
