import csv
import asyncio
from datetime import date, datetime
from io import StringIO

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import HTTPException

from src.api.routes.ledgers import _doc_range, _doc_ranges, get_tax_ledger, gstr1_export_csv, gstr1_export_json, gstr1_summary, gstr1_validate
from src.db.base import Base
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
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
        gst="29ABCDE1234F1ZW",
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
        hsn_sac="84713010",
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
    credit_note_type: str = "return",
    direction: str = "outward",
):
    total_tax = cgst_amount + sgst_amount + igst_amount
    credit_note = CreditNote(
        credit_note_number=number,
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type=credit_note_type,
        direction=direction,
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


def _make_company(name="Test Co", gst="29TESTT1234X1ZE"):
    return CompanyProfile(
        name=name,
        address="Somewhere",
        gst=gst,
        phone_number="999",
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Existing Tax Ledger Tests
# ═══════════════════════════════════════════════════════════════════════════

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

    # Taxable value follows the same side as the tax on it, so the summary
    # figures net purchases and credit notes off sales the way the tax does.
    assert response.totals.debit_taxable == pytest.approx(200.0)   # S-001 + CN-P-001
    assert response.totals.credit_taxable == pytest.approx(250.0)  # P-001 + CN-S-001
    assert response.totals.net_taxable == pytest.approx(-50.0)

    assert response.totals.debit_gross == pytest.approx(236.0)
    assert response.totals.credit_gross == pytest.approx(295.0)
    assert response.totals.net_gross == pytest.approx(-59.0)
    assert response.totals.net_gross == pytest.approx(
        response.totals.net_taxable + response.totals.net_total_tax
    )


def test_tax_liability_sets_off_credit_within_each_head(db_session):
    """Intra-state sales against intra-state purchases: like clears like."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="S-100",
        when=datetime(2026, 1, 10, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=90, sgst_amount=90, igst_amount=0,
    )
    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="purchase", invoice_number="P-100",
        when=datetime(2026, 1, 11, 9, 0, 0), gst_rate=18,
        taxable_amount=400, cgst_amount=36, sgst_amount=36, igst_amount=0,
    )
    db_session.commit()

    liability = get_tax_ledger(
        from_date=date(2026, 1, 1), to_date=date(2026, 1, 31),
        voucher_type=None, gst_rate=None, db=db_session, _=user,
    ).liability

    assert liability.cgst.output_tax == pytest.approx(90.0)
    assert liability.cgst.input_credit == pytest.approx(36.0)
    assert liability.cgst.credit_used == pytest.approx(36.0)
    assert liability.cgst.payable == pytest.approx(54.0)
    assert liability.sgst.payable == pytest.approx(54.0)
    assert liability.igst.payable == pytest.approx(0.0)

    assert liability.payable == pytest.approx(108.0)
    assert liability.credit_carried_forward == pytest.approx(0.0)


def test_tax_liability_does_not_set_cgst_credit_against_sgst(db_session):
    """The case a plain net of the three heads gets wrong.

    CGST credit cannot touch an SGST liability, so cash is still due even
    though the heads sum to zero between them.
    """
    user, ledger = _seed_basics(db_session)

    # Sales carrying SGST only, purchases carrying CGST only. Contrived, but it
    # is exactly the shape that separates a real set-off from a subtraction.
    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="S-200",
        when=datetime(2026, 1, 10, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=0, sgst_amount=100, igst_amount=0,
    )
    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="purchase", invoice_number="P-200",
        when=datetime(2026, 1, 11, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=100, sgst_amount=0, igst_amount=0,
    )
    db_session.commit()

    response = get_tax_ledger(
        from_date=date(2026, 1, 1), to_date=date(2026, 1, 31),
        voucher_type=None, gst_rate=None, db=db_session, _=user,
    )

    # Netting the heads together says nothing is owed...
    assert response.totals.net_total_tax == pytest.approx(0.0)
    # ...but the SGST has to be paid in cash and the CGST credit carries over.
    assert response.liability.sgst.payable == pytest.approx(100.0)
    assert response.liability.sgst.credit_used == pytest.approx(0.0)
    assert response.liability.payable == pytest.approx(100.0)
    assert response.liability.cgst.credit_carried_forward == pytest.approx(100.0)
    assert response.liability.credit_carried_forward == pytest.approx(100.0)


def test_tax_liability_spends_igst_credit_across_heads(db_session):
    """IGST credit clears IGST first, then crosses into CGST and SGST."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="S-300",
        when=datetime(2026, 1, 10, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=50, sgst_amount=50, igst_amount=30,
    )
    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="purchase", invoice_number="P-300",
        when=datetime(2026, 1, 11, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=0, sgst_amount=0, igst_amount=100,
    )
    db_session.commit()

    liability = get_tax_ledger(
        from_date=date(2026, 1, 1), to_date=date(2026, 1, 31),
        voucher_type=None, gst_rate=None, db=db_session, _=user,
    ).liability

    # 100 of IGST credit: 30 to IGST, then 50 to CGST, leaving 20 for SGST.
    assert liability.igst.payable == pytest.approx(0.0)
    assert liability.cgst.credit_used == pytest.approx(50.0)
    assert liability.cgst.payable == pytest.approx(0.0)
    assert liability.sgst.credit_used == pytest.approx(20.0)
    assert liability.sgst.payable == pytest.approx(30.0)
    assert liability.payable == pytest.approx(30.0)
    assert liability.credit_carried_forward == pytest.approx(0.0)


def test_tax_liability_igst_credit_pays_the_head_cgst_credit_cannot(db_session):
    """IGST credit goes to SGST when CGST credit already covers CGST."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="S-350",
        when=datetime(2026, 1, 10, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=100, sgst_amount=100, igst_amount=0,
    )
    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="purchase", invoice_number="P-350",
        when=datetime(2026, 1, 11, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=100, sgst_amount=0, igst_amount=100,
    )
    db_session.commit()

    liability = get_tax_ledger(
        from_date=date(2026, 1, 1), to_date=date(2026, 1, 31),
        voucher_type=None, gst_rate=None, db=db_session, _=user,
    ).liability

    assert liability.cgst.payable == pytest.approx(0.0)
    assert liability.sgst.payable == pytest.approx(0.0)
    assert liability.sgst.credit_used == pytest.approx(100.0)
    assert liability.payable == pytest.approx(0.0)
    assert liability.credit_carried_forward == pytest.approx(0.0)


def test_tax_liability_nets_credit_notes_off_their_own_side(db_session):
    """A sales credit note reduces output tax; a purchase one reduces credit."""
    user, ledger = _seed_basics(db_session)

    sales_invoice = _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="S-400",
        when=datetime(2026, 1, 10, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=90, sgst_amount=90, igst_amount=0,
    )
    purchase_invoice = _add_invoice_with_item(
        db_session, ledger, user, voucher_type="purchase", invoice_number="P-400",
        when=datetime(2026, 1, 11, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=50, sgst_amount=50, igst_amount=0,
    )
    _add_credit_note_item(
        db_session, user, ledger, sales_invoice, number="CN-S-400",
        when=datetime(2026, 1, 12, 9, 0, 0), gst_rate=18,
        taxable_amount=200, cgst_amount=18, sgst_amount=18, igst_amount=0,
    )
    _add_credit_note_item(
        db_session, user, ledger, purchase_invoice, number="CN-P-400",
        when=datetime(2026, 1, 13, 9, 0, 0), gst_rate=18,
        taxable_amount=200, cgst_amount=10, sgst_amount=10, igst_amount=0,
    )
    db_session.commit()

    liability = get_tax_ledger(
        from_date=date(2026, 1, 1), to_date=date(2026, 1, 31),
        voucher_type=None, gst_rate=None, db=db_session, _=user,
    ).liability

    assert liability.cgst.output_tax == pytest.approx(72.0)   # 90 - 18
    assert liability.cgst.input_credit == pytest.approx(40.0)  # 50 - 10
    assert liability.cgst.payable == pytest.approx(32.0)
    assert liability.payable == pytest.approx(64.0)


def test_tax_liability_carries_surplus_credit_forward(db_session):
    """Buying more than you sell leaves credit, not a negative amount due."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="S-500",
        when=datetime(2026, 1, 10, 9, 0, 0), gst_rate=18,
        taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0,
    )
    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="purchase", invoice_number="P-500",
        when=datetime(2026, 1, 11, 9, 0, 0), gst_rate=18,
        taxable_amount=1000, cgst_amount=90, sgst_amount=90, igst_amount=0,
    )
    db_session.commit()

    liability = get_tax_ledger(
        from_date=date(2026, 1, 1), to_date=date(2026, 1, 31),
        voucher_type=None, gst_rate=None, db=db_session, _=user,
    ).liability

    assert liability.payable == pytest.approx(0.0)
    assert liability.cgst.credit_carried_forward == pytest.approx(81.0)
    assert liability.credit_carried_forward == pytest.approx(162.0)


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


