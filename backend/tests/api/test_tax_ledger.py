from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.routes.ledgers import get_tax_ledger
from src.db.base import Base
from src.models.buyer import Buyer
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice, InvoiceItem
from src.models.user import User, UserRole


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _seed_basics(db_session):
    user = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="secret",
        role=UserRole.admin,
    )
    ledger = Buyer(
        name="Acme Stores",
        address="42 Market Road",
        gst="29ABCDE1234F1Z5",
        phone_number="9999999999",
        email="ledger@example.com",
    )
    db_session.add_all([user, ledger])
    db_session.commit()
    return user, ledger


def _add_invoice_with_item(
    db_session,
    ledger,
    user,
    *,
    voucher_type: str,
    invoice_number: str,
    when: datetime,
    gst_rate: float,
    taxable_amount: float,
    cgst_amount: float,
    sgst_amount: float,
    igst_amount: float,
):
    total_tax = cgst_amount + sgst_amount + igst_amount
    invoice = Invoice(
        invoice_number=invoice_number,
        ledger_id=ledger.id,
        ledger_name=ledger.name,
        ledger_address=ledger.address,
        ledger_gst=ledger.gst,
        ledger_phone=ledger.phone_number,
        company_name="Respawn Pvt Ltd",
        company_address="1 Billing Street",
        company_gst="29RESP1234N1Z1",
        company_phone="8888888888",
        company_email="accounts@example.com",
        company_currency_code="INR",
        voucher_type=voucher_type,
        status="active",
        created_by=user.id,
        taxable_amount=taxable_amount,
        total_tax_amount=total_tax,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        total_amount=taxable_amount + total_tax,
        invoice_date=when,
    )
    db_session.add(invoice)
    db_session.flush()

    item = InvoiceItem(
        invoice_id=invoice.id,
        product_id=1,
        quantity=1,
        unit_price=taxable_amount,
        gst_rate=gst_rate,
        taxable_amount=taxable_amount,
        tax_amount=total_tax,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        line_total=taxable_amount + total_tax,
    )
    db_session.add(item)
    db_session.flush()
    return invoice


def _add_credit_note_item(
    db_session,
    user,
    ledger,
    invoice,
    *,
    number: str,
    when: datetime,
    gst_rate: float,
    taxable_amount: float,
    cgst_amount: float,
    sgst_amount: float,
    igst_amount: float,
):
    total_tax = cgst_amount + sgst_amount + igst_amount
    credit_note = CreditNote(
        credit_note_number=number,
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        status="active",
        taxable_amount=taxable_amount,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        total_amount=taxable_amount + total_tax,
        created_at=when,
    )
    db_session.add(credit_note)
    db_session.flush()

    item = CreditNoteItem(
        credit_note_id=credit_note.id,
        invoice_id=invoice.id,
        invoice_item_id=invoice.items[0].id if invoice.items else None,
        quantity=1,
        unit_price=taxable_amount,
        gst_rate=gst_rate,
        taxable_amount=taxable_amount,
        tax_amount=total_tax,
        line_total=taxable_amount + total_tax,
        created_at=when,
    )
    db_session.add(item)
    db_session.flush()
    return credit_note


