from datetime import datetime
from pathlib import Path
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from src.api.routes.invoices import _apply_payload_to_invoice, _build_invoice_html
from src.db.base import Base
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _seed_common(db_session, ledger_gst: str = "07ABCDE1234F1Z5"):
    user = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="secret",
        role=UserRole.admin,
    )
    ledger = Buyer(
        name="Test Ledger",
        address="Some Address",
        gst=ledger_gst,
        phone_number="9999999999",
    )
    company = CompanyProfile(
        name="Respawn",
        address="HQ",
        gst="07AAMPB1274B1Z8",
        phone_number="8888888888",
        currency_code="INR",
    )
    db_session.add_all([user, ledger, company])
    db_session.flush()
    return user, ledger


def _create_product_with_inventory(db_session, sku: str, price: float, gst_rate: float) -> Product:
    product = Product(
        sku=sku,
        name=f"Product {sku}",
        price=price,
        gst_rate=gst_rate,
    )
    db_session.add(product)
    db_session.flush()

    inventory = Inventory(product_id=product.id, quantity=100)
    db_session.add(inventory)
    db_session.flush()
    return product


def _new_invoice(db_session) -> Invoice:
    invoice = Invoice(
        total_amount=0,
        created_by=1,
        invoice_date=datetime.utcnow(),
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


def test_intrastate_odd_paise_total_tax_is_adjusted_and_split_equally(db_session):
    user, ledger = _seed_common(db_session)
    product = _create_product_with_inventory(db_session, "ODD01", 100.03, 18)
    invoice = _new_invoice(db_session)

    payload = InvoiceCreate(
        ledger_id=ledger.id,
        voucher_type="sales",
        tax_inclusive=False,
        items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100.03)],
    )

    _apply_payload_to_invoice(
        db_session,
        invoice,
        payload,
        created_by=user.id,
        regenerate_number=False,
    )
    db_session.flush()
    db_session.refresh(invoice)

    assert float(invoice.total_tax_amount) == pytest.approx(18.02)
    assert float(invoice.cgst_amount) == pytest.approx(9.01)
    assert float(invoice.sgst_amount) == pytest.approx(9.01)
    assert float(invoice.cgst_amount) == pytest.approx(float(invoice.sgst_amount))

    assert len(invoice.items) == 1
    assert float(invoice.items[0].tax_amount) == pytest.approx(18.02)
    assert float(invoice.items[0].cgst_amount) == pytest.approx(9.01)
    assert float(invoice.items[0].sgst_amount) == pytest.approx(9.01)
    assert float(invoice.items[0].igst_amount) == pytest.approx(0)
    assert float(invoice.items[0].line_total) == pytest.approx(118.05)

    html = _build_invoice_html(invoice, [product])
    assert "SGST %</th>" in html
    assert "CGST %</th>" in html
    assert "Total Tax</th>" in html
    assert "IGST %</th>" not in html
    assert "GST Split" not in html


def test_intrastate_three_line_case_keeps_cgst_sgst_equal(db_session):
    user, ledger = _seed_common(db_session)
    p1 = _create_product_with_inventory(db_session, "MS02", 254.24, 18)
    p2 = _create_product_with_inventory(db_session, "LED01", 2457.63, 18)
    p3 = _create_product_with_inventory(db_session, "KB04", 508.47, 18)
    invoice = _new_invoice(db_session)

    payload = InvoiceCreate(
        ledger_id=ledger.id,
        voucher_type="sales",
        tax_inclusive=False,
        items=[
            InvoiceItemCreate(product_id=p1.id, quantity=1, unit_price=254.24),
            InvoiceItemCreate(product_id=p2.id, quantity=1, unit_price=2457.63),
            InvoiceItemCreate(product_id=p3.id, quantity=1, unit_price=508.47),
        ],
    )

    _apply_payload_to_invoice(
        db_session,
        invoice,
        payload,
        created_by=user.id,
        regenerate_number=False,
    )
    db_session.flush()
    db_session.refresh(invoice)

    assert float(invoice.taxable_amount) == pytest.approx(3220.34)
    assert float(invoice.total_tax_amount) == pytest.approx(579.66)
    assert float(invoice.cgst_amount) == pytest.approx(289.83)
    assert float(invoice.sgst_amount) == pytest.approx(289.83)
    assert float(invoice.cgst_amount) == pytest.approx(float(invoice.sgst_amount))

    assert len(invoice.items) == 3
    assert float(invoice.items[0].tax_amount) == pytest.approx(45.76)
    assert float(invoice.items[1].tax_amount) == pytest.approx(442.37)
    assert float(invoice.items[2].tax_amount) == pytest.approx(91.53)
    assert float(invoice.items[0].cgst_amount) == pytest.approx(22.88)
    assert float(invoice.items[0].sgst_amount) == pytest.approx(22.88)
    assert float(invoice.items[1].cgst_amount) == pytest.approx(221.19)
    assert float(invoice.items[1].sgst_amount) == pytest.approx(221.18)
    assert float(invoice.items[2].cgst_amount) == pytest.approx(45.76)
    assert float(invoice.items[2].sgst_amount) == pytest.approx(45.77)
    assert sum(float(item.cgst_amount) for item in invoice.items) == pytest.approx(289.83)
    assert sum(float(item.sgst_amount) for item in invoice.items) == pytest.approx(289.83)
    assert sum(float(item.igst_amount) for item in invoice.items) == pytest.approx(0)


def test_interstate_item_tax_is_stored_as_igst_and_rendered_in_pdf(db_session):
    user, ledger = _seed_common(db_session, ledger_gst="27ABCDE1234F1Z5")
    product = _create_product_with_inventory(db_session, "IGST01", 100.00, 18)
    invoice = _new_invoice(db_session)

    payload = InvoiceCreate(
        ledger_id=ledger.id,
        voucher_type="sales",
        tax_inclusive=False,
        items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100.00)],
    )

    _apply_payload_to_invoice(
        db_session,
        invoice,
        payload,
        created_by=user.id,
        regenerate_number=False,
    )
    db_session.flush()
    db_session.refresh(invoice)

    assert float(invoice.cgst_amount) == pytest.approx(0)
    assert float(invoice.sgst_amount) == pytest.approx(0)
    assert float(invoice.igst_amount) == pytest.approx(18.00)
    assert len(invoice.items) == 1
    assert float(invoice.items[0].cgst_amount) == pytest.approx(0)
    assert float(invoice.items[0].sgst_amount) == pytest.approx(0)
    assert float(invoice.items[0].igst_amount) == pytest.approx(18.00)

    html = _build_invoice_html(invoice, [product])
    assert "IGST %</th>" in html
    assert "Total Tax</th>" in html
    assert "SGST %</th>" not in html
    assert "CGST %</th>" not in html
    assert "GST Split" not in html