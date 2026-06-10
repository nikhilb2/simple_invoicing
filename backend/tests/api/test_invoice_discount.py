"""Tests for discount feature — item-level and invoice-level discounts."""

from datetime import datetime
from decimal import Decimal

import pytest

from src.services.invoice_processor import InvoiceProcessor
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate


@pytest.fixture
def processor(db_session):
    return InvoiceProcessor(db_session)


def _seed(db_session):
    user = User(email="admin@test.com", full_name="Admin", hashed_password="x", role=UserRole.admin)
    ledger = Buyer(name="Test Buyer", address="Addr", gst="07AABB1234C1Z5", phone_number="9999999999")
    company = CompanyProfile(name="Test Co", address="HQ", gst="07AAMPB1274B1Z8", phone_number="8888888888", currency_code="INR")
    db_session.add_all([user, ledger, company])
    db_session.flush()
    return user, ledger


def _product(db_session, sku="SKU01", price=100.0, gst_rate=18.0):
    p = Product(sku=sku, name=f"Product {sku}", price=price, gst_rate=gst_rate)
    db_session.add(p)
    db_session.flush()
    inv = Inventory(product_id=p.id, quantity=100)
    db_session.add(inv)
    db_session.flush()
    return p


def _inv(db_session):
    inv = Invoice(total_amount=0, created_by=1, invoice_date=datetime.utcnow())
    db_session.add(inv)
    db_session.flush()
    return inv


class TestItemDiscountPercentage:
    def test_percentage_discount_reduces_line_total(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id,
                quantity=1,
                unit_price=100.00,
                discount_type="percentage",
                discount_value=10.0,
            )],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        # 10% off 100 = 90 taxable; tax = 90 * 18% = 16.20; total = 106.20
        assert len(invoice.items) == 1
        assert float(invoice.items[0].taxable_amount) == pytest.approx(90.00)
        assert float(invoice.items[0].line_total) == pytest.approx(106.20)
        assert float(invoice.total_amount) == pytest.approx(106.20)

    def test_percentage_discount_fully_wiped(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id,
                quantity=1,
                unit_price=100.00,
                discount_type="percentage",
                discount_value=100.0,
            )],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        assert float(invoice.items[0].taxable_amount) == pytest.approx(0.00)
        assert float(invoice.items[0].line_total) == pytest.approx(0.00)
        assert float(invoice.total_amount) == pytest.approx(0.00)


class TestItemDiscountNet:
    def test_net_discount_reduces_line_total(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id,
                quantity=1,
                unit_price=100.00,
                discount_type="net",
                discount_value=25.00,
            )],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        # 100 - 25 = 75 taxable; tax = 75 * 18% = 13.50; total = 88.50
        assert float(invoice.items[0].taxable_amount) == pytest.approx(75.00)
        assert float(invoice.items[0].line_total) == pytest.approx(88.50)


class TestInvoiceLevelDiscount:
    def test_percentage_invoice_discount(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            discount_type="percentage",
            discount_value=10.0,
            items=[InvoiceItemCreate(
                product_id=product.id,
                quantity=2,
                unit_price=100.00,
            )],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        # 200 taxable; tax = 36; gross = 236
        # 10% off 236 = 23.60; total = 212.40
        assert float(invoice.taxable_amount) == pytest.approx(200.00)
        assert float(invoice.total_tax_amount) == pytest.approx(36.00)
        assert float(invoice.total_amount) == pytest.approx(212.40)

    def test_net_invoice_discount(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            discount_type="net",
            discount_value=50.00,
            items=[InvoiceItemCreate(
                product_id=product.id,
                quantity=1,
                unit_price=500.00,
            )],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        # 500 taxable + 90 tax = 590; minus 50 flat = 540
        assert float(invoice.total_amount) == pytest.approx(540.00)


class TestCombinedDiscounts:
    def test_item_and_invoice_discounts_combined(self, db_session, processor):
        user, ledger = _seed(db_session)
        p1 = _product(db_session, "SKU-A", 200.00)
        p2 = _product(db_session, "SKU-B", 300.00)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            discount_type="net",
            discount_value=20.00,
            items=[
                InvoiceItemCreate(
                    product_id=p1.id, quantity=1, unit_price=200.00,
                    discount_type="percentage", discount_value=10.0,
                ),
                InvoiceItemCreate(
                    product_id=p2.id, quantity=1, unit_price=300.00,
                    discount_type="net", discount_value=50.00,
                ),
            ],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        # Item 1: 200 - 10% = 180; tax = 180*18% = 32.40; line = 212.40
        # Item 2: 300 - 50 = 250; tax = 250*18% = 45.00; line = 295.00
        # Subtotal: 212.40 + 295.00 = 507.40
        # Invoice discount: 20.00 flat
        # Total: 507.40 - 20.00 = 487.40
        assert float(invoice.items[0].taxable_amount) == pytest.approx(180.00)
        assert float(invoice.items[0].line_total) == pytest.approx(212.40)
        assert float(invoice.items[1].taxable_amount) == pytest.approx(250.00)
        assert float(invoice.items[1].line_total) == pytest.approx(295.00)
        assert float(invoice.total_amount) == pytest.approx(487.40)


class TestDiscountWithRoundOff:
    def test_discount_with_round_off(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session, price=123.45)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            apply_round_off=True,
            discount_type="percentage",
            discount_value=5.0,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=123.45)],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        # Taxable: 123.45; tax = 22.221 → 22.22; gross = 145.67
        # 5% off 145.67 = 7.2835 → 7.28; after disc = 138.39
        # Round off to nearest 1 → 138.00; round_off = -0.39
        assert float(invoice.total_amount) == pytest.approx(138.00)
        assert float(invoice.round_off_amount) == pytest.approx(-0.39)


class TestDiscountStored:
    def test_discount_fields_persisted_on_items(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id,
                quantity=1,
                unit_price=100.00,
                discount_type="net",
                discount_value=15.0,
            )],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        assert invoice.items[0].discount_type == "net"
        assert float(invoice.items[0].discount_value) == pytest.approx(15.0)

    def test_discount_fields_persisted_on_invoice(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            discount_type="percentage",
            discount_value=8.0,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100.00)],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        assert invoice.discount_type == "percentage"
        assert float(invoice.discount_value) == pytest.approx(8.0)


class TestDiscountEdgeCases:
    def test_no_discount_does_nothing(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100.00)],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        assert float(invoice.total_amount) == pytest.approx(118.00)

    def test_net_discount_cannot_exceed_value(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id, quantity=1, unit_price=50.00,
                discount_type="net", discount_value=100.00,
            )],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        # Net discount capped at taxable (50); tax = 0; total = 0
        assert float(invoice.items[0].taxable_amount) == pytest.approx(0.00)
        assert float(invoice.items[0].line_total) == pytest.approx(0.00)

    def test_zero_discount_value_is_ignored(self, db_session, processor):
        user, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _inv(db_session)

        payload = InvoiceCreate(
            ledger_id=ledger.id,
            voucher_type="sales",
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id, quantity=1, unit_price=100.00,
                discount_type="percentage", discount_value=0,
            )],
        )
        processor.apply_payload(invoice, payload, created_by=user.id, regenerate_number=False)
        db_session.flush()
        db_session.refresh(invoice)

        assert float(invoice.total_amount) == pytest.approx(118.00)