def test_tax_ledger_includes_ledger_gst(db_session):
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="S-GST-001",
        when=datetime(2026, 3, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=100,
        cgst_amount=9,
        sgst_amount=9,
        igst_amount=0,
    )
    db_session.commit()

    response = get_tax_ledger(
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 31),
        voucher_type=None,
        gst_rate=None,
        db=db_session,
        _=user,
    )

    assert len(response.entries) == 1
    assert response.entries[0].ledger_gst == "29ABCDE1234F1ZW"


# ═══════════════════════════════════════════════════════════════════════════
#  GSTR-1 Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_gstr1_validate_passes_for_valid_sales_invoices(db_session):
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="GS-001",
        when=datetime(2026, 4, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.flush()
    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "GS-001").first()
    inv.items[0].hsn_sac = "84713010"
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
        db=db_session,
        _=user,
        active_company=None,
    )

    assert result.status == "valid"
    assert result.total_invoices == 1
    assert result.valid_invoices == 1
    assert result.invalid_invoices == 0
    assert len(result.errors) == 0


def test_gstr1_validate_ignores_purchase_invoices(db_session):
    user, ledger = _seed_basics(db_session)

    purchase = _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="purchase",
        invoice_number="GP-BAD",
        when=datetime(2026, 4, 11, 9, 0, 0),
        gst_rate=17.99,
        taxable_amount=0,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=0,
    )
    purchase.ledger_gst = "INVALID"
    purchase.items[0].hsn_sac = None

    sales = _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="GS-BAD-MIXED",
        when=datetime(2026, 4, 12, 9, 0, 0),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    sales.ledger_gst = "INVALID"
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
        db=db_session,
        _=user,
        active_company=None,
    )

    assert result.status == "invalid"
    assert result.total_invoices == 1
    assert result.valid_invoices == 0
    assert result.invalid_invoices == 1
    assert all(error.invoice_number != "GP-BAD" for error in result.errors)
    assert any(error.invoice_number == "GS-BAD-MIXED" and "Invalid GSTIN" in error.message for error in result.errors)


def test_gstr1_validate_detects_missing_gstin(db_session):
    user, ledger = _seed_basics(db_session)
    ledger.gst = None
    db_session.flush()

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="GS-NOGST",
        when=datetime(2026, 5, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    db_session.flush()
    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "GS-NOGST").first()
    inv.ledger_gst = None
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 5, 1),
        to_date=date(2026, 5, 31),
        db=db_session,
        _=user,
        active_company=None,
    )

    # A missing buyer GSTIN is a B2C supply — it must NOT block filing.
    # It is surfaced as a warning, and the return stays valid.
    assert result.status == "valid"
    gstin_warnings = [e for e in result.errors if e.field == "GSTIN"]
    assert len(gstin_warnings) == 1
    assert gstin_warnings[0].severity == "warning"
    assert "B2C" in gstin_warnings[0].message


def test_gstr1_validate_detects_invalid_gstin(db_session):
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="GS-BAD",
        when=datetime(2026, 6, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    db_session.flush()
    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "GS-BAD").first()
    inv.ledger_gst = "INVALID"
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 30),
        db=db_session,
        _=user,
        active_company=None,
    )

    assert result.status == "invalid"
    assert any("Invalid GSTIN" in e.message for e in result.errors)


def test_gstr1_validate_no_duplicate_false_flag_for_unique_numbers(db_session):
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="GS-DUP-1",
        when=datetime(2026, 7, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="GS-DUP-2",
        when=datetime(2026, 7, 11, 9, 0, 0),
        gst_rate=18,
        taxable_amount=2000,
        cgst_amount=180,
        sgst_amount=180,
        igst_amount=0,
    )
    db_session.flush()
    inv1 = db_session.query(Invoice).filter(Invoice.invoice_number == "GS-DUP-1").first()
    inv1.items[0].hsn_sac = "84713010"
    inv2 = db_session.query(Invoice).filter(Invoice.invoice_number == "GS-DUP-2").first()
    inv2.items[0].hsn_sac = "84713010"
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
        db=db_session,
        _=user,
        active_company=None,
    )

    assert result.status == "valid"
    # With unique numbers, no duplicate errors
    assert not any("Duplicate" in e.message for e in result.errors)


def test_gstr1_validate_detects_missing_hsn(db_session):
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="GS-NOHSN",
        when=datetime(2026, 8, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    db_session.commit()

    # Clear HSN to simulate missing HSN
    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "GS-NOHSN").first()
    if inv and inv.items:
        inv.items[0].hsn_sac = None
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 31),
        db=db_session,
        _=user,
        active_company=None,
    )

    assert result.status == "invalid"
    assert any("Missing HSN" in e.message for e in result.errors)


def test_gstr1_validate_detects_hsn_of_illegal_length(db_session):
    """5- and 7-digit HSN codes are rejected by the portal, so flag them here."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="GS-BADHSN",
        when=datetime(2026, 8, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    db_session.commit()

    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "GS-BADHSN").first()
    inv.items[0].hsn_sac = "8507600"  # 7 digits — a truncated 85076000
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 31),
        db=db_session,
        _=user,
        active_company=None,
    )

    assert result.status == "invalid"
    assert any("7 digits" in e.message for e in result.errors)


def test_gstr1_validate_detects_non_slab_gst_rate(db_session):
    """A rate of 17.99 lands in Table 12 verbatim and fails the upload."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="GS-BADRATE",
        when=datetime(2026, 8, 10, 9, 0, 0),
        gst_rate=17.99,
        taxable_amount=1000,
        cgst_amount=89.95,
        sgst_amount=89.95,
        igst_amount=0,
    )
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 31),
        db=db_session,
        _=user,
        active_company=None,
    )

    assert result.status == "invalid"
    assert any("not a GST slab" in e.message for e in result.errors)