def test_tax_ledger_includes_invoice_tax_and_credit_note_reversals(db_session):
    user, ledger = _seed_basics(db_session)

    sales_invoice = _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="S-001",
        when=datetime(2026, 1, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=100,
        cgst_amount=9,
        sgst_amount=9,
        igst_amount=0,
    )
    purchase_invoice = _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="purchase",
        invoice_number="P-001",
        when=datetime(2026, 1, 11, 9, 0, 0),
        gst_rate=18,
        taxable_amount=200,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=36,
    )

    sales_credit_note = _add_credit_note_item(
        db_session,
        user,
        ledger,
        sales_invoice,
        number="CN-S-001",
        when=datetime(2026, 1, 12, 9, 0, 0),
        gst_rate=18,
        taxable_amount=50,
        cgst_amount=4.5,
        sgst_amount=4.5,
        igst_amount=0,
    )
    purchase_credit_note = _add_credit_note_item(
        db_session,
        user,
        ledger,
        purchase_invoice,
        number="CN-P-001",
        when=datetime(2026, 1, 13, 9, 0, 0),
        gst_rate=18,
        taxable_amount=100,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=18,
    )
    db_session.commit()

    response = get_tax_ledger(
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 31),
        voucher_type=None,
        gst_rate=None,
        db=db_session,
        _=user,
    )

    assert len(response.entries) == 4

    entry_by_key = {(entry.entry_type, entry.entry_id): entry for entry in response.entries}
    assert entry_by_key[("invoice", sales_invoice.id)].debit_total_tax == pytest.approx(18.0)
    assert entry_by_key[("invoice", purchase_invoice.id)].credit_total_tax == pytest.approx(36.0)
    assert entry_by_key[("credit_note", sales_credit_note.id)].credit_total_tax == pytest.approx(9.0)
    assert entry_by_key[("credit_note", purchase_credit_note.id)].debit_total_tax == pytest.approx(18.0)

    assert response.totals.debit_cgst == pytest.approx(9.0)
    assert response.totals.debit_sgst == pytest.approx(9.0)
    assert response.totals.debit_igst == pytest.approx(18.0)
    assert response.totals.debit_total_tax == pytest.approx(36.0)

    assert response.totals.credit_cgst == pytest.approx(4.5)
    assert response.totals.credit_sgst == pytest.approx(4.5)
    assert response.totals.credit_igst == pytest.approx(36.0)
    assert response.totals.credit_total_tax == pytest.approx(45.0)
    assert response.totals.net_total_tax == pytest.approx(-9.0)


def test_tax_ledger_supports_voucher_type_and_gst_rate_filters(db_session):
    user, ledger = _seed_basics(db_session)

    sales_invoice = _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="S-010",
        when=datetime(2026, 2, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=100,
        cgst_amount=9,
        sgst_amount=9,
        igst_amount=0,
    )
    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="S-005",
        when=datetime(2026, 2, 11, 9, 0, 0),
        gst_rate=5,
        taxable_amount=100,
        cgst_amount=2.5,
        sgst_amount=2.5,
        igst_amount=0,
    )
    purchase_invoice = _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="purchase",
        invoice_number="P-010",
        when=datetime(2026, 2, 12, 9, 0, 0),
        gst_rate=18,
        taxable_amount=200,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=36,
    )

    sales_credit_note = _add_credit_note_item(
        db_session,
        user,
        ledger,
        sales_invoice,
        number="CN-S-010",
        when=datetime(2026, 2, 13, 9, 0, 0),
        gst_rate=18,
        taxable_amount=20,
        cgst_amount=1.8,
        sgst_amount=1.8,
        igst_amount=0,
    )
    _add_credit_note_item(
        db_session,
        user,
        ledger,
        purchase_invoice,
        number="CN-P-010",
        when=datetime(2026, 2, 14, 9, 0, 0),
        gst_rate=18,
        taxable_amount=100,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=18,
    )
    db_session.commit()

    response = get_tax_ledger(
        from_date=date(2026, 2, 1),
        to_date=date(2026, 2, 28),
        voucher_type="sales",
        gst_rate=18,
        db=db_session,
        _=user,
    )

    assert len(response.entries) == 2
    assert {entry.entry_type for entry in response.entries} == {"invoice", "credit_note"}
    assert all(entry.source_voucher_type == "sales" for entry in response.entries)
    assert all(entry.gst_rate == pytest.approx(18.0) for entry in response.entries)

    entry_by_key = {(entry.entry_type, entry.entry_id): entry for entry in response.entries}
    assert entry_by_key[("invoice", sales_invoice.id)].debit_total_tax == pytest.approx(18.0)
    assert entry_by_key[("credit_note", sales_credit_note.id)].credit_total_tax == pytest.approx(3.6)
