import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from src.api.routes.email import StatementEmailSendRequest, send_ledger_statement_email, send_payment_reminder_email
from src.api.routes.ledgers import get_day_book, get_ledger_statement
from src.db.base import Base
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.financial_year import FinancialYear
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.product import Product
from src.models.user import User, UserRole

_ = (FinancialYear, Product)


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
    company = CompanyProfile(
        name="Respawn Pvt Ltd",
        address="1 Billing Street",
        gst="29RESP1234N1Z1",
        phone_number="8888888888",
        currency_code="INR",
        email="accounts@example.com",
    )
    db_session.add_all([user, ledger, company])
    db_session.commit()
    return user, ledger, company


def _add_invoice(db_session, ledger, user, amount, when, status="active", voucher_type="sales"):
    invoice = Invoice(
        invoice_number=f"INV-{when.strftime('%Y%m%d%H%M%S')}-{status}-{amount}",
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
        status=status,
        created_by=user.id,
        taxable_amount=amount,
        total_tax_amount=0,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=0,
        total_amount=amount,
        invoice_date=when,
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


def _add_payment(db_session, ledger, user, amount, when, status="active", voucher_type="receipt"):
    payment = Payment(
        ledger_id=ledger.id,
        voucher_type=voucher_type,
        amount=amount,
        date=when,
        payment_number=f"PAY-{when.strftime('%Y%m%d%H%M%S')}-{status}-{amount}",
        mode="bank",
        created_by=user.id,
        status=status,
    )
    db_session.add(payment)
    db_session.flush()
    return payment


def _add_credit_note(db_session, ledger, user, invoice, amount, when, status="active"):
    credit_note = CreditNote(
        credit_note_number=f"CN-{when.strftime('%Y%m%d%H%M%S')}-{status}-{amount}",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        status=status,
        taxable_amount=amount,
        cgst_amount=0,
        sgst_amount=0,
        igst_amount=0,
        total_amount=amount,
        created_at=when,
    )
    db_session.add(credit_note)
    db_session.flush()

    item = CreditNoteItem(
        credit_note_id=credit_note.id,
        invoice_id=invoice.id,
        quantity=1,
        unit_price=amount,
        gst_rate=0,
        taxable_amount=amount,
        tax_amount=0,
        line_total=amount,
        created_at=when,
    )
    db_session.add(item)
    db_session.flush()
    return credit_note


def test_day_book_excludes_cancelled_financial_documents(db_session):
    user, ledger, _ = _seed_basics(db_session)
    active_invoice = _add_invoice(db_session, ledger, user, 100, datetime(2026, 1, 12, 10, 0, 0))
    cancelled_invoice = _add_invoice(db_session, ledger, user, 250, datetime(2026, 1, 13, 10, 0, 0), status="cancelled")
    active_receipt = _add_payment(db_session, ledger, user, 30, datetime(2026, 1, 14, 10, 0, 0))
    cancelled_receipt = _add_payment(db_session, ledger, user, 60, datetime(2026, 1, 15, 10, 0, 0), status="cancelled")
    active_credit_note = _add_credit_note(db_session, ledger, user, active_invoice, 10, datetime(2026, 1, 16, 10, 0, 0))
    cancelled_credit_note = _add_credit_note(db_session, ledger, user, active_invoice, 5, datetime(2026, 1, 17, 10, 0, 0), status="cancelled")
    db_session.commit()

    result = get_day_book(
        from_date=date(2026, 1, 10),
        to_date=date(2026, 1, 31),
        db=db_session,
        _=user,
    )

    assert result.total_debit == pytest.approx(100.0)
    assert result.total_credit == pytest.approx(40.0)
    assert {(entry.entry_type, entry.entry_id) for entry in result.entries} == {
        ("invoice", active_invoice.id),
        ("payment", active_receipt.id),
        ("credit_note", active_credit_note.id),
    }
    assert all(entry.entry_id != cancelled_invoice.id for entry in result.entries)
    assert all(entry.entry_id != cancelled_receipt.id for entry in result.entries)
    assert all(entry.entry_id != cancelled_credit_note.id for entry in result.entries)


def test_ledger_statement_excludes_cancelled_documents_from_opening_and_period_balances(db_session):
    user, ledger, _ = _seed_basics(db_session)
    opening_invoice = _add_invoice(db_session, ledger, user, 100, datetime(2026, 1, 1, 10, 0, 0))
    _add_invoice(db_session, ledger, user, 250, datetime(2026, 1, 2, 10, 0, 0), status="cancelled")
    _add_payment(db_session, ledger, user, 20, datetime(2026, 1, 3, 10, 0, 0))
    _add_payment(db_session, ledger, user, 15, datetime(2026, 1, 4, 10, 0, 0), status="cancelled")
    _add_credit_note(db_session, ledger, user, opening_invoice, 5, datetime(2026, 1, 5, 10, 0, 0))
    _add_credit_note(db_session, ledger, user, opening_invoice, 7, datetime(2026, 1, 6, 10, 0, 0), status="cancelled")

    period_invoice = _add_invoice(db_session, ledger, user, 40, datetime(2026, 1, 12, 10, 0, 0))
    _add_invoice(db_session, ledger, user, 80, datetime(2026, 1, 13, 10, 0, 0), status="cancelled")
    period_receipt = _add_payment(db_session, ledger, user, 10, datetime(2026, 1, 14, 10, 0, 0))
    _add_payment(db_session, ledger, user, 8, datetime(2026, 1, 15, 10, 0, 0), status="cancelled")
    period_credit_note = _add_credit_note(db_session, ledger, user, period_invoice, 3, datetime(2026, 1, 16, 10, 0, 0))
    _add_credit_note(db_session, ledger, user, period_invoice, 2, datetime(2026, 1, 17, 10, 0, 0), status="cancelled")
    db_session.commit()

    result = get_ledger_statement(
        ledger_id=ledger.id,
        from_date=date(2026, 1, 10),
        to_date=date(2026, 1, 31),
        db=db_session,
        _=user,
    )

    assert result.opening_balance == pytest.approx(75.0)
    assert result.period_debit == pytest.approx(40.0)
    assert result.period_credit == pytest.approx(13.0)
    assert result.closing_balance == pytest.approx(102.0)
    assert {(entry.entry_type, entry.entry_id) for entry in result.entries} == {
        ("invoice", period_invoice.id),
        ("payment", period_receipt.id),
        ("credit_note", period_credit_note.id),
    }


def test_statement_email_uses_same_active_only_statement_math(db_session):
    user, ledger, _ = _seed_basics(db_session)
    opening_invoice = _add_invoice(db_session, ledger, user, 100, datetime(2026, 1, 1, 10, 0, 0))
    _add_invoice(db_session, ledger, user, 250, datetime(2026, 1, 2, 10, 0, 0), status="cancelled")
    _add_payment(db_session, ledger, user, 20, datetime(2026, 1, 3, 10, 0, 0))
    _add_payment(db_session, ledger, user, 15, datetime(2026, 1, 4, 10, 0, 0), status="cancelled")
    _add_credit_note(db_session, ledger, user, opening_invoice, 5, datetime(2026, 1, 5, 10, 0, 0))

    period_invoice = _add_invoice(db_session, ledger, user, 40, datetime(2026, 1, 12, 10, 0, 0))
    _add_invoice(db_session, ledger, user, 80, datetime(2026, 1, 13, 10, 0, 0), status="cancelled")
    _add_payment(db_session, ledger, user, 10, datetime(2026, 1, 14, 10, 0, 0))
    _add_payment(db_session, ledger, user, 8, datetime(2026, 1, 15, 10, 0, 0), status="cancelled")
    _add_credit_note(db_session, ledger, user, period_invoice, 3, datetime(2026, 1, 16, 10, 0, 0))
    db_session.commit()

    fake_template = MagicMock()
    fake_template.render.return_value = "body"
    fake_html_instance = MagicMock()
    fake_html_instance.write_pdf.return_value = b"pdf"

    with patch("src.api.routes.email._build_statement_html", return_value="<html>statement</html>") as build_html_mock, patch(
        "src.api.routes.email._jinja_env.get_template",
        return_value=fake_template,
    ), patch("src.api.routes.email.weasyprint.HTML", return_value=fake_html_instance), patch(
        "src.api.routes.email.send_email",
        new=AsyncMock(),
    ) as send_email_mock:
        asyncio.run(send_ledger_statement_email(
            ledger_id=ledger.id,
            payload=StatementEmailSendRequest(
                to="customer@example.com",
                from_date=date(2026, 1, 10),
                to_date=date(2026, 1, 31),
            ),
            db=db_session,
            _=user,
        ))

    build_kwargs = build_html_mock.call_args.kwargs
    assert build_kwargs["opening_balance"] == pytest.approx(75.0)
    assert build_kwargs["period_debit"] == pytest.approx(40.0)
    assert build_kwargs["period_credit"] == pytest.approx(13.0)
    assert build_kwargs["closing_balance"] == pytest.approx(102.0)
    assert len(build_kwargs["entries"]) == 3

    render_kwargs = fake_template.render.call_args.kwargs
    assert render_kwargs["total_invoices"] == "40.00"


def test_ledger_statement_supports_signed_opening_balance_entries(db_session):
    user, ledger, _ = _seed_basics(db_session)

    # Opening balance window (before from_date)
    _add_payment(db_session, ledger, user, 120, datetime(2026, 1, 1, 9, 0, 0), voucher_type="opening_balance")
    _add_payment(db_session, ledger, user, -30, datetime(2026, 1, 2, 9, 0, 0), voucher_type="opening_balance")

    # Period window
    period_positive_opening = _add_payment(db_session, ledger, user, 15, datetime(2026, 1, 11, 9, 0, 0), voucher_type="opening_balance")
    period_negative_opening = _add_payment(db_session, ledger, user, -40, datetime(2026, 1, 12, 9, 0, 0), voucher_type="opening_balance")
    period_receipt = _add_payment(db_session, ledger, user, 10, datetime(2026, 1, 13, 9, 0, 0), voucher_type="receipt")
    period_payment = _add_payment(db_session, ledger, user, 5, datetime(2026, 1, 14, 9, 0, 0), voucher_type="payment")
    db_session.commit()

    result = get_ledger_statement(
        ledger_id=ledger.id,
        from_date=date(2026, 1, 10),
        to_date=date(2026, 1, 31),
        db=db_session,
        _=user,
    )

    assert result.opening_balance == pytest.approx(90.0)
    assert result.period_debit == pytest.approx(20.0)
    assert result.period_credit == pytest.approx(50.0)
    assert result.closing_balance == pytest.approx(60.0)

    entry_by_id = {entry.entry_id: entry for entry in result.entries}
    assert entry_by_id[period_positive_opening.id].debit == pytest.approx(15.0)
    assert entry_by_id[period_positive_opening.id].credit == pytest.approx(0.0)
    assert entry_by_id[period_positive_opening.id].voucher_type == "Opening Balance"
    assert entry_by_id[period_negative_opening.id].debit == pytest.approx(0.0)
    assert entry_by_id[period_negative_opening.id].credit == pytest.approx(40.0)
    assert entry_by_id[period_receipt.id].credit == pytest.approx(10.0)
    assert entry_by_id[period_payment.id].debit == pytest.approx(5.0)


def test_day_book_supports_signed_opening_balance_entries(db_session):
    user, ledger, _ = _seed_basics(db_session)
    opening_positive = _add_payment(db_session, ledger, user, 25, datetime(2026, 1, 20, 10, 0, 0), voucher_type="opening_balance")
    opening_negative = _add_payment(db_session, ledger, user, -12, datetime(2026, 1, 21, 10, 0, 0), voucher_type="opening_balance")
    db_session.commit()

    result = get_day_book(
        from_date=date(2026, 1, 20),
        to_date=date(2026, 1, 31),
        db=db_session,
        _=user,
    )

    assert result.total_debit == pytest.approx(25.0)
    assert result.total_credit == pytest.approx(12.0)
    entry_by_id = {entry.entry_id: entry for entry in result.entries}
    assert entry_by_id[opening_positive.id].voucher_type == "Opening Balance"
    assert entry_by_id[opening_positive.id].debit == pytest.approx(25.0)
    assert entry_by_id[opening_negative.id].credit == pytest.approx(12.0)


def test_payment_reminder_ignores_cancelled_documents_and_cancelled_last_payment(db_session):
    user, ledger, _ = _seed_basics(db_session)
    invoice = _add_invoice(db_session, ledger, user, 100, datetime(2026, 1, 5, 10, 0, 0))
    _add_invoice(db_session, ledger, user, 300, datetime(2026, 1, 6, 10, 0, 0), status="cancelled")
    _add_credit_note(db_session, ledger, user, invoice, 10, datetime(2026, 1, 18, 10, 0, 0))
    _add_credit_note(db_session, ledger, user, invoice, 7, datetime(2026, 1, 26, 10, 0, 0), status="cancelled")
    _add_payment(db_session, ledger, user, 20, datetime(2026, 1, 20, 10, 0, 0))
    _add_payment(db_session, ledger, user, 99, datetime(2026, 1, 25, 10, 0, 0), status="cancelled")
    db_session.commit()

    fake_template = MagicMock()
    fake_template.render.return_value = "body"

    with patch(
        "src.api.routes.email._jinja_env.get_template",
        return_value=fake_template,
    ), patch("src.api.routes.email.send_email", new=AsyncMock()) as send_email_mock:
        asyncio.run(send_payment_reminder_email(
            ledger_id=ledger.id,
            payload=None,
            db=db_session,
            _=user,
        ))

    render_kwargs = fake_template.render.call_args.kwargs
    assert render_kwargs["outstanding_balance"] == "70.00"
    assert render_kwargs["last_payment_date"] == "20 Jan 2026"
    assert render_kwargs["unpaid_invoices"] == [
        {
            "invoice_number": invoice.invoice_number,
            "invoice_date": "05 Jan 2026",
            "due_date": None,
            "amount": "90.00",
        }
    ]
    send_email_mock.assert_awaited_once()