def test_gstr1_json_export_blocked_on_malformed_hsn(db_session):
    """Export refuses rather than shipping a file the portal will drop."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="BADHSN-001",
        when=datetime(2027, 1, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "BADHSN-001").first()
    inv.items[0].hsn_sac = "99842"  # 5 digits
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        gstr1_export_json(
            from_date=date(2027, 1, 1),
            to_date=date(2027, 1, 31),
            db=db_session,
            _=user,
            active_company=_make_company(gst="29TESTT1234X1ZE"),
        )
    assert exc_info.value.status_code == 400
    assert "99842" in exc_info.value.detail


def test_gstr1_summary_classifies_b2b(db_session):
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="B2B-001",
        when=datetime(2026, 9, 10, 9, 0, 0),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    company = _make_company()

    result = gstr1_summary(
        from_date=date(2026, 9, 1),
        to_date=date(2026, 9, 30),
        db=db_session,
        _=user,
        active_company=company,
    )

    assert result.b2b.invoice_count == 1
    assert result.b2b.taxable_value == pytest.approx(5000.0)
    assert result.b2cl.invoice_count == 0
    assert result.doc_summary.total_invoices == 1


def test_gstr1_summary_classifies_b2cl(db_session):
    user, ledger = _seed_basics(db_session)
    ledger.gst = None
    db_session.flush()

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="B2CL-001",
        when=datetime(2026, 10, 10),
        gst_rate=18,
        taxable_amount=300000,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=54000,
    )
    db_session.flush()
    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "B2CL-001").first()
    inv.ledger_gst = None
    inv.place_of_supply = "10"
    db_session.commit()

    company = _make_company()

    result = gstr1_summary(
        from_date=date(2026, 10, 1),
        to_date=date(2026, 10, 31),
        db=db_session,
        _=user,
        active_company=company,
    )

    assert result.b2cl.invoice_count == 1
    assert result.b2cl.taxable_value == pytest.approx(300000.0)


def test_gstr1_export_json_structure(db_session):
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="JSON-001",
        when=datetime(2026, 11, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    company = _make_company()

    response = gstr1_export_json(
        from_date=date(2026, 11, 1),
        to_date=date(2026, 11, 30),
        db=db_session,
        _=user,
        active_company=company,
    )

    import json as _json
    content = response.body

    data = _json.loads(content)
    assert data["gstin"] == "29TESTT1234X1ZE"
    assert len(data["b2b"]) == 1
    assert data["b2b"][0]["ctin"] == "29ABCDE1234F1ZW"
    assert len(data["b2b"][0]["inv"]) == 1
    assert data["b2b"][0]["inv"][0]["inum"] == "JSON-001"
    assert "doc_issue" in data


def test_gstr1_export_json_consolidates_same_rate_items(db_session):
    """Multiple invoice items with the same GST rate must be consolidated
    into a single itms entry to avoid RET191117."""
    user, ledger = _seed_basics(db_session)

    total_taxable = 3000 + 2000
    total_cgst = 270 + 180
    total_sgst = 270 + 180
    invoice = Invoice(
        invoice_number="JSON-MULTI",
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
        voucher_type="sales",
        status="active",
        created_by=user.id,
        taxable_amount=total_taxable,
        total_tax_amount=total_cgst + total_sgst,
        cgst_amount=total_cgst,
        sgst_amount=total_sgst,
        igst_amount=0,
        total_amount=total_taxable + total_cgst + total_sgst,
        invoice_date=datetime(2026, 11, 10),
    )
    db_session.add(invoice)
    db_session.flush()

    for i, (taxable, cgst, sgst) in enumerate([
        (3000, 270, 270),
        (2000, 180, 180),
    ], start=1):
        db_session.add(InvoiceItem(
            invoice_id=invoice.id,
            product_id=i,
            hsn_sac="84713010",
            quantity=1,
            unit_price=taxable,
            gst_rate=18,
            taxable_amount=taxable,
            tax_amount=cgst + sgst,
            cgst_amount=cgst,
            sgst_amount=sgst,
            igst_amount=0,
            line_total=taxable + cgst + sgst,
        ))
    db_session.commit()

    company = _make_company()
    response = gstr1_export_json(
        from_date=date(2026, 11, 1),
        to_date=date(2026, 11, 30),
        db=db_session,
        _=user,
        active_company=company,
    )

    import json as _json
    data = _json.loads(response.body)
    inv = data["b2b"][0]["inv"][0]
    assert len(inv["itms"]) == 1
    det = inv["itms"][0]["itm_det"]
    assert det["rt"] == 18
    assert det["txval"] == round(total_taxable, 2)
    assert det["camt"] == round(total_cgst, 2)
    assert det["samt"] == round(total_sgst, 2)


def test_gstr1_export_json_keeps_different_rate_items_separate(db_session):
    """Items with different GST rates must remain separate itms entries."""
    user, ledger = _seed_basics(db_session)

    total_taxable = 1000 + 2000
    total_cgst = 60 + 280
    total_sgst = 60 + 280
    invoice = Invoice(
        invoice_number="JSON-RATES",
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
        voucher_type="sales",
        status="active",
        created_by=user.id,
        taxable_amount=total_taxable,
        total_tax_amount=total_cgst + total_sgst,
        cgst_amount=total_cgst,
        sgst_amount=total_sgst,
        igst_amount=0,
        total_amount=total_taxable + total_cgst + total_sgst,
        invoice_date=datetime(2026, 11, 11),
    )
    db_session.add(invoice)
    db_session.flush()

    db_session.add(InvoiceItem(
        invoice_id=invoice.id,
        product_id=1,
        hsn_sac="84713010",
        quantity=1,
        unit_price=1000,
        gst_rate=12,
        taxable_amount=1000,
        tax_amount=120,
        cgst_amount=60,
        sgst_amount=60,
        igst_amount=0,
        line_total=1120,
    ))
    db_session.add(InvoiceItem(
        invoice_id=invoice.id,
        product_id=2,
        hsn_sac="84713020",
        quantity=1,
        unit_price=2000,
        gst_rate=28,
        taxable_amount=2000,
        tax_amount=560,
        cgst_amount=280,
        sgst_amount=280,
        igst_amount=0,
        line_total=2560,
    ))
    db_session.commit()

    company = _make_company()
    response = gstr1_export_json(
        from_date=date(2026, 11, 1),
        to_date=date(2026, 11, 30),
        db=db_session,
        _=user,
        active_company=company,
    )

    import json as _json
    data = _json.loads(response.body)
    inv = data["b2b"][0]["inv"][0]
    assert len(inv["itms"]) == 2
    rates = {it["itm_det"]["rt"] for it in inv["itms"]}
    assert rates == {12, 28}


def test_gstr1_validate_warns_missing_place_of_supply(db_session):
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session,
        ledger,
        user,
        voucher_type="sales",
        invoice_number="GS-NOPOS",
        when=datetime(2026, 12, 10),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    db_session.flush()
    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "GS-NOPOS").first()
    inv.company_gst = None
    inv.items[0].hsn_sac = "84713010"
    db_session.commit()

    result = gstr1_validate(
        from_date=date(2026, 12, 1),
        to_date=date(2026, 12, 31),
        db=db_session,
        _=user,
        active_company=None,
    )

    assert any("Place of Supply" in e.message for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════════
#  Issue #376: GSTR-1 Fix Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_gstr1_json_export_blocked_when_company_has_no_gstin(db_session):
    """JSON export should raise HTTP 400 when company GSTIN is empty."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="NOGST-001",
        when=datetime(2027, 1, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    # Company with no GSTIN
    company = _make_company(gst="")

    with pytest.raises(HTTPException) as exc_info:
        gstr1_export_json(
            from_date=date(2027, 1, 1),
            to_date=date(2027, 1, 31),
            db=db_session,
            _=user,
            active_company=company,
        )
    assert exc_info.value.status_code == 400
    assert "Company GSTIN" in exc_info.value.detail


def test_gstr1_json_export_blocked_when_pos_is_00(db_session):
    """JSON export should raise HTTP 400 when company GSTIN is invalid (pos='00')."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="POS00-001",
        when=datetime(2027, 2, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    # Company with a GSTIN that has "00" as state code
    company = _make_company(gst="00AAAAA1234F1Z5")

    with pytest.raises(HTTPException) as exc_info:
        gstr1_export_json(
            from_date=date(2027, 2, 1),
            to_date=date(2027, 2, 28),
            db=db_session,
            _=user,
            active_company=company,
        )
    assert exc_info.value.status_code == 400
    assert "Place of Supply" in exc_info.value.detail


def test_gstr1_b2b_pos_uses_customer_state_code(db_session):
    """B2B JSON export should set POS to customer's state code (ctin[:2])."""
    user, ledger = _seed_basics(db_session)
    # Customer GSTIN starts with "27" (Maharashtra)
    ledger.gst = "27ABCDE1234F1Z0"
    db_session.flush()

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="B2BPOS-001",
        when=datetime(2027, 3, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=900,
    )
    db_session.commit()

    # Company GSTIN starts with "29" (Karnataka)
    company = _make_company(gst="29TESTT1234X1ZE")

    response = gstr1_export_json(
        from_date=date(2027, 3, 1),
        to_date=date(2027, 3, 31),
        db=db_session,
        _=user,
        active_company=company,
    )

    import json as _json
    data = _json.loads(response.body)
    assert len(data["b2b"]) == 1
    # POS should be "27" (customer's state), NOT "29" (company's state)
    assert data["b2b"][0]["ctin"] == "27ABCDE1234F1Z0"
    assert data["b2b"][0]["inv"][0]["pos"] == "27"


def test_gstr1_cdnr_ctin_from_invoice_id(db_session):
    """CDNR section ctin should be correctly looked up from the original invoice."""
    user, ledger = _seed_basics(db_session)

    sales_invoice = _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="CDNR-INV-001",
        when=datetime(2027, 4, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    # Create credit note referencing the invoice
    _add_credit_note_item(
        db_session, user, ledger, sales_invoice,
        number="CDNR-CN-001",
        when=datetime(2027, 4, 15),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    db_session.commit()

    company = _make_company(gst="29TESTT1234X1ZE")

    response = gstr1_export_json(
        from_date=date(2027, 4, 1),
        to_date=date(2027, 4, 30),
        db=db_session,
        _=user,
        active_company=company,
    )

    import json as _json
    data = _json.loads(response.body)
    # CDNR is grouped by customer GSTIN, with notes under "nt".
    assert len(data["cdnr"]) == 1
    assert data["cdnr"][0]["ctin"] == "29ABCDE1234F1ZW"
    assert len(data["cdnr"][0]["nt"]) == 1
    assert data["cdnr"][0]["nt"][0]["nt_num"] == "CDNR-CN-001"
    assert data["cdnr"][0]["nt"][0]["pos"] == "29"


def test_gstr1_discount_credit_note_is_reported_as_a_credit_note(db_session):
    """A discount note still lowers the liability, so it is ntty "C", not "D"."""
    user, ledger = _seed_basics(db_session)

    sales_invoice = _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="DISC-INV-001",
        when=datetime(2027, 4, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    _add_credit_note_item(
        db_session, user, ledger, sales_invoice,
        number="DISC-CN-001",
        when=datetime(2027, 4, 15),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
        credit_note_type="discount",
    )
    db_session.commit()

    response = gstr1_export_json(
        from_date=date(2027, 4, 1),
        to_date=date(2027, 4, 30),
        db=db_session,
        _=user,
        active_company=_make_company(gst="29TESTT1234X1ZE"),
    )

    import json as _json
    data = _json.loads(response.body)
    note = data["cdnr"][0]["nt"][0]
    assert note["nt_num"] == "DISC-CN-001"
    assert note["ntty"] == "C"
    assert note["itms"][0]["itm_det"]["camt"] == 90.0
    assert note["itms"][0]["itm_det"]["samt"] == 90.0

    doc_nums = [d["doc_num"] for d in data["doc_issue"]["doc_det"]]
    assert 4 not in doc_nums  # no debit note series is ever issued
    cn_doc = next(d for d in data["doc_issue"]["doc_det"] if d["doc_num"] == 5)
    assert cn_doc["docs"][0]["from"] == "DISC-CN-001"
    assert cn_doc["docs"][0]["totnum"] == 1


def test_gstr1_csv_export_blocked_when_company_has_no_gstin(db_session):
    """CSV export should raise HTTP 400 when company GSTIN is empty."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="CSVNOGST-001",
        when=datetime(2027, 5, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    company = _make_company(gst="")

    with pytest.raises(HTTPException) as exc_info:
        gstr1_export_csv(
            from_date=date(2027, 5, 1),
            to_date=date(2027, 5, 31),
            db=db_session,
            _=user,
            active_company=company,
        )
    assert exc_info.value.status_code == 400
    assert "Company GSTIN" in exc_info.value.detail


def _export_json_data(db_session, user, company, from_date, to_date):
    import json as _json

    response = gstr1_export_json(
        from_date=from_date,
        to_date=to_date,
        db=db_session,
        _=user,
        active_company=company,
    )
    return _json.loads(response.body)


def test_gstr1_b2cs_uses_gstn_schema_fields(db_session):
    """B2CS entries must use sply_ty/pos/typ/rt, not the legacy ty/crt/srt fields."""
    user, ledger = _seed_basics(db_session)
    ledger.gst = None  # B2C — no customer GSTIN
    db_session.flush()

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="B2CS-001",
        when=datetime(2026, 4, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()
    company = _make_company(gst="29TESTT1234X1ZE")

    data = _export_json_data(db_session, user, company, date(2026, 4, 1), date(2026, 4, 30))

    assert len(data["b2cs"]) == 1
    entry = data["b2cs"][0]
    assert entry["sply_ty"] == "INTRA"
    assert entry["pos"] == "29"
    assert entry["typ"] == "OE"
    assert entry["rt"] == 18
    assert entry["txval"] == 5000.0
    assert entry["camt"] == 450.0
    assert entry["samt"] == 450.0
    # Legacy / invalid field names must be gone.
    assert "ty" not in entry
    assert "crt" not in entry
    assert "srt" not in entry
    assert "irt" not in entry
    assert "hsn_sc" not in entry


def test_gstr1_doc_issue_uses_nature_code_and_ranges(db_session):
    """doc_issue must use nature-of-document codes with docs ranges, not doc_typ labels."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="DOC-001",
        when=datetime(2026, 4, 5),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="DOC-002",
        when=datetime(2026, 4, 9),
        gst_rate=18,
        taxable_amount=3000,
        cgst_amount=270,
        sgst_amount=270,
        igst_amount=0,
    )
    db_session.commit()
    company = _make_company(gst="29TESTT1234X1ZE")

    data = _export_json_data(db_session, user, company, date(2026, 4, 1), date(2026, 4, 30))

    doc_det = data["doc_issue"]["doc_det"]
    inv_doc = next(d for d in doc_det if d["doc_num"] == 1)
    assert "doc_typ" not in inv_doc
    rng = inv_doc["docs"][0]
    assert rng["from"] == "DOC-001"
    assert rng["to"] == "DOC-002"
    assert rng["totnum"] == 2
    assert rng["net_issue"] == 2


@pytest.mark.parametrize(
    ("numbers", "first", "last"),
    [
        # Padded counter that outgrows its pad: text order would give 1000..999.
        (["INV-2026-998", "INV-2026-1001", "INV-2026-999", "INV-2026-1000"], "INV-2026-998", "INV-2026-1001"),
        (["S-98", "S-100", "S-99"], "S-98", "S-100"),
        (["INV-10", "INV-9"], "INV-9", "INV-10"),
        # The financial-year digits must not confuse the order of the counter.
        (["INV-2026-27-010", "INV-2026-27-009", "INV-2025-26-999"], "INV-2025-26-999", "INV-2026-27-010"),
        (["A/10", "A/2", "a/1"], "a/1", "A/10"),
    ],
)
def test_gstr1_doc_range_sorts_numbers_in_issue_order(numbers, first, last):
    rng = _doc_range(numbers)
    assert rng["from"] == first
    assert rng["to"] == last
    assert rng["totnum"] == len(numbers)
    assert rng["net_issue"] == len(numbers)


def test_gstr1_doc_range_single_empty_and_null_numbers():
    rng = _doc_range(["INV-001", None, ""], num=5)
    assert rng == {"num": 5, "from": "INV-001", "to": "INV-001", "totnum": 1, "cancel": 0, "net_issue": 1}
    assert _doc_range([]) is None
    assert _doc_range([None, ""]) is None


def test_gstr1_doc_issue_range_survives_counter_outgrowing_pad(db_session):
    """Table 13 from/to follow issue order once a padded counter reaches 1000."""
    user, ledger = _seed_basics(db_session)
    for day, number in enumerate(["INV-998", "INV-999", "INV-1000", "INV-1001"], start=1):
        _add_invoice_with_item(
            db_session, ledger, user,
            voucher_type="sales",
            invoice_number=number,
            when=datetime(2026, 4, day),
            gst_rate=18,
            taxable_amount=1000,
            cgst_amount=90,
            sgst_amount=90,
            igst_amount=0,
        )
    db_session.commit()
    company = _make_company(gst="29TESTT1234X1ZE")

    data = _export_json_data(db_session, user, company, date(2026, 4, 1), date(2026, 4, 30))

    inv_doc = next(d for d in data["doc_issue"]["doc_det"] if d["doc_num"] == 1)
    rng = inv_doc["docs"][0]
    assert rng["from"] == "INV-998"
    assert rng["to"] == "INV-1001"
    assert rng["totnum"] == 4


def test_gstr1_doc_issue_keeps_b2b_and_b2c_in_same_invoice_series(db_session):
    """Table 13 must not split one invoice series by recipient registration."""
    user, ledger = _seed_basics(db_session)
    company = _make_company(gst="29TESTT1234X1ZE")

    # B2B invoice — ledger has GSTIN
    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="INV-2026-27-068",
        when=datetime(2026, 6, 14),
        gst_rate=18,
        taxable_amount=10000,
        cgst_amount=900,
        sgst_amount=900,
        igst_amount=0,
    )

    # B2C invoice — no GSTIN on ledger; use a fresh Buyer without gst
    b2c_ledger = Buyer(
        name="B2C Customer",
        address="Some Street",
        gst=None,
        phone_number="8888888888",
    )
    db_session.add(b2c_ledger)
    db_session.commit()
    db_session.refresh(b2c_ledger)

    _add_invoice_with_item(
        db_session, b2c_ledger, user,
        voucher_type="sales",
        invoice_number="INV-2026-27-069",
        when=datetime(2026, 6, 15),
        gst_rate=18,
        taxable_amount=216,
        cgst_amount=19,
        sgst_amount=19,
        igst_amount=0,
    )

    # Another B2B invoice after the B2C invoice makes a registration-based split
    # produce overlapping 068-070 and 069-069 ranges.
    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="INV-2026-27-070",
        when=datetime(2026, 6, 16),
        gst_rate=18,
        taxable_amount=2000,
        cgst_amount=180,
        sgst_amount=180,
        igst_amount=0,
    )
    db_session.commit()

    data = _export_json_data(db_session, user, company, date(2026, 6, 1), date(2026, 6, 30))

    doc_det = data["doc_issue"]["doc_det"]
    inv_doc = next(d for d in doc_det if d["doc_num"] == 1)
    docs = inv_doc["docs"]

    assert len(docs) == 1
    invoice_series = docs[0]
    assert invoice_series["num"] == 1
    assert invoice_series["from"] == "INV-2026-27-068"
    assert invoice_series["to"] == "INV-2026-27-070"
    assert invoice_series["totnum"] == 3
    assert invoice_series["cancel"] == 0
    assert invoice_series["net_issue"] == 3


def test_gstr1_hsn_section_splits_b2b_with_rate(db_session):
    """HSN summary must expose hsn_b2b rows with hsn_sc first and a rate."""
    user, ledger = _seed_basics(db_session)

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="HSN-001",
        when=datetime(2026, 4, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()
    company = _make_company(gst="29TESTT1234X1ZE")

    data = _export_json_data(db_session, user, company, date(2026, 4, 1), date(2026, 4, 30))

    assert "hsn_b2b" in data["hsn"]
    row = data["hsn"]["hsn_b2b"][0]
    assert list(row.keys())[0] == "hsn_sc"
    assert row["hsn_sc"] == "84713010"
    assert row["rt"] == 18
    assert row["txval"] == 5000.0


def test_gstr1_hsn_row_uses_product_unit_and_trimmed_desc(db_session):
    """UQC comes from the product unit; desc is one line of at most 30 chars."""
    user, ledger = _seed_basics(db_session)

    product = Product(name="Copper wire", sku="CW-1", price=100, gst_rate=18, unit="Kg")
    db_session.add(product)
    db_session.commit()

    invoice = _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="UQC-001",
        when=datetime(2027, 5, 10),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    invoice.items[0].product_id = product.id
    invoice.items[0].description = "ZAD04NV203095, ZAD04NV705458,\n ZAD04NV203097"
    db_session.commit()

    response = gstr1_export_json(
        from_date=date(2027, 5, 1),
        to_date=date(2027, 5, 31),
        db=db_session,
        _=user,
        active_company=_make_company(gst="29TESTT1234X1ZE"),
    )

    import json as _json
    row = _json.loads(response.body)["hsn"]["hsn_b2b"][0]
    assert row["uqc"] == "KGS"
    assert len(row["desc"]) <= 30
    assert "\n" not in row["desc"]
    assert row["desc"] == "ZAD04NV203095, ZAD04NV705458,"


def test_gstr1_hsn_desc_is_populated(db_session):
    """HSN rows must include a non-empty 'desc' field (mandatory per GSTN portal schema).

    The portal rejects exports where desc is absent or empty. We use the first
    non-empty InvoiceItem.description for the HSN group; if none is set we fall
    back to the HSN code itself so the field is always present and non-empty.
    """
    user, ledger = _seed_basics(db_session)
    company = _make_company(gst="29TESTT1234X1ZE")

    invoice = _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="DESC-001",
        when=datetime(2026, 4, 5),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    # Patch the item with a description after creation.
    db_session.query(InvoiceItem).filter_by(invoice_id=invoice.id).update({"description": "Laptop Computer"})
    db_session.commit()

    data = _export_json_data(db_session, user, company, date(2026, 4, 1), date(2026, 4, 30))

    row = data["hsn"]["hsn_b2b"][0]
    # desc must be present and non-empty
    assert "desc" in row, "HSN row missing mandatory 'desc' field"
    assert row["desc"], "HSN row 'desc' must not be empty"
    assert row["desc"] == "Laptop Computer"


def test_gstr1_hsn_desc_falls_back_to_hsn_code_when_no_description(db_session):
    """When no item description is set, desc falls back to the HSN code itself.

    This ensures the field is always present and non-empty even for invoices
    where the item description was left blank.
    """
    user, ledger = _seed_basics(db_session)
    company = _make_company(gst="29TESTT1234X1ZE")

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="DESC-002",
        when=datetime(2026, 4, 6),
        gst_rate=18,
        taxable_amount=3000,
        cgst_amount=270,
        sgst_amount=270,
        igst_amount=0,
    )
    # No description set on item — helper leaves it NULL.
    db_session.commit()

    data = _export_json_data(db_session, user, company, date(2026, 4, 1), date(2026, 4, 30))

    row = data["hsn"]["hsn_b2b"][0]
    assert "desc" in row, "HSN row missing mandatory 'desc' field"
    assert row["desc"], "HSN row 'desc' must not be empty even when item description is NULL"
    # Fallback: desc equals the HSN code
    assert row["desc"] == row["hsn_sc"]


# ─────────────────────────────────────────────────────────────────────────────
# Notes received from suppliers stay out of GSTR-1
#
# GSTR-1 is a return of outward supplies. A note against a purchase is the
# supplier's own credit note, which they declare in their GSTR-1 and which
# reaches us through GSTR-2B as a reduction of input credit. Filing it here
# would lower our output liability instead, and declare in Table 13 a document
# we never issued.
# ─────────────────────────────────────────────────────────────────────────────

def _seed_one_of_each_note(db_session):
    """A sales note and a supplier's note in the same period."""
    user, ledger = _seed_basics(db_session)

    sales_invoice = _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="MIX-INV-001",
        when=datetime(2027, 6, 5),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    purchase_invoice = _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="purchase",
        invoice_number="MIX-PINV-001",
        when=datetime(2027, 6, 6),
        gst_rate=18,
        taxable_amount=3000,
        cgst_amount=270,
        sgst_amount=270,
        igst_amount=0,
    )
    db_session.commit()

    _add_credit_note_item(
        db_session, user, ledger, sales_invoice,
        number="MIX-CN-001",
        when=datetime(2027, 6, 10),
        gst_rate=18,
        taxable_amount=1000,
        cgst_amount=90,
        sgst_amount=90,
        igst_amount=0,
    )
    _add_credit_note_item(
        db_session, user, ledger, purchase_invoice,
        number="MIX-DN-001",
        when=datetime(2027, 6, 11),
        gst_rate=18,
        taxable_amount=500,
        cgst_amount=45,
        sgst_amount=45,
        igst_amount=0,
        direction="inward",
    )
    db_session.commit()
    return user, ledger


