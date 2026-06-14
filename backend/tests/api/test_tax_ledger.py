from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import HTTPException

from src.api.routes.ledgers import get_tax_ledger, gstr1_export_csv, gstr1_export_json, gstr1_summary, gstr1_validate
from src.db.base import Base
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
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


def _make_company(name="Test Co", gst="29TESTT1234X1Z5"):
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
    assert response.entries[0].ledger_gst == "29ABCDE1234F1Z5"


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
        cgst_amount=27000,
        sgst_amount=27000,
        igst_amount=0,
    )
    db_session.flush()
    inv = db_session.query(Invoice).filter(Invoice.invoice_number == "B2CL-001").first()
    inv.ledger_gst = None
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
    assert data["gstin"] == "29TESTT1234X1Z5"
    assert len(data["b2b"]) == 1
    assert data["b2b"][0]["ctin"] == "29ABCDE1234F1Z5"
    assert len(data["b2b"][0]["inv"]) == 1
    assert data["b2b"][0]["inv"][0]["inum"] == "JSON-001"
    assert "doc_issue" in data


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
    ledger.gst = "27ABCDE1234F1Z5"
    db_session.flush()

    _add_invoice_with_item(
        db_session, ledger, user,
        voucher_type="sales",
        invoice_number="B2BPOS-001",
        when=datetime(2027, 3, 10),
        gst_rate=18,
        taxable_amount=5000,
        cgst_amount=450,
        sgst_amount=450,
        igst_amount=0,
    )
    db_session.commit()

    # Company GSTIN starts with "29" (Karnataka)
    company = _make_company(gst="29TESTT1234X1Z5")

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
    assert data["b2b"][0]["ctin"] == "27ABCDE1234F1Z5"
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

    company = _make_company(gst="29TESTT1234X1Z5")

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
    assert data["cdnr"][0]["ctin"] == "29ABCDE1234F1Z5"
    assert len(data["cdnr"][0]["nt"]) == 1
    assert data["cdnr"][0]["nt"][0]["nt_num"] == "CDNR-CN-001"
    assert data["cdnr"][0]["nt"][0]["pos"] == "29"


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
    company = _make_company(gst="29TESTT1234X1Z5")

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
    company = _make_company(gst="29TESTT1234X1Z5")

    data = _export_json_data(db_session, user, company, date(2026, 4, 1), date(2026, 4, 30))

    doc_det = data["doc_issue"]["doc_det"]
    inv_doc = next(d for d in doc_det if d["doc_num"] == 1)
    assert "doc_typ" not in inv_doc
    rng = inv_doc["docs"][0]
    assert rng["from"] == "DOC-001"
    assert rng["to"] == "DOC-002"
    assert rng["totnum"] == 2
    assert rng["net_issue"] == 2


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
    company = _make_company(gst="29TESTT1234X1Z5")

    data = _export_json_data(db_session, user, company, date(2026, 4, 1), date(2026, 4, 30))

    assert "hsn_b2b" in data["hsn"]
    row = data["hsn"]["hsn_b2b"][0]
    assert list(row.keys())[0] == "hsn_sc"
    assert row["hsn_sc"] == "84713010"
    assert row["rt"] == 18
    assert row["txval"] == 5000.0
