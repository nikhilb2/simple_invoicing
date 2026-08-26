"""
Unit tests for src.services.serial_service.SerialManager.

These tests use the same in-memory SQLite database configured by conftest.py so
they exercise real ORM queries — including the partial unique index that lets a
voided serial number be registered again — without a running Postgres instance.
"""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from src.models.company import CompanyProfile
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.product_serial import (
    STATUS_IN_STOCK,
    STATUS_SOLD,
    STATUS_VOID,
    ProductSerial,
)
from src.models.user import User, UserRole
from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from src.services.serial_service import SerialManager


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_company(db, *, name="Test Co", gst="27AABCU9603R1ZX") -> CompanyProfile:
    company = CompanyProfile(
        name=name,
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
    name="iPhone 15 128GB",
    price=100,
    gst_rate=18,
    maintain_inventory=True,
    allow_decimal=False,
    track_serials=True,
    sku="P001",
) -> Product:
    product = Product(
        company_id=company_id,
        sku=sku,
        name=name,
        price=price,
        gst_rate=gst_rate,
        maintain_inventory=maintain_inventory,
        allow_decimal=allow_decimal,
        track_serials=track_serials,
    )
    db.add(product)
    db.flush()
    return product


def make_user(db, *, email="test@example.com") -> User:
    """Fetch or create the admin user every invoice below is created by."""
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(
        email=email,
        full_name="Test User",
        hashed_password="hashed",
        role=UserRole.admin,
    )
    db.add(user)
    db.flush()
    return user