def test_gstr1_summary_excludes_notes_received_from_suppliers(db_session):
    user, _ = _seed_one_of_each_note(db_session)

    result = gstr1_summary(
        from_date=date(2027, 6, 1),
        to_date=date(2027, 6, 30),
        db=db_session,
        _=user,
        active_company=_make_company(gst="29TESTT1234X1ZE"),
    )

    # Only the outward note counts: 1000 taxable, not 1500.
    assert result.credit_notes.invoice_count == 1
    assert result.credit_notes.taxable_value == 1000
    assert result.credit_notes.cgst == 90
    assert result.doc_summary.total_credit_notes == 1
    assert result.doc_summary.total_debit_notes == 0


def test_gstr1_export_json_excludes_supplier_notes_from_cdnr(db_session):
    user, _ = _seed_one_of_each_note(db_session)

    response = gstr1_export_json(
        from_date=date(2027, 6, 1),
        to_date=date(2027, 6, 30),
        db=db_session,
        _=user,
        active_company=_make_company(gst="29TESTT1234X1ZE"),
    )

    import json as _json
    data = _json.loads(response.body)

    note_numbers = [
        note["nt_num"]
        for group in data.get("cdnr", [])
        for note in group["nt"]
    ] + [note["nt_num"] for note in data.get("cdnur", [])]
    assert note_numbers == ["MIX-CN-001"]


