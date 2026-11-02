"""Tenant mail on a shared host: through the platform relay, never a stored SMTPConfig."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.email_log import EmailLog
from src.models.smtp_config import SMTPConfig
from src.services import backup_email, platform_mail
from src.services.mail import send_email


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def relay(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", "smtp-relay.example.com")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_FROM_EMAIL", "no-reply@host.example")
    monkeypatch.setattr(settings, "PLATFORM_SMTP_FROM_NAME", "Simple Invoicing")
    monkeypatch.setattr(platform_mail, "_deliver", sent.append)
    return sent


@pytest.fixture
def company(db_session):
    row = CompanyProfile(name="Alpha Traders", address="", gst="", phone_number="", email="billing@alpha.example")
    db_session.add(row)
    db_session.commit()
    return row


def _logs(db):
    return db.query(EmailLog).order_by(EmailLog.id).all()


@pytest.mark.anyio
async def test_sends_from_the_platform_as_the_company_with_replies_to_it(db_session, relay, company):
    await send_email(db_session, "customer@example.com", "Invoice 1", "<p>hi</p>",
                     attachments=[(b"%PDF", "invoice.pdf")], cc=["cc@example.com"], company_id=company.id)

    msg = relay[0]
    assert msg["From"] == "Alpha Traders via Simple Invoicing <no-reply@host.example>"
    assert msg["Reply-To"] == "billing@alpha.example"
    assert msg["To"] == "customer@example.com"
    assert msg["Cc"] == "cc@example.com"
    assert [p.get_filename() for p in msg.walk() if p.get_filename()] == ["invoice.pdf"]
    assert _logs(db_session)[0].status == "sent"


@pytest.mark.anyio
async def test_a_stored_smtp_config_is_never_used_for_tenant_mail(db_session, relay, company):
    db_session.add(SMTPConfig(name="old", host="smtp.tenant.example", port=587, username="u", password="p",
                              from_email="spoof@bank.example", from_name="Bank", is_active=True))
    db_session.commit()

    with patch("src.services.mail._send_sync") as stored_config_send:
        await send_email(db_session, "customer@example.com", "S", "<p/>", company_id=company.id)

    stored_config_send.assert_not_called()
    assert "no-reply@host.example" in relay[0]["From"]


@pytest.mark.anyio
async def test_awkward_company_names_stay_inside_the_display_name(db_session, relay):
    row = CompanyProfile(name='Evil, "Inc" <x@bank.example>\nBcc: a@b.example', address="", gst="", phone_number="")
    db_session.add(row)
    db_session.commit()

    await send_email(db_session, "customer@example.com", "S", "<p/>", company_id=row.id)

    sender = relay[0]["From"]
    assert sender.endswith("<no-reply@host.example>")
    assert "\n" not in sender


@pytest.mark.anyio
@pytest.mark.parametrize("to,cc", [
    ("one@example.com, two@example.com", None),
    ("one@example.com", ["two@example.com, three@example.com"]),
    ("not-an-address", None),
])
async def test_each_recipient_field_takes_one_valid_address(db_session, relay, company, to, cc):
    with pytest.raises(RuntimeError, match="not a valid email address"):
        await send_email(db_session, to, "S", "<p/>", cc=cc, company_id=company.id)
    assert relay == []


@pytest.mark.anyio
async def test_a_typo_in_the_company_email_only_costs_the_reply_to(db_session, relay):
    row = CompanyProfile(name="Typo Co", address="", gst="", phone_number="", email="billing at typo")
    db_session.add(row)
    db_session.commit()

    await send_email(db_session, "customer@example.com", "S", "<p/>", company_id=row.id)

    assert relay[0]["Reply-To"] is None


@pytest.mark.anyio
async def test_daily_limit_is_per_company_and_ignores_failures_and_old_mail(db_session, relay, company, monkeypatch):
    monkeypatch.setattr(settings, "TENANT_EMAIL_DAILY_LIMIT", 2)
    other = CompanyProfile(name="Beta", address="", gst="", phone_number="")
    db_session.add(other)
    db_session.commit()
    db_session.add_all([
        EmailLog(company_id=company.id, to_email="a@x.example", subject="failed", status="failed"),
        EmailLog(company_id=company.id, to_email="a@x.example", subject="old", status="sent",
                 sent_at=datetime.now(timezone.utc) - timedelta(days=2)),
        EmailLog(company_id=other.id, to_email="a@x.example", subject="other", status="sent"),
    ])
    db_session.commit()

    await send_email(db_session, "c@example.com", "1", "<p/>", company_id=company.id)
    await send_email(db_session, "c@example.com", "2", "<p/>", company_id=company.id)
    with pytest.raises(RuntimeError, match="Daily email limit"):
        await send_email(db_session, "c@example.com", "3", "<p/>", company_id=company.id)

    assert len(relay) == 2
    await send_email(db_session, "c@example.com", "other", "<p/>", company_id=other.id)
    assert len(relay) == 3


@pytest.mark.anyio
async def test_relay_errors_are_not_shown_to_the_tenant(db_session, relay, company, monkeypatch):
    def refuse(_msg):
        raise OSError("535 credits exhausted for account owner@host.example")

    monkeypatch.setattr(platform_mail, "_deliver", refuse)

    with pytest.raises(RuntimeError) as caught:
        await send_email(db_session, "customer@example.com", "S", "<p/>", company_id=company.id)

    assert "credits" not in str(caught.value)
    log = _logs(db_session)[0]
    assert log.status == "failed"
    assert "credits" not in log.error_message


@pytest.mark.anyio
async def test_no_relay_or_no_company_fails_closed(db_session, relay, company, monkeypatch):
    with pytest.raises(RuntimeError, match="needs a company"):
        await send_email(db_session, "customer@example.com", "S", "<p/>")

    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", None)
    with pytest.raises(RuntimeError, match="not available"):
        await send_email(db_session, "customer@example.com", "S", "<p/>", company_id=company.id)
    assert relay == []


@pytest.mark.anyio
async def test_platform_job_can_keep_the_stored_smtp_config(db_session, relay):
    config = SMTPConfig(name="ops", host="smtp.ops.example", port=587, username="u", password="p",
                        from_email="ops@host.example", from_name="Ops", is_active=True)
    db_session.add(config)
    db_session.commit()

    with patch("src.services.mail._send_sync") as stored_config_send:
        await send_email(db_session, "ops@host.example", "Backup", "<p/>", use_smtp_config=True)

    stored_config_send.assert_called_once()
    assert relay == []


def test_backup_email_stays_off_the_relay():
    import inspect
    assert "use_smtp_config=True" in inspect.getsource(backup_email)


@pytest.mark.anyio
async def test_single_tenant_never_uses_the_relay(db_session, monkeypatch, company):
    sent = []
    monkeypatch.setattr(settings, "PLATFORM_SMTP_HOST", "smtp-relay.example.com")
    monkeypatch.setattr(platform_mail, "_deliver", sent.append)
    db_session.add(SMTPConfig(name="own", host="smtp.own.example", port=587, username="u", password="p",
                              from_email="me@own.example", from_name="Me", is_active=True))
    db_session.commit()

    with patch("src.services.mail._send_sync") as own_send:
        await send_email(db_session, "customer@example.com, second@example.com", "S", "<p/>", company_id=company.id)

    own_send.assert_called_once()
    assert own_send.call_args.args[1]["From"] == "Me <me@own.example>"
    assert sent == []