def make_invoice(
    db, company_id, user_id=None, voucher_type="sales", invoice_number=None
) -> Invoice:
    if user_id is None:
        user = make_user(db)
        user_id = user.id
    invoice = Invoice(
        total_amount=0,
        company_id=company_id,
        created_by=user_id,
        voucher_type=voucher_type,
        invoice_number=invoice_number,
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


def line(product_id, quantity, serials=None) -> InvoiceItemCreate:
    """A line-item schema as the invoice router would receive it."""
    return InvoiceItemCreate(
        product_id=product_id, quantity=quantity, serial_numbers=serials
    )


def validated(*triples) -> list[tuple]:
    """The ``(item_schema, product, quantity)`` shape validate_items returns."""
    return [
        (line(product.id, quantity, serials), product, Decimal(str(quantity)))
        for product, quantity, serials in triples
    ]


def serials_of(db, product_id=None, *, status=None) -> list[ProductSerial]:
    query = db.query(ProductSerial)
    if product_id is not None:
        query = query.filter(ProductSerial.product_id == product_id)
    if status is not None:
        query = query.filter(ProductSerial.status == status)
    return query.order_by(ProductSerial.id.asc()).all()


def numbers_of(db, product_id=None, *, status=None) -> list[str]:
    return [row.serial_number for row in serials_of(db, product_id, status=status)]


# ---------------------------------------------------------------------------
# SerialManager.normalize  (static / pure)
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_strips_surrounding_whitespace(self):
        assert SerialManager.normalize("  356938035643809  ") == "356938035643809"

    def test_collapses_inner_whitespace(self):
        assert SerialManager.normalize("3569 3803  5643809") == "3569 3803 5643809"

    def test_none_becomes_empty_string(self):
        assert SerialManager.normalize(None) == ""

    def test_preserves_case_as_entered(self):
        assert SerialManager.normalize(" abc-123 ") == "abc-123"


# ---------------------------------------------------------------------------
# SerialManager.validate_for_items
# ---------------------------------------------------------------------------

class TestValidateForItems:
    def test_rejects_serials_on_untracked_product(self, db_session):
        company = make_company(db_session)
        product = make_product(
            db_session, company.id, name="USB Cable", sku="P-UNTRACKED",
            track_serials=False,
        )

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 1, ["356938035643809"])),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "USB Cable is not serial-tracked" in exc_info.value.detail

    def test_allows_untracked_product_without_serials(self, db_session):
        company = make_company(db_session)
        product = make_product(
            db_session, company.id, sku="P-UNTRACKED-OK", track_serials=False
        )

        mgr = SerialManager(db_session)
        # Should not raise
        mgr.validate_for_items(
            validated((product, 3, None)),
            voucher_type="sales",
            company_id=company.id,
            invoice_id=None,
        )

    def test_rejects_too_few_serials(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-FEW")

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 3, ["A1", "A2"])),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "needs 3 serial numbers for quantity 3 (2 provided)" in exc_info.value.detail

    def test_rejects_too_many_serials(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-MANY")

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 2, ["A1", "A2", "A3"])),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "needs 2 serial numbers for quantity 2 (3 provided)" in exc_info.value.detail

    def test_rejects_tracked_line_with_no_serials(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-NONE")

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 1, None)),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "needs 1 serial number for quantity 1 (0 provided)" in exc_info.value.detail

    def test_rejects_same_product_on_two_lines(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-TWOLINE")

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 1, ["A1"]), (product, 1, ["A2"])),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "can only appear on one line per invoice" in exc_info.value.detail

    def test_rejects_duplicate_serial_within_payload(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-DUP")

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 2, ["A1", "a1"])),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "listed more than once on this invoice" in exc_info.value.detail

    def test_rejects_fractional_quantity_on_tracked_product(self, db_session):
        company = make_company(db_session)
        product = make_product(
            db_session, company.id, sku="P-FRAC", allow_decimal=True
        )

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 1.5, ["A1"])),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "quantity must be a whole number" in exc_info.value.detail

    def test_purchase_rejects_serial_already_registered(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-COLLIDE")
        purchase = make_invoice(
            db_session, company.id, voucher_type="purchase", invoice_number="PUR-000001"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["356938035643809"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 1, ["356938035643809"])),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "already registered to iPhone 15 128GB" in exc_info.value.detail
        assert "PUR-000001" in exc_info.value.detail

    def test_purchase_collision_is_case_insensitive(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-CASE")
        purchase = make_invoice(
            db_session, company.id, voucher_type="purchase", invoice_number="PUR-000002"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["imei-abc"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 1, ["IMEI-ABC"])),
                voucher_type="purchase",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400

    def test_purchase_allows_resaving_its_own_serials(self, db_session):
        """Re-validating an edit of the invoice that received the unit must not
        collide with itself."""
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-SELFEDIT")
        purchase = make_invoice(
            db_session, company.id, voucher_type="purchase", invoice_number="PUR-000003"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        # Should not raise
        mgr.validate_for_items(
            validated((product, 1, ["A1"])),
            voucher_type="purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

    def test_sales_rejects_unknown_serial(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-UNKNOWN")

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 1, ["NOPE-1"])),
                voucher_type="sales",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "Serial NOPE-1 is not in stock" in exc_info.value.detail

    def test_sales_rejects_serial_of_a_different_product(self, db_session):
        company = make_company(db_session)
        phone = make_product(db_session, company.id, sku="P-PHONE")
        tablet = make_product(
            db_session, company.id, name="iPad Air", sku="P-TABLET"
        )
        purchase = make_invoice(
            db_session, company.id, voucher_type="purchase", invoice_number="PUR-000004"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((tablet, 1, ["TAB-1"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((phone, 1, ["TAB-1"])),
                voucher_type="sales",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "Serial TAB-1 is already registered to iPad Air" in exc_info.value.detail

    def test_sales_rejects_already_sold_serial_naming_the_invoice(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-SOLD")
        purchase = make_invoice(
            db_session, company.id, voucher_type="purchase", invoice_number="PUR-000005"
        )
        sale = make_invoice(
            db_session, company.id, voucher_type="sales", invoice_number="INV-2026-118"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["356938035643809"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["356938035643809"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            mgr.validate_for_items(
                validated((product, 1, ["356938035643809"])),
                voucher_type="sales",
                company_id=company.id,
                invoice_id=None,
            )
        assert exc_info.value.status_code == 400
        assert "has already been sold" in exc_info.value.detail
        # The invoice it went out on is the whole point of the message.
        assert "INV-2026-118" in exc_info.value.detail


# ---------------------------------------------------------------------------
# SerialManager.apply_new_items
# ---------------------------------------------------------------------------

class TestApplyNewItems:
    def test_purchase_registers_serials_in_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-REG")
        purchase = make_invoice(
            db_session, company.id, voucher_type="purchase", invoice_number="PUR-000010"
        )

        codes = ["356938035643809", "356938035643817", "356938035643825"]
        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 3, codes)),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        rows = serials_of(db_session, product.id)
        assert [row.serial_number for row in rows] == codes
        assert all(row.status == STATUS_IN_STOCK for row in rows)
        assert all(row.purchase_invoice_id == purchase.id for row in rows)
        assert all(row.sales_invoice_id is None for row in rows)
        assert all(row.company_id == company.id for row in rows)

    def test_purchase_stores_the_code_as_entered(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-ASENTERED")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["  imei  Ab12  "])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        assert numbers_of(db_session, product.id) == ["imei Ab12"]

    def test_sale_consumes_serials(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-CONSUME")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        sale = make_invoice(
            db_session, company.id, voucher_type="sales", invoice_number="SAL-000001"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )

        sold = serials_of(db_session, product.id, status=STATUS_SOLD)
        assert [row.serial_number for row in sold] == ["A1"]
        assert sold[0].sales_invoice_id == sale.id
        assert sold[0].purchase_invoice_id == purchase.id
        assert numbers_of(db_session, product.id, status=STATUS_IN_STOCK) == ["A2"]

    def test_sale_matches_the_stored_serial_case_insensitively(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-SALECASE")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        sale = make_invoice(db_session, company.id, voucher_type="sales")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["imei-abc"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["IMEI-ABC"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )

        rows = serials_of(db_session, product.id)
        assert len(rows) == 1
        assert rows[0].status == STATUS_SOLD
        # The row keeps the code as it was received, not as it was scanned out.
        assert rows[0].serial_number == "imei-abc"

    def test_skips_untracked_products(self, db_session):
        company = make_company(db_session)
        product = make_product(
            db_session, company.id, sku="P-SKIP", track_serials=False
        )
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 5, None)),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        assert serials_of(db_session, product.id) == []

    def test_rejects_registration_without_an_active_company(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-NOCOMPANY")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        with pytest.raises(HTTPException) as exc_info:
            mgr.apply_new_items(
                validated((product, 1, ["A1"])),
                "purchase",
                company_id=None,
                invoice_id=purchase.id,
            )
        assert exc_info.value.status_code == 400
        assert "without an active company" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Per-tenant uniqueness
# ---------------------------------------------------------------------------

class TestTenantScopedUniqueness:
    def test_same_serial_allowed_in_two_companies(self, db_session):
        """Two shops can legitimately hold handsets with the same code on file —
        uniqueness is per tenant, not global."""
        company_a = make_company(db_session, name="Shop A", gst="27AABCU9603R1ZX")
        company_b = make_company(db_session, name="Shop B", gst="29AABCU9603R1ZY")
        product_a = make_product(db_session, company_a.id, sku="A-PHONE")
        product_b = make_product(db_session, company_b.id, sku="B-PHONE")
        purchase_a = make_invoice(db_session, company_a.id, voucher_type="purchase")
        purchase_b = make_invoice(db_session, company_b.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product_a, 1, ["356938035643809"])),
            "purchase",
            company_id=company_a.id,
            invoice_id=purchase_a.id,
        )
        mgr.apply_new_items(
            validated((product_b, 1, ["356938035643809"])),
            "purchase",
            company_id=company_b.id,
            invoice_id=purchase_b.id,
        )

        assert numbers_of(db_session, product_a.id) == ["356938035643809"]
        assert numbers_of(db_session, product_b.id) == ["356938035643809"]

    def test_lookup_does_not_cross_company_boundaries(self, db_session):
        company_a = make_company(db_session, name="Shop A", gst="27AABCU9603R1ZX")
        company_b = make_company(db_session, name="Shop B", gst="29AABCU9603R1ZY")
        product_a = make_product(db_session, company_a.id, sku="A-PHONE2")
        purchase_a = make_invoice(db_session, company_a.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product_a, 1, ["ONLY-IN-A"])),
            "purchase",
            company_id=company_a.id,
            invoice_id=purchase_a.id,
        )

        assert mgr.lookup("ONLY-IN-A", company_a.id) is not None
        assert mgr.lookup("ONLY-IN-A", company_b.id) is None

    def test_same_serial_twice_in_one_company_is_rejected(self, db_session):
        company = make_company(db_session)
        phone = make_product(db_session, company.id, sku="P-ONE")
        tablet = make_product(
            db_session, company.id, name="iPad Air", sku="P-TWO"
        )
        first = make_invoice(
            db_session, company.id, voucher_type="purchase", invoice_number="PUR-000020"
        )
        second = make_invoice(db_session, company.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((phone, 1, ["356938035643809"])),
            "purchase",
            company_id=company.id,
            invoice_id=first.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            mgr.apply_new_items(
                validated((tablet, 1, ["356938035643809"])),
                "purchase",
                company_id=company.id,
                invoice_id=second.id,
            )
        assert exc_info.value.status_code == 400
        assert "already registered to iPhone 15 128GB" in exc_info.value.detail
        assert "PUR-000020" in exc_info.value.detail


# ---------------------------------------------------------------------------
# SerialManager.apply_invoice_changes  (the per-product set-diff)
# ---------------------------------------------------------------------------

class TestApplyInvoiceChanges:
    def _payload(self, ledger_id, product_id, quantity, serials, voucher_type="sales"):
        return InvoiceCreate(
            ledger_id=ledger_id,
            voucher_type=voucher_type,
            items=[
                InvoiceItemCreate(
                    product_id=product_id,
                    quantity=quantity,
                    serial_numbers=serials,
                )
            ],
        )

    def test_purchase_edit_adds_and_removes_units(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-EDITPUR")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, purchase.id, product.id, quantity=2)

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        # A2 dropped, A3 added
        payload = self._payload(
            1, product.id, 2, ["A1", "A3"], voucher_type="purchase"
        )
        mgr.apply_invoice_changes(purchase, payload, company_id=company.id)

        assert sorted(numbers_of(db_session, product.id)) == ["A1", "A3"]
        # A removal on a purchase deletes the row rather than voiding it —
        # void is reserved for cancellation.
        assert db_session.query(ProductSerial).filter(
            ProductSerial.serial_number == "A2"
        ).count() == 0

    def test_purchase_edit_refuses_to_remove_a_sold_unit(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-EDITSOLD")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, purchase.id, product.id, quantity=2)
        sale = make_invoice(
            db_session, company.id, voucher_type="sales", invoice_number="SAL-000090"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["A2"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )

        payload = self._payload(1, product.id, 1, ["A1"], voucher_type="purchase")
        with pytest.raises(HTTPException) as exc_info:
            mgr.apply_invoice_changes(purchase, payload, company_id=company.id)
        assert exc_info.value.status_code == 400
        assert "Serial A2 cannot be removed" in exc_info.value.detail
        assert "SAL-000090" in exc_info.value.detail

    def test_sales_edit_swaps_a_unit(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-EDITSAL")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        sale = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, sale.id, product.id, quantity=1)

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )

        payload = self._payload(1, product.id, 1, ["A2"], voucher_type="sales")
        mgr.apply_invoice_changes(sale, payload, company_id=company.id)

        assert numbers_of(db_session, product.id, status=STATUS_SOLD) == ["A2"]
        # The released unit goes back in stock, detached from the sale.
        released = db_session.query(ProductSerial).filter(
            ProductSerial.serial_number == "A1"
        ).one()
        assert released.status == STATUS_IN_STOCK
        assert released.sales_invoice_id is None

    def test_no_change_leaves_the_original_rows_alone(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-NOOP")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, purchase.id, product.id, quantity=2)

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        original_ids = [row.id for row in serials_of(db_session, product.id)]

        payload = self._payload(
            1, product.id, 2, ["A1", "A2"], voucher_type="purchase"
        )
        mgr.apply_invoice_changes(purchase, payload, company_id=company.id)

        assert [row.id for row in serials_of(db_session, product.id)] == original_ids


# ---------------------------------------------------------------------------
# SerialManager.reverse_invoice_serials  (cancel)
# ---------------------------------------------------------------------------

class TestReverseInvoiceSerials:
    def test_cancelling_a_purchase_voids_its_units(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-CANCELPUR")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, purchase.id, product.id, quantity=2)

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        mgr.reverse_invoice_serials(purchase)

        rows = serials_of(db_session, product.id)
        assert all(row.status == STATUS_VOID for row in rows)
        assert serials_of(db_session, product.id, status=STATUS_IN_STOCK) == []

    def test_cancelling_a_purchase_with_a_sold_unit_is_refused(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-CANCELSOLD")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, purchase.id, product.id, quantity=2)
        sale = make_invoice(
            db_session, company.id, voucher_type="sales", invoice_number="INV-2026-118"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["356938035643809", "356938035643817"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["356938035643817"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            mgr.reverse_invoice_serials(purchase)
        assert exc_info.value.status_code == 400
        assert "356938035643817" in exc_info.value.detail
        assert "INV-2026-118" in exc_info.value.detail
        assert "Cancel that sale first" in exc_info.value.detail

        # Nothing was voided — the refusal is all-or-nothing.
        assert len(serials_of(db_session, product.id, status=STATUS_IN_STOCK)) == 1

    def test_cancelling_a_sale_returns_its_units_to_stock(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-CANCELSAL")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        sale = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, sale.id, product.id, quantity=1)

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )

        mgr.reverse_invoice_serials(sale)

        row = db_session.query(ProductSerial).filter(
            ProductSerial.serial_number == "A1"
        ).one()
        assert row.status == STATUS_IN_STOCK
        # sales_invoice_id is kept deliberately: it is the only record of which
        # handsets went out on this invoice, and restore reads it back.
        assert row.sales_invoice_id == sale.id


# ---------------------------------------------------------------------------
# Re-registering a voided serial  (the partial unique index)
# ---------------------------------------------------------------------------

class TestVoidedSerialsCanBeRegisteredAgain:
    def test_voided_number_is_free_for_a_new_purchase(self, db_session):
        """The unique index excludes voided rows, so a wrongly-entered IMEI can
        be received again once the purchase carrying it is cancelled.  Worth an
        explicit test: a partial index behaves differently per dialect."""
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-REVOID")
        first = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, first.id, product.id, quantity=1)
        second = make_invoice(db_session, company.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["356938035643809"])),
            "purchase",
            company_id=company.id,
            invoice_id=first.id,
        )
        mgr.reverse_invoice_serials(first)

        # Should not raise — nor hit the unique index
        mgr.apply_new_items(
            validated((product, 1, ["356938035643809"])),
            "purchase",
            company_id=company.id,
            invoice_id=second.id,
        )
        db_session.commit()

        rows = serials_of(db_session, product.id)
        assert len(rows) == 2
        assert {row.status for row in rows} == {STATUS_VOID, STATUS_IN_STOCK}
        live = [row for row in rows if row.status == STATUS_IN_STOCK]
        assert live[0].purchase_invoice_id == second.id

    def test_a_voided_unit_is_invisible_to_lookup(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-VOIDLOOKUP")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.reverse_invoice_serials(purchase)

        assert mgr.lookup("A1", company.id) is None


# ---------------------------------------------------------------------------
# SerialManager.restore_invoice_serials
# ---------------------------------------------------------------------------

class TestRestoreInvoiceSerials:
    def test_restores_a_cancelled_purchase(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-RSTPUR")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, purchase.id, product.id, quantity=2)

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.reverse_invoice_serials(purchase)
        mgr.restore_invoice_serials(purchase, company_id=company.id)

        assert sorted(
            numbers_of(db_session, product.id, status=STATUS_IN_STOCK)
        ) == ["A1", "A2"]

    def test_restore_refused_when_the_number_was_registered_again(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-RSTCLASH")
        first = make_invoice(db_session, company.id, voucher_type="purchase")
        add_item(db_session, first.id, product.id, quantity=1)
        second = make_invoice(
            db_session, company.id, voucher_type="purchase", invoice_number="PUR-000099"
        )

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["356938035643809"])),
            "purchase",
            company_id=company.id,
            invoice_id=first.id,
        )
        mgr.reverse_invoice_serials(first)
        mgr.apply_new_items(
            validated((product, 1, ["356938035643809"])),
            "purchase",
            company_id=company.id,
            invoice_id=second.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            mgr.restore_invoice_serials(first, company_id=company.id)
        assert exc_info.value.status_code == 400
        assert "has been registered again" in exc_info.value.detail
        assert "PUR-000099" in exc_info.value.detail

    def test_restores_a_cancelled_sale(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-RSTSAL")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        sale = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, sale.id, product.id, quantity=1)

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )
        mgr.reverse_invoice_serials(sale)
        mgr.restore_invoice_serials(sale, company_id=company.id)

        row = db_session.query(ProductSerial).filter(
            ProductSerial.serial_number == "A1"
        ).one()
        assert row.status == STATUS_SOLD
        assert row.sales_invoice_id == sale.id
        assert numbers_of(db_session, product.id, status=STATUS_IN_STOCK) == ["A2"]

    def test_restore_of_a_sale_refused_when_units_went_elsewhere(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-RSTGONE")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        sale = make_invoice(db_session, company.id, voucher_type="sales")
        add_item(db_session, sale.id, product.id, quantity=1)
        other_sale = make_invoice(db_session, company.id, voucher_type="sales")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )
        mgr.reverse_invoice_serials(sale)
        # The freed handset goes out on a different invoice while this one is
        # cancelled.
        mgr.apply_new_items(
            validated((product, 1, ["A1"])),
            "sales",
            company_id=company.id,
            invoice_id=other_sale.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            mgr.restore_invoice_serials(sale, company_id=company.id)
        assert exc_info.value.status_code == 400
        assert "no longer has the 1 serial number" in exc_info.value.detail


# ---------------------------------------------------------------------------
# SerialManager read paths
# ---------------------------------------------------------------------------

class TestLookup:
    def test_matches_case_insensitively_and_ignores_stray_spacing(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-LOOKUP")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 1, ["imei-Ab12"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        assert mgr.lookup("IMEI-AB12", company.id).product_id == product.id
        assert mgr.lookup("  imei-ab12  ", company.id).product_id == product.id

    def test_blank_code_resolves_to_nothing(self, db_session):
        company = make_company(db_session)
        mgr = SerialManager(db_session)
        assert mgr.lookup("   ", company.id) is None


class TestSerialsForInvoice:
    def test_maps_serials_by_product_for_a_purchase(self, db_session):
        company = make_company(db_session)
        phone = make_product(db_session, company.id, sku="P-MAP1")
        tablet = make_product(
            db_session, company.id, name="iPad Air", sku="P-MAP2"
        )
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((phone, 2, ["A1", "A2"]), (tablet, 1, ["B1"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )

        assert mgr.serials_for_invoice(purchase) == {
            phone.id: ["A1", "A2"],
            tablet.id: ["B1"],
        }

    def test_maps_serials_for_a_whole_page_of_invoices(self, db_session):
        company = make_company(db_session)
        product = make_product(db_session, company.id, sku="P-MAPPAGE")
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        sale = make_invoice(db_session, company.id, voucher_type="sales")

        mgr = SerialManager(db_session)
        mgr.apply_new_items(
            validated((product, 2, ["A1", "A2"])),
            "purchase",
            company_id=company.id,
            invoice_id=purchase.id,
        )
        mgr.apply_new_items(
            validated((product, 1, ["A2"])),
            "sales",
            company_id=company.id,
            invoice_id=sale.id,
        )

        mapped = mgr.serials_for_invoices([purchase, sale])
        assert mapped[purchase.id] == {product.id: ["A1", "A2"]}
        assert mapped[sale.id] == {product.id: ["A2"]}

    def test_empty_for_an_invoice_with_no_serials(self, db_session):
        company = make_company(db_session)
        purchase = make_invoice(db_session, company.id, voucher_type="purchase")
        assert SerialManager(db_session).serials_for_invoice(purchase) == {}