def test_gstr1_doc_issue_excludes_the_debit_note_series(db_session):
    """Table 13 declares a from/to range, so a DN number inside it would be a lie."""
    user, _ = _seed_one_of_each_note(db_session)

    response = gstr1_export_json(
        from_date=date(2027, 6, 1),
        to_date=date(2027, 6, 30),
        db=db_session,
        _=user,
        active_company=_make_company(gst="29TESTT1234X1ZE"),
    )

    import json as _json
    data = _json.loads(response.body)

    doc_det = data["doc_issue"]["doc_det"]
    assert 4 not in [d["doc_num"] for d in doc_det]  # still no debit note series
    cn_doc = next(d for d in doc_det if d["doc_num"] == 5)
    assert cn_doc["docs"][0]["from"] == "MIX-CN-001"
    assert cn_doc["docs"][0]["to"] == "MIX-CN-001"
    assert cn_doc["docs"][0]["totnum"] == 1
    assert cn_doc["docs"][0]["net_issue"] == 1


def test_supplier_note_still_reverses_input_credit(db_session):
    """It leaves GSTR-1 alone, but it must still cut the ITC we claimed."""
    user, _ = _seed_one_of_each_note(db_session)

    result = get_tax_ledger(
        from_date=date(2027, 6, 1),
        to_date=date(2027, 6, 30),
        voucher_type=None,
        gst_rate=None,
        db=db_session,
        _=user,
    )

    # Purchase brought in 540 of credit; the supplier's note takes back 90.
    assert result.liability.input_credit == 450.0
    # Output tax is the sale's 900 less the 180 our own note reversed.
    assert result.liability.output_tax == 720.0


