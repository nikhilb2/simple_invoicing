"""Tests for discount amount derivation.

Invoices store discount_type/discount_value but never the discount *amount*, so
src.services.invoice_discounts recovers it by inverting the write path. These
tests guard that inversion: the known-answer cases pin the arithmetic, and
TestRoundTripAgainstProcessor catches the real risk — the write path changing
shape and the derivation silently drifting away from it.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from src.services.invoice_discounts import build_invoice_discount_totals
from src.services.invoice_processor import InvoiceProcessor


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
    db_session.add(Inventory(product_id=p.id, quantity=100))
    db_session.flush()
    return p


def _inv(db_session):
    invoice = Invoice(total_amount=0, created_by=1, invoice_date=datetime.utcnow())
    db_session.add(invoice)
    db_session.flush()
    return invoice


def _apply(db_session, processor, ledger, **payload_kwargs):
    """Build an invoice through the real processor and return it."""
    invoice = _inv(db_session)
    payload = InvoiceCreate(ledger_id=ledger.id, voucher_type="sales", **payload_kwargs)
    processor.apply_payload(invoice, payload, created_by=1, regenerate_number=False)
    db_session.flush()
    db_session.refresh(invoice)
    return invoice


def _summary(db_session, invoice):
    summaries = build_invoice_discount_totals(db_session, [invoice])
    assert invoice.id in summaries
    return summaries[invoice.id]


class TestItemLevelDiscounts:
    def test_percentage_discount(self, db_session, processor):
        _, ledger = _seed(db_session)
        product = _product(db_session)
        # 10% off 100 taxable = 10.00 discount.
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id, quantity=1, unit_price=100.00,
                discount_type="percentage", discount_value=10.0,
            )],
        )

        summary = _summary(db_session, invoice)
        assert summary.item_discount_total == Decimal("10.00")
        assert summary.invoice_discount_amount == Decimal("0.00")
        assert summary.total_discount == Decimal("10.00")

    def test_net_discount(self, db_session, processor):
        _, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id, quantity=1, unit_price=100.00,
                discount_type="net", discount_value=25.00,
            )],
        )

        assert _summary(db_session, invoice).item_discount_total == Decimal("25.00")

    def test_net_discount_clamped_to_line_value(self, db_session, processor):
        """A 100 discount on a 50 line is clamped to 50 by the write path.

        This is the case a discount_value-based derivation gets wrong — it would
        report 100 given away on a 50 line.
        """
        _, ledger = _seed(db_session)
        product = _product(db_session, price=50.0)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id, quantity=1, unit_price=50.00,
                discount_type="net", discount_value=100.00,
            )],
        )

        assert _summary(db_session, invoice).item_discount_total == Decimal("50.00")

    def test_tax_inclusive_discount(self, db_session, processor):
        """Tax-inclusive lines discount the ex-tax taxable, not the gross."""
        _, ledger = _seed(db_session)
        product = _product(db_session)
        # 118 incl. 18% → 100.00 taxable; 10% off = 10.00.
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=True,
            items=[InvoiceItemCreate(
                product_id=product.id, quantity=1, unit_price=118.00,
                discount_type="percentage", discount_value=10.0,
            )],
        )

        assert _summary(db_session, invoice).item_discount_total == Decimal("10.00")

    def test_multiple_lines_sum(self, db_session, processor):
        _, ledger = _seed(db_session)
        p1 = _product(db_session, "SKU-A", 200.00)
        p2 = _product(db_session, "SKU-B", 300.00)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            items=[
                # 10% off 200 = 20.00
                InvoiceItemCreate(product_id=p1.id, quantity=1, unit_price=200.00,
                                  discount_type="percentage", discount_value=10.0),
                # flat 50 off 300 = 50.00
                InvoiceItemCreate(product_id=p2.id, quantity=1, unit_price=300.00,
                                  discount_type="net", discount_value=50.00),
            ],
        )

        assert _summary(db_session, invoice).item_discount_total == Decimal("70.00")


class TestInvoiceLevelDiscounts:
    def test_percentage_discount(self, db_session, processor):
        _, ledger = _seed(db_session)
        product = _product(db_session)
        # 200 taxable + 36 tax = 236 gross; 10% = 23.60.
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            discount_type="percentage", discount_value=10.0,
            items=[InvoiceItemCreate(product_id=product.id, quantity=2, unit_price=100.00)],
        )

        summary = _summary(db_session, invoice)
        assert summary.invoice_discount_amount == Decimal("23.60")
        assert summary.item_discount_total == Decimal("0.00")
        assert summary.total_discount == Decimal("23.60")

    def test_net_discount(self, db_session, processor):
        _, ledger = _seed(db_session)
        product = _product(db_session, price=500.0)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            discount_type="net", discount_value=50.00,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=500.00)],
        )

        assert _summary(db_session, invoice).invoice_discount_amount == Decimal("50.00")

    def test_discount_with_round_off(self, db_session, processor):
        """Round-off must not be mistaken for discount.

        Taxable 123.45 + tax 22.22 = 145.67 gross; 5% = 7.28 discount → 138.39;
        rounded to 138.00 with round_off -0.39. The derivation has to add the
        round_off back to recover 7.28 rather than reporting 7.67.
        """
        _, ledger = _seed(db_session)
        product = _product(db_session, price=123.45)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            apply_round_off=True,
            discount_type="percentage", discount_value=5.0,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=123.45)],
        )

        assert float(invoice.round_off_amount) == pytest.approx(-0.39)
        assert _summary(db_session, invoice).invoice_discount_amount == Decimal("7.28")

    def test_round_off_without_discount_is_not_a_discount(self, db_session, processor):
        """Round-off alone must derive to exactly zero discount."""
        _, ledger = _seed(db_session)
        product = _product(db_session, price=123.45)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            apply_round_off=True,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=123.45)],
        )

        assert _summary(db_session, invoice).total_discount == Decimal("0.00")


class TestCombined:
    def test_item_and_invoice_discounts(self, db_session, processor):
        _, ledger = _seed(db_session)
        p1 = _product(db_session, "SKU-A", 200.00)
        p2 = _product(db_session, "SKU-B", 300.00)
        # Item discounts: 10% off 200 = 20.00, flat 50 off 300 = 50.00 → 70.00
        # Invoice discount: flat 20.00
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            discount_type="net", discount_value=20.00,
            items=[
                InvoiceItemCreate(product_id=p1.id, quantity=1, unit_price=200.00,
                                  discount_type="percentage", discount_value=10.0),
                InvoiceItemCreate(product_id=p2.id, quantity=1, unit_price=300.00,
                                  discount_type="net", discount_value=50.00),
            ],
        )

        summary = _summary(db_session, invoice)
        assert summary.item_discount_total == Decimal("70.00")
        assert summary.invoice_discount_amount == Decimal("20.00")
        assert summary.total_discount == Decimal("90.00")


class TestEdgeCases:
    def test_no_discount_is_exactly_zero(self, db_session, processor):
        _, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100.00)],
        )

        summary = _summary(db_session, invoice)
        assert summary.total_discount == Decimal("0.00")

    def test_zero_discount_value_is_zero(self, db_session, processor):
        """discount_type set with a zero value is ignored by the write path."""
        _, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id, quantity=1, unit_price=100.00,
                discount_type="percentage", discount_value=0,
            )],
        )

        assert _summary(db_session, invoice).total_discount == Decimal("0.00")

    def test_fully_wiped_line(self, db_session, processor):
        _, ledger = _seed(db_session)
        product = _product(db_session)
        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=False,
            items=[InvoiceItemCreate(
                product_id=product.id, quantity=1, unit_price=100.00,
                discount_type="percentage", discount_value=100.0,
            )],
        )

        assert _summary(db_session, invoice).item_discount_total == Decimal("100.00")

    def test_empty_invoice_list(self, db_session):
        assert build_invoice_discount_totals(db_session, []) == {}

    def test_batches_multiple_invoices(self, db_session, processor):
        _, ledger = _seed(db_session)
        product = _product(db_session)
        first = _apply(
            db_session, processor, ledger, tax_inclusive=False,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100.00,
                                     discount_type="net", discount_value=10.00)],
        )
        second = _apply(
            db_session, processor, ledger, tax_inclusive=False,
            items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100.00,
                                     discount_type="net", discount_value=30.00)],
        )

        summaries = build_invoice_discount_totals(db_session, [first, second])
        assert summaries[first.id].total_discount == Decimal("10.00")
        assert summaries[second.id].total_discount == Decimal("30.00")


class TestRoundTripAgainstProcessor:
    """The derivation must agree with what the processor itself computed.

    These assert against the processor's own output rather than hand-computed
    constants, so they fail if the write path changes shape — which is the
    failure mode the derivation is exposed to.
    """

    @pytest.mark.parametrize("tax_inclusive", [False, True])
    @pytest.mark.parametrize("apply_round_off", [False, True])
    @pytest.mark.parametrize(
        "item_discount,invoice_discount",
        [
            (None, None),
            (("percentage", 10.0), None),
            (("net", 25.0), None),
            (None, ("percentage", 10.0)),
            (None, ("net", 50.0)),
            (("percentage", 7.5), ("net", 20.0)),
            (("net", 33.33), ("percentage", 12.5)),
        ],
    )
    def test_derived_matches_processor(
        self, db_session, processor, tax_inclusive, apply_round_off, item_discount, invoice_discount
    ):
        _, ledger = _seed(db_session)
        product = _product(db_session, price=137.77)

        item_kwargs = {}
        if item_discount:
            item_kwargs = {"discount_type": item_discount[0], "discount_value": item_discount[1]}
        invoice_kwargs = {}
        if invoice_discount:
            invoice_kwargs = {"discount_type": invoice_discount[0], "discount_value": invoice_discount[1]}

        # apply_inventory_changes=False — this call only computes the expected
        # discount; the real stock movement happens in _apply below.
        validated = processor.validate_items(
            [InvoiceItemCreate(product_id=product.id, quantity=3, unit_price=137.77, **item_kwargs)],
            company_id=None,
            voucher_type="sales",
            apply_inventory_changes=False,
        )
        expected_item_discount = sum(
            (row["discount_amount"] for row in processor.calculate_totals(validated, tax_inclusive)),
            Decimal("0"),
        )

        invoice = _apply(
            db_session, processor, ledger,
            tax_inclusive=tax_inclusive,
            apply_round_off=apply_round_off,
            items=[InvoiceItemCreate(product_id=product.id, quantity=3, unit_price=137.77, **item_kwargs)],
            **invoice_kwargs,
        )

        summary = _summary(db_session, invoice)
        assert summary.item_discount_total == expected_item_discount

        # The invoice-level discount is recoverable from the processor's own
        # published totals the same way a reader would: gross minus what was
        # actually charged, net of round-off.
        gross = Decimal(str(invoice.taxable_amount)) + Decimal(str(invoice.total_tax_amount))
        charged = Decimal(str(invoice.total_amount)) - Decimal(str(invoice.round_off_amount))
        assert summary.invoice_discount_amount == max(gross - charged, Decimal("0.00"))
