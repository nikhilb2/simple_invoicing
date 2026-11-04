"""Reminder links resolve their period when read, using real in-memory ORM data.

These tests exercise the route functions and public router without app_main's
PostgreSQL startup/migrations. Mail delivery and PDF conversion are test doubles.
"""

import asyncio
import re
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import src.models  # noqa: F401
from src.api.routes import email, public_share
from src.core.config import settings
from src.db.base import Base
from src.db.session import get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.share_link import ShareLink
from src.models.user import User, UserRole
from src.services import share_documents as shares


@pytest.fixture
def reminder_case(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(email='reminder@example.com', full_name='Owner', hashed_password='x', role=UserRole.admin)
    company = CompanyProfile(name='Company', address='Mumbai', currency_code='INR',
                             show_pay_qr_on_invoice=True)
    db.add_all([user, company])
    db.commit()
    ledger = Buyer(company_id=company.id, name='Customer', address='Mumbai',
                   phone_number='9999999999', email='customer@example.com')
    db.add(ledger)
    db.commit()
    monkeypatch.setattr(settings, 'SHARE_LINKS_ENABLED', True)
    sent = AsyncMock()
    monkeypatch.setattr(email, 'send_email', sent)
    monkeypatch.setattr(email, 'track', lambda *args, **kwargs: None)
    monkeypatch.setattr(public_share, '_track_share', lambda *args, **kwargs: None)
    public_share.reset_rate_limits()
    app = FastAPI()
    app.include_router(public_share.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield SimpleNamespace(db=db, user=user, company=company, ledger=ledger, sent=sent, client=client)
    db.close()
    engine.dispose()
    public_share.reset_rate_limits()


def invoice(case, when, amount=100, company_id=None, status='active'):
    row = Invoice(
        invoice_number=f'REM-{case.db.query(Invoice).count()}',
        company_id=company_id or case.company.id, ledger_id=case.ledger.id,
        created_by=case.user.id, voucher_type='sales', status=status,
        invoice_date=datetime.combine(when, datetime.min.time()),
        total_amount=Decimal(amount), taxable_amount=Decimal(amount),
        total_tax_amount=0, cgst_amount=0, sgst_amount=0,
    )
    case.db.add(row)
    case.db.commit()
    return row


def today(monkeypatch, value):
    class ClockDate(date):
        @classmethod
        def today(cls):
            return value

    # Patch both the old location and the shared service after the helper moves.
    monkeypatch.setattr(email, 'date', ClockDate)
    monkeypatch.setattr(shares, 'date', ClockDate)


def remind(case, bulk=False):
    request = Request({'type': 'http', 'scheme': 'https', 'server': ('billing.test', 443),
                       'path': '/api/email', 'root_path': '', 'headers': []})
    kwargs = dict(request=request, db=case.db, current_user=case.user, active_company=case.company)
    if bulk:
        result = email.send_due_reminders(payload=email.DueRemindersRequest(), **kwargs)
    else:
        result = email.send_payment_reminder_email(
            case.ledger.id, payload=email.EmailSendRequest(), **kwargs)
    asyncio.run(result)
    return case.sent.await_args.kwargs['html_body']


@pytest.mark.parametrize('bulk', [False, True])
def test_reminders_reuse_one_open_link_across_days_and_backdated_invoices(reminder_case, monkeypatch, bulk):
    case = reminder_case
    invoice(case, date(2026, 1, 1))
    today(monkeypatch, date(2026, 1, 10))
    first = remind(case, bulk)
    today(monkeypatch, date(2026, 1, 11))
    invoice(case, date(2025, 12, 1), 200)
    second = remind(case, bulk)
    links = case.db.query(ShareLink).filter(ShareLink.revoked_at.is_(None)).all()
    assert len(links) == 1
    assert links[0].from_date is None and links[0].to_date is None
    urls = [re.search(r'https?[^\s"<>]+/s/[A-Za-z0-9_-]+', html).group() for html in (first, second)]
    assert urls[0] == urls[1]


def test_open_statement_landing_document_and_pdf_use_current_period_and_balance(reminder_case, monkeypatch):
    case = reminder_case
    invoice(case, date(2026, 1, 1))
    link, _ = shares.ensure_live_share_link(case.db, case.company.id, shares.RESOURCE_STATEMENT, case.ledger.id)
    today(monkeypatch, date(2026, 1, 11))
    invoice(case, date(2025, 12, 1), 200)
    case.db.add(Payment(company_id=case.company.id, ledger_id=case.ledger.id,
                        voucher_type='receipt', status='active', amount=50, created_by=case.user.id,
                        date=datetime(2026, 1, 11), mode='cash', payment_number='RCPT-1'))
    case.db.commit()
    summary = shares.build_share_summary(case.db, link)
    assert summary is not None
    assert summary.date_label == '01 Dec 2025 – 11 Jan 2026'
    assert '250.00' in summary.amount_label
    pdf_html = []

    class PdfConverter:
        def __init__(self, *, string, **kwargs):
            pdf_html.append(string)

        def write_pdf(self):
            return b'%PDF-test'

    monkeypatch.setattr(shares.weasyprint, 'HTML', PdfConverter)
    landing = case.client.get(f'/s/{link.token}')
    document = case.client.get(f'/s/{link.token}/document.html')
    pdf = case.client.get(f'/s/{link.token}/pdf')
    assert landing.status_code == document.status_code == pdf.status_code == 200
    assert pdf.content == b'%PDF-test'
    for html in (landing.text, document.text, pdf_html[0]):
        assert '250.00' in html
        assert '01 Dec 2025' in html and '11 Jan 2026' in html


def test_chosen_period_link_stays_separate_and_keeps_its_dates(reminder_case, monkeypatch):
    case = reminder_case
    invoice(case, date(2026, 1, 1))
    fixed, _ = shares.ensure_live_share_link(
        case.db, case.company.id, shares.RESOURCE_STATEMENT, case.ledger.id,
        from_date=date(2026, 1, 1), to_date=date(2026, 1, 10))
    today(monkeypatch, date(2026, 1, 10))
    remind(case)
    links = case.db.query(ShareLink).all()
    assert len(links) == 2
    assert any(link.from_date is None and link.to_date is None for link in links)
    today(monkeypatch, date(2026, 2, 1))
    assert shares.build_share_summary(case.db, fixed).date_label == '01 Jan 2026 – 10 Jan 2026'


def test_revoking_the_open_link_disables_it_and_next_reminder_mints_another(reminder_case, monkeypatch):
    case = reminder_case
    invoice(case, date(2026, 1, 1))
    today(monkeypatch, date(2026, 1, 10))
    remind(case)
    old = case.db.query(ShareLink).one()
    old.revoked_at = datetime(2026, 1, 10, 12)
    case.db.commit()
    assert case.client.get(f'/s/{old.token}').status_code == 404
    remind(case)
    live = case.db.query(ShareLink).filter(ShareLink.revoked_at.is_(None)).one()
    assert live.token != old.token
    assert case.client.get(f'/s/{live.token}').status_code == 200


@pytest.mark.parametrize('from_date,to_date', [(date(2026, 1, 1), None), (None, date(2026, 1, 10))])
def test_partially_dated_links_remain_unavailable(reminder_case, from_date, to_date):
    case = reminder_case
    link, _ = shares.ensure_live_share_link(
        case.db, case.company.id, shares.RESOURCE_STATEMENT, case.ledger.id,
        from_date=from_date, to_date=to_date)
    assert shares.build_share_summary(case.db, link) is None
    assert case.client.get(f'/s/{link.token}').status_code == 404