# ═══════════════════════════════════════════════════════════════════════════
#  GSTR-1: place of supply, B2CL, unregistered notes, periods, Table 12/13
# ═══════════════════════════════════════════════════════════════════════════

OCT_2026 = (date(2026, 10, 1), date(2026, 10, 31))


def _read_stream(response) -> bytes:
    async def collect():
        return b"".join([chunk async for chunk in response.body_iterator])

    return asyncio.run(collect())


def _unregistered(db_session):
    """A user and a ledger with no GSTIN, under a Karnataka (29) company."""
    user, ledger = _seed_basics(db_session)
    ledger.gst = None
    db_session.flush()
    return user, ledger, _make_company(gst="29TESTT1234X1ZE")


def _b2c_sale(db_session, ledger, user, number, taxable, *, pos=None, when=datetime(2026, 10, 5), rate=18):
    """A sale to a buyer with no GSTIN, taxed the way its place of supply says."""
    tax = round(taxable * rate / 100, 2)
    interstate = pos is not None and pos != "29"
    invoice = _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number=number,
        when=when,
        gst_rate=rate,
        taxable_amount=taxable,
        cgst_amount=0 if interstate else tax / 2,
        sgst_amount=0 if interstate else tax / 2,
        igst_amount=tax if interstate else 0,
    )
    invoice.ledger_gst = None
    invoice.place_of_supply = pos
    db_session.commit()
    return invoice


def _b2c_note(db_session, ledger, user, invoice, number, taxable, *, when=datetime(2026, 10, 20), rate=18, **extra):
    tax = round(taxable * rate / 100, 2)
    interstate = bool(float(invoice.igst_amount or 0))
    note = _add_credit_note_item(
        db_session, user, ledger, invoice,
        number=number,
        when=when,
        gst_rate=rate,
        taxable_amount=taxable,
        cgst_amount=0 if interstate else tax / 2,
        sgst_amount=0 if interstate else tax / 2,
        igst_amount=tax if interstate else 0,
        **extra,
    )
    db_session.commit()
    return note


def test_gstr1_interstate_sale_below_limit_is_b2cs_under_the_buyers_state(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 50000, pos="10")

    data = _export_json_data(db_session, user, company, *OCT_2026)

    assert "b2cl" not in data
    row = data["b2cs"][0]
    assert (row["sply_ty"], row["pos"], row["iamt"], row["camt"]) == ("INTER", "10", 9000.0, 0.0)


def test_gstr1_b2cl_is_above_one_lakh_of_invoice_value_and_grouped_by_state(db_session):
    user, ledger, company = _unregistered(db_session)
    # 90,000 taxable is 1,06,200 invoice value: over the limit, which is on value.
    _b2c_sale(db_session, ledger, user, "A-1", 90000, pos="10")

    data = _export_json_data(db_session, user, company, *OCT_2026)

    assert "b2cs" not in data
    assert data["b2cl"][0]["pos"] == "10"
    invoice = data["b2cl"][0]["inv"][0]
    assert invoice["inum"] == "A-1"
    assert invoice["itms"][0]["itm_det"] == {"rt": 18.0, "txval": 90000.0, "iamt": 16200.0, "csamt": 0.0}


def test_gstr1_large_sale_inside_the_state_is_b2cs_not_b2cl(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 300000)

    data = _export_json_data(db_session, user, company, *OCT_2026)

    assert "b2cl" not in data
    assert (data["b2cs"][0]["sply_ty"], data["b2cs"][0]["pos"]) == ("INTRA", "29")


def test_gstr1_b2cl_limit_was_two_and_a_half_lakh_before_august_2024(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 150000, pos="10", when=datetime(2024, 7, 10))
    _b2c_sale(db_session, ledger, user, "B-1", 150000, pos="10", when=datetime(2024, 8, 10))

    july = _export_json_data(db_session, user, company, date(2024, 7, 1), date(2024, 7, 31))
    august = _export_json_data(db_session, user, company, date(2024, 8, 1), date(2024, 8, 31))

    assert "b2cl" not in july
    assert "b2cs" not in august


def test_gstr1_summary_and_csv_agree_with_the_json_on_b2cl(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 300000)
    _b2c_sale(db_session, ledger, user, "B-1", 90000, pos="10")

    summary = gstr1_summary(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)
    assert (summary.b2cl.invoice_count, summary.b2cs.invoice_count) == (1, 1)

    response = gstr1_export_csv(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)
    rows = {row["Invoice Number"]: row for row in csv.DictReader(StringIO(_read_stream(response).decode("utf-8-sig")))}
    assert (rows["A-1"]["Section"], rows["A-1"]["Place of Supply"]) == ("B2CS", "29")
    assert (rows["B-1"]["Section"], rows["B-1"]["Place of Supply"]) == ("B2CL", "10")


def test_gstr1_registered_buyer_keeps_a_chosen_place_of_supply(db_session):
    user, ledger = _seed_basics(db_session)
    invoice = _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="A-1", when=datetime(2026, 10, 5),
        gst_rate=18, taxable_amount=1000, cgst_amount=0, sgst_amount=0, igst_amount=180,
    )
    invoice.place_of_supply = "27"
    db_session.commit()

    data = _export_json_data(db_session, user, _make_company(gst="29TESTT1234X1ZE"), *OCT_2026)

    assert data["b2b"][0]["ctin"] == ledger.gst
    assert data["b2b"][0]["inv"][0]["pos"] == "27"


def test_gstr1_small_unregistered_note_reduces_b2cs_instead_of_cdnur(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 50000)
    _b2c_note(db_session, ledger, user, invoice, "CN-1", 10000)

    data = _export_json_data(db_session, user, company, *OCT_2026)

    assert "cdnur" not in data
    row = data["b2cs"][0]
    assert (row["txval"], row["camt"], row["samt"]) == (40000.0, 3600.0, 3600.0)


def test_gstr1_note_against_a_b2cl_invoice_goes_to_cdnur_as_b2cl(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 200000, pos="10", when=datetime(2026, 9, 5))
    # The note itself is small, but its invoice was filed on its own in Table 5.
    _b2c_note(db_session, ledger, user, invoice, "CN-1", 1000)

    data = _export_json_data(db_session, user, company, *OCT_2026)

    assert "b2cs" not in data
    note = data["cdnur"][0]
    assert (note["typ"], note["pos"], note["nt_num"]) == ("B2CL", "10", "CN-1")
    assert note["itms"][0]["itm_det"] == {"rt": 18.0, "txval": 1000.0, "iamt": 180.0, "csamt": 0.0}


