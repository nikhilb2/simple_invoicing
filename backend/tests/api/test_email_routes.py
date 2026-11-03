"""SMTP failures give useful responses without aborting a reminder batch."""

import io
import smtplib
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.api.routes import email as email_routes
from src.core.config import settings
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.email_log import EmailLog
from src.models.invoice import Invoice
from src.models.smtp_config import SMTPConfig
from src.models.user import User, UserRole
from src.services import mail


@pytest.fixture
def recipients(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    user = User(
        id=1, email="test@example.com", full_name="Test Admin", hashed_password="x", role=UserRole.admin,
    )
    company = CompanyProfile(
        id=1, name="Email Test Co", address="", gst="", phone_number="", currency_code="INR",
    )
    config = SMTPConfig(
        name="test", host="smtp.example.com", port=587, username="test",
        password="test-password", from_email="sender@example.com", from_name="Sender",
        is_active=True, use_starttls=True,
    )
    db_session.add_all([user, company, config])
    db_session.flush()
    rows = []
    for index in range(3):
        ledger = Buyer(
            company_id=company.id, name=f"Customer {index}", address="", phone_number="",
            email=f"customer{index}@example.com",
        )
        db_session.add(ledger)
        db_session.flush()
        invoice = Invoice(
            company_id=company.id, ledger_id=ledger.id, created_by=user.id,
            invoice_number=f"INV-{index}", voucher_type="sales", status="active",
            taxable_amount=100, total_amount=100, invoice_date=datetime(2026, 2, 1),
        )
        db_session.add(invoice)
        db_session.flush()
        rows.append((ledger.id, invoice.id, ledger.email))
    db_session.commit()

    # Rendering is unrelated to delivery; keep the real route, mail service and log.
    monkeypatch.setattr(email_routes, "_build_invoice_pdf", lambda *args, **kwargs: io.BytesIO(b"pdf"))
    pdf = MagicMock()
    pdf.write_pdf.return_value = b"pdf"
    monkeypatch.setattr(email_routes.weasyprint, "HTML", MagicMock(return_value=pdf))
    return rows


def _send(client, kind, recipient):
    ledger_id, invoice_id, _ = recipient
    entity_id = invoice_id if kind == "invoice" else ledger_id
    payload = {"from_date": "2026-02-01", "to_date": "2026-02-28"} if kind == "ledger-statement" else {}
    return client.post(f"/api/email/{kind}/{entity_id}", json=payload)


@pytest.mark.parametrize("kind", ["invoice", "ledger-statement", "payment-reminder"])
def test_single_send_returns_a_safe_error_and_keeps_the_failed_log(
    client, db_session, monkeypatch, recipients, kind,
):
    error = smtplib.SMTPAuthenticationError(535, b"private authentication details")
    deliver = MagicMock(side_effect=error)
    monkeypatch.setattr(mail, "_send_sync", deliver)

    response = _send(client, kind, recipients[0])

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Could not send the email. Check the SMTP settings."}
    deliver.assert_called_once()
    log = db_session.query(EmailLog).one()
    assert log.status == "failed"
    assert log.error_message == str(error)
    history = client.get("/api/email-logs/", params={"status": "failed"})
    assert history.status_code == 200
    assert history.json()["items"][0]["error_message"] == str(error)


@pytest.mark.parametrize("kind", ["invoice", "ledger-statement", "payment-reminder"])
def test_single_send_still_succeeds(client, db_session, monkeypatch, recipients, kind):
    deliver = MagicMock()
    monkeypatch.setattr(mail, "_send_sync", deliver)

    response = _send(client, kind, recipients[0])

    assert response.status_code == 200, response.text
    deliver.assert_called_once()
    assert db_session.query(EmailLog).one().status == "sent"


def test_bulk_reminders_continue_after_a_failed_delivery(client, db_session, monkeypatch, recipients):
    error = smtplib.SMTPRecipientsRefused({recipients[1][2]: (550, b"recipient rejected")})
    attempted = []

    def deliver(config, message):
        attempted.append(message["To"])
        if message["To"] == recipients[1][2]:
            raise error

    monkeypatch.setattr(mail, "_send_sync", deliver)

    response = client.post("/api/email/due-reminders", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["ledger_id"] for row in body["sent"]] == [recipients[0][0], recipients[2][0]]
    assert [row["ledger_id"] for row in body["failed"]] == [recipients[1][0]]
    assert body["skipped"] == []
    assert attempted == [row[2] for row in recipients]
    logs = db_session.query(EmailLog).order_by(EmailLog.id).all()
    assert [log.status for log in logs] == ["sent", "failed", "sent"]
    assert logs[1].error_message == str(error)