def test_gstr1_cdnur_never_has_a_b2cs_type(db_session):
    user, ledger, company = _unregistered(db_session)
    small = _b2c_sale(db_session, ledger, user, "A-1", 1000, pos="10")
    large = _b2c_sale(db_session, ledger, user, "A-2", 200000, pos="10")
    _b2c_note(db_session, ledger, user, small, "CN-1", 500)
    _b2c_note(db_session, ledger, user, large, "CN-2", 500)

    data = _export_json_data(db_session, user, company, *OCT_2026)

    assert {note["typ"] for note in data["cdnur"]} == {"B2CL"}
    assert [note["nt_num"] for note in data["cdnur"]] == ["CN-2"]


def test_gstr1_cdnr_pos_follows_the_invoice(db_session):
    user, ledger = _seed_basics(db_session)
    invoice = _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="A-1", when=datetime(2026, 10, 5),
        gst_rate=18, taxable_amount=1000, cgst_amount=0, sgst_amount=0, igst_amount=180,
    )
    invoice.place_of_supply = "27"
    _add_credit_note_item(
        db_session, user, ledger, invoice, number="CN-1", when=datetime(2026, 10, 6),
        gst_rate=18, taxable_amount=100, cgst_amount=0, sgst_amount=0, igst_amount=18,
    )
    db_session.commit()

    data = _export_json_data(db_session, user, _make_company(gst="29TESTT1234X1ZE"), *OCT_2026)

    assert data["cdnr"][0]["nt"][0]["pos"] == "27"


def test_gstr1_validate_accepts_the_40_percent_rate(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 1000, rate=40)

    result = gstr1_validate(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)

    assert not [e for e in result.errors if e.severity == "error"]


def test_gstr1_export_blocks_a_rate_validation_rejects(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 1000, rate=17.99)

    with pytest.raises(HTTPException) as exc:
        _export_json_data(db_session, user, company, *OCT_2026)

    assert exc.value.status_code == 400
    assert "17.99%" in exc.value.detail


@pytest.mark.parametrize(
    ("from_date", "to_date", "fp"),
    [
        (date(2026, 10, 1), date(2026, 10, 31), "102026"),
        (date(2024, 2, 1), date(2024, 2, 29), "022024"),
        (date(2026, 4, 1), date(2026, 6, 30), "062026"),
        (date(2026, 10, 1), date(2026, 12, 31), "122026"),
        (date(2027, 1, 1), date(2027, 3, 31), "032027"),
    ],
)
def test_gstr1_return_period_is_the_last_month_covered(db_session, from_date, to_date, fp):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 1000, when=datetime.combine(from_date, datetime.min.time()))

    assert _export_json_data(db_session, user, company, from_date, to_date)["fp"] == fp


@pytest.mark.parametrize(
    ("from_date", "to_date"),
    [
        (date(2026, 4, 1), date(2027, 3, 31)),   # a financial year
        (date(2026, 10, 1), date(2026, 10, 15)), # part of a month
        (date(2026, 10, 2), date(2026, 10, 31)),
        (date(2026, 5, 1), date(2026, 7, 31)),   # three months, not a GST quarter
        (date(2026, 4, 1), date(2026, 5, 31)),   # two months
        (date(2026, 12, 1), date(2027, 1, 31)),  # across a year end
    ],
)
def test_gstr1_range_that_is_not_a_return_period_is_refused(db_session, from_date, to_date):
    user, ledger, company = _unregistered(db_session)

    with pytest.raises(HTTPException) as exc:
        _export_json_data(db_session, user, company, from_date, to_date)
    assert exc.value.status_code == 400
    assert "not a return period" in exc.value.detail

    result = gstr1_validate(from_date=from_date, to_date=to_date, db=db_session, _=user, active_company=company)
    assert result.status == "invalid"
    assert result.errors[0].field == "Period"
    assert result.invalid_invoices == 0


@pytest.mark.parametrize("number", ["INVOICE-2026-27-00001", "INV_001", "INV.001", "INV 001"])
def test_gstr1_invoice_number_the_portal_refuses_is_blocked(db_session, number):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, number, 1000)

    with pytest.raises(HTTPException) as exc:
        _export_json_data(db_session, user, company, *OCT_2026)
    assert "16 characters" in exc.value.detail

    result = gstr1_validate(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)
    assert result.status == "invalid"
    assert any(e.field == "Invoice Number" for e in result.errors)


def test_gstr1_credit_note_number_the_portal_refuses_is_blocked(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 1000)
    _b2c_note(db_session, ledger, user, invoice, "CREDIT_NOTE_2026_0001", 100)

    with pytest.raises(HTTPException) as exc:
        _export_json_data(db_session, user, company, *OCT_2026)
    assert "Credit note CREDIT_NOTE_2026_0001" in exc.value.detail


def test_gstr1_table_13_counts_a_cancelled_invoice(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "E-1", 1000)
    cancelled = _b2c_sale(db_session, ledger, user, "E-2", 1000)
    cancelled.status = "cancelled"
    _b2c_sale(db_session, ledger, user, "E-3", 1000)
    db_session.commit()

    data = _export_json_data(db_session, user, company, *OCT_2026)

    row = data["doc_issue"]["doc_det"][0]["docs"][0]
    assert row == {"num": 1, "from": "E-1", "to": "E-3", "totnum": 3, "cancel": 1, "net_issue": 2}


def test_gstr1_table_13_has_one_row_per_number_series(db_session):
    user, ledger, company = _unregistered(db_session)
    for number in ("INV-1", "INV-2", "SHOP-500"):
        _b2c_sale(db_session, ledger, user, number, 1000)

    data = _export_json_data(db_session, user, company, *OCT_2026)

    docs = data["doc_issue"]["doc_det"][0]["docs"]
    assert [(d["num"], d["from"], d["to"], d["totnum"]) for d in docs] == [
        (1, "INV-1", "INV-2", 2),
        (2, "SHOP-500", "SHOP-500", 1),
    ]


def test_gstr1_table_12_is_net_of_a_return(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 50000)
    invoice.items[0].quantity = 5
    _b2c_note(db_session, ledger, user, invoice, "CN-1", 10000)

    data = _export_json_data(db_session, user, company, *OCT_2026)

    row = data["hsn"]["hsn_b2c"][0]
    assert (row["qty"], row["txval"], row["camt"], row["samt"]) == (4.0, 40000.0, 3600.0, 3600.0)

    summary = gstr1_summary(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)
    assert summary.hsn_summary[0].taxable_value == pytest.approx(40000.0)
    assert summary.hsn_summary[0].quantity == pytest.approx(4.0)


def test_gstr1_table_12_discount_note_lowers_value_but_not_quantity(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 50000)
    invoice.items[0].quantity = 5
    _b2c_note(db_session, ledger, user, invoice, "CN-1", 10000, credit_note_type="discount")

    row = _export_json_data(db_session, user, company, *OCT_2026)["hsn"]["hsn_b2c"][0]

    assert (row["qty"], row["txval"]) == (5.0, 40000.0)


def test_gstr1_table_12_nets_a_note_on_last_months_invoice_into_its_buyer_list(db_session):
    user, ledger = _seed_basics(db_session)
    invoice = _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="A-1", when=datetime(2026, 9, 5),
        gst_rate=18, taxable_amount=1000, cgst_amount=90, sgst_amount=90, igst_amount=0,
    )
    _add_credit_note_item(
        db_session, user, ledger, invoice, number="CN-1", when=datetime(2026, 10, 6),
        gst_rate=18, taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0,
    )
    db_session.commit()

    data = _export_json_data(db_session, user, _make_company(gst="29TESTT1234X1ZE"), *OCT_2026)

    assert "hsn_b2c" not in data["hsn"]
    assert data["hsn"]["hsn_b2b"][0]["txval"] == -100.0


def test_gstr1_export_writes_no_blank_sections(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 1000)

    data = _export_json_data(db_session, user, company, *OCT_2026)

    assert "hsn_b2b" not in data["hsn"]
    assert data["hsn"]["hsn_b2c"]
    assert set(data) == {"gstin", "fp", "b2cs", "hsn", "doc_issue"}
    # Zero is a value, not a blank.
    assert data["b2cs"][0]["iamt"] == 0.0


def test_gstr1_note_is_dated_by_its_credit_note_date_not_created_at(db_session):
    user, ledger, company = _unregistered(db_session)
    large = _b2c_sale(db_session, ledger, user, "A-2", 200000, pos="10", when=datetime(2026, 10, 5))
    note = _b2c_note(db_session, ledger, user, large, "CN-1", 100, when=datetime(2026, 11, 2, 9, 0))
    note.credit_note_date = datetime(2026, 10, 31)
    db_session.commit()

    october = _export_json_data(db_session, user, company, *OCT_2026)
    november = _export_json_data(db_session, user, company, date(2026, 11, 1), date(2026, 11, 30))

    assert october["cdnur"][0]["nt_dt"] == "31-10-2026"
    assert "cdnur" not in november


def test_tax_ledger_dates_a_note_by_its_credit_note_date(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 1000, when=datetime(2026, 10, 5))
    note = _b2c_note(db_session, ledger, user, invoice, "CN-1", 100, when=datetime(2026, 11, 2, 9, 0))
    note.credit_note_date = datetime(2026, 10, 31)
    db_session.commit()

    result = get_tax_ledger(
        from_date=OCT_2026[0], to_date=OCT_2026[1], voucher_type=None, gst_rate=None,
        db=db_session, _=user, active_company=company,
    )

    assert "CN-1" in {entry.reference_number for entry in result.entries}


def test_gstr1_tax_that_does_not_match_the_place_of_supply_is_blocked(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 200000)  # CGST/SGST
    invoice.place_of_supply = "10"
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _export_json_data(db_session, user, company, *OCT_2026)
    assert "CGST/SGST charged" in exc.value.detail

    result = gstr1_validate(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)
    assert any(e.field == "Place of Supply" for e in result.errors)


def test_gstr1_igst_on_the_sellers_own_state_is_blocked(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 1000, pos="10")  # IGST
    invoice.place_of_supply = "29"
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _export_json_data(db_session, user, company, *OCT_2026)
    assert "IGST charged" in exc.value.detail


def test_gstr1_export_blocks_what_validate_blocks(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 1000)
    invoice.total_tax_amount = 999
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _export_json_data(db_session, user, company, *OCT_2026)
    assert "Item tax sum" in exc.value.detail


def test_gstr1_sale_to_your_own_gstin_is_blocked(db_session):
    user, ledger = _seed_basics(db_session)
    company = _make_company(gst=ledger.gst)
    _add_invoice_with_item(
        db_session, ledger, user, voucher_type="sales", invoice_number="A-1", when=datetime(2026, 10, 5),
        gst_rate=18, taxable_amount=1000, cgst_amount=90, sgst_amount=90, igst_amount=0,
    )
    db_session.commit()

    result = gstr1_validate(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)

    assert any("your own" in e.message for e in result.errors)


def test_gstr1_cancelled_number_gstr1_refuses_stays_out_of_table_13_with_a_warning(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "E-1", 1000)
    cancelled = _b2c_sale(db_session, ledger, user, "OLD_NUMBER_2026_0001", 1000)
    cancelled.status = "cancelled"
    db_session.commit()

    data = _export_json_data(db_session, user, company, *OCT_2026)
    assert "OLD_NUMBER" not in str(data["doc_issue"])

    result = gstr1_validate(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)
    assert result.status == "valid"
    assert any(e.invoice_number == "OLD_NUMBER_2026_0001" and e.severity == "warning" for e in result.errors)


@pytest.mark.parametrize(
    ("numbers", "ranges"),
    [
        # A year after the counter does not make every invoice its own series.
        (["INV/0001/26-27", "INV/0002/26-27", "INV/0003/26-27"], [("INV/0001/26-27", "INV/0003/26-27", 3)]),
        (["01/2026-27", "02/2026-27"], [("01/2026-27", "02/2026-27", 2)]),
        # Two years apart are two series, however the sort interleaves them.
        (
            ["INV/0001/26-27", "INV/0001/27-28", "INV/0002/26-27"],
            [("INV/0001/26-27", "INV/0002/26-27", 2), ("INV/0001/27-28", "INV/0001/27-28", 1)],
        ),
        (["INV-999", "INV-1000"], [("INV-999", "INV-1000", 2)]),
        (["INV-1", "SHOP-1"], [("INV-1", "INV-1", 1), ("SHOP-1", "SHOP-1", 1)]),
    ],
)
def test_gstr1_doc_ranges_find_the_counter(numbers, ranges):
    assert [(r["from"], r["to"], r["totnum"]) for r in _doc_ranges(numbers)] == ranges


def test_gstr1_note_line_with_a_bad_rate_or_hsn_is_blocked(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 1000, when=datetime(2026, 4, 5))
    invoice.items[0].hsn_sac = "12345"
    _b2c_note(db_session, ledger, user, invoice, "CN-1", 100, rate=17.99)

    with pytest.raises(HTTPException) as exc:
        _export_json_data(db_session, user, company, *OCT_2026)

    assert "17.99%" in exc.value.detail
    assert "12345" in exc.value.detail


def test_gstr1_period_before_may_2025_writes_one_hsn_list(db_session):
    user, ledger, company = _unregistered(db_session)
    _b2c_sale(db_session, ledger, user, "A-1", 1000, when=datetime(2025, 3, 5))
    _b2c_sale(db_session, ledger, user, "A-2", 1000, when=datetime(2025, 5, 5))

    march = _export_json_data(db_session, user, company, date(2025, 3, 1), date(2025, 3, 31))
    may = _export_json_data(db_session, user, company, date(2025, 5, 1), date(2025, 5, 31))

    assert set(march["hsn"]) == {"data"}
    assert set(may["hsn"]) == {"hsn_b2c"}


def test_gstr1_csv_lists_notes_as_negative_rows_and_summary_counts_cancelled(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 1000)
    _b2c_note(db_session, ledger, user, invoice, "CN-1", 100)
    cancelled = _b2c_sale(db_session, ledger, user, "A-2", 1000)
    cancelled.status = "cancelled"
    db_session.commit()

    response = gstr1_export_csv(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)
    rows = {row["Invoice Number"]: row for row in csv.DictReader(StringIO(_read_stream(response).decode("utf-8-sig")))}
    assert rows["CN-1"]["Section"] == "B2CS (credit note)"
    assert rows["CN-1"]["Taxable Value"] == "-100.00"

    summary = gstr1_summary(from_date=OCT_2026[0], to_date=OCT_2026[1], db=db_session, _=user, active_company=company)
    assert summary.doc_summary.cancelled_invoices == 1


def test_tax_ledger_lists_a_note_after_the_invoice_it_reverses_on_the_same_day(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 1000, when=datetime(2026, 10, 10))
    # The note is written first, so it has the lower id in its own table.
    _b2c_note(db_session, ledger, user, invoice, "CN-1", 100, when=datetime(2026, 10, 10))

    result = get_tax_ledger(
        from_date=OCT_2026[0], to_date=OCT_2026[1], voucher_type=None, gst_rate=None,
        db=db_session, _=user, active_company=company,
    )

    assert [entry.reference_number for entry in result.entries] == ["A-1", "CN-1"]


def test_gstr1_leaves_out_an_older_note_stamped_outward_against_a_purchase(db_session):
    # Migration 20260904000001 marked every older note outward, including these.
    user, ledger = _seed_basics(db_session)
    company = _make_company(gst="29TESTT1234X1ZE")
    purchase = _add_invoice_with_item(
        db_session, ledger, user, voucher_type="purchase", invoice_number="P-1", when=datetime(2026, 10, 5),
        gst_rate=18, taxable_amount=1000, cgst_amount=90, sgst_amount=90, igst_amount=0,
    )
    _add_credit_note_item(
        db_session, user, ledger, purchase, number="CN-1", when=datetime(2026, 10, 6),
        gst_rate=18, taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0, direction="outward",
    )
    db_session.commit()

    data = _export_json_data(db_session, user, company, *OCT_2026)

    assert "cdnr" not in data
    assert "hsn" not in data
    assert "CN-1" not in str(data.get("doc_issue"))


def test_gstr1_files_a_note_on_a_sale_whatever_its_direction_says(db_session):
    user, ledger, company = _unregistered(db_session)
    invoice = _b2c_sale(db_session, ledger, user, "A-1", 50000)
    _b2c_note(db_session, ledger, user, invoice, "CN-1", 10000, direction="inward")

    row = _export_json_data(db_session, user, company, *OCT_2026)["b2cs"][0]

    assert row["txval"] == 40000.0
