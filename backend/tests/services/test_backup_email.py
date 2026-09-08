"""Mailing a finished automatic backup to the admins.

The rule this file exists to hold: emailing is best-effort. The archive is already
written and safe by the time any of this runs, so every failure mode here has to
come back as a reported outcome rather than an exception.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.smtp_config import SMTPConfig
from src.models.user import User, UserRole
from src.services import backup_email

CREATED_AT = datetime(2026, 9, 9, 18, 30, tzinfo=timezone.utc)


def _fake_db(smtp=None, admins=(), company=None):
    """A session that answers the three queries backup_email actually makes."""
    db = MagicMock()

    def query(model):
        result = MagicMock()
        if model is SMTPConfig:
            result.filter.return_value.first.return_value = smtp
        elif model is User:
            result.filter.return_value.all.return_value = list(admins)
        elif model is CompanyProfile:
            result.order_by.return_value.first.return_value = company
        return result

    db.query.side_effect = query
    return db


def _admin(email):
    return SimpleNamespace(email=email, role=UserRole.admin)


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "autobackup_20260909_183000.enc"
    path.write_bytes(b"encrypted-archive-bytes")
    return path


@pytest.fixture
def active_smtp():
    config = SMTPConfig()
    config.is_active = True
    return config


def _send(archive_path, db, **overrides):
    """Run email_backup_archive against a stubbed session and captured send_email."""
    sent = {}

    async def fake_send_email(**kwargs):
        sent.update(kwargs)

    with patch.object(backup_email, "SessionLocal", return_value=db), patch.object(
        backup_email, "send_email", fake_send_email
    ):
        outcome = asyncio.run(
            backup_email.email_backup_archive(
                archive_path=archive_path,
                created_at=CREATED_AT,
                migration_head=overrides.get("migration_head", "20260906000002_add_upi"),
            )
        )
    return outcome, sent


# --- recipients ------------------------------------------------------------

def test_recipients_default_to_admin_users(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "")
    db = _fake_db(admins=[_admin("zoe@example.com"), _admin("amit@example.com")])
    assert backup_email.resolve_recipients(db) == ["amit@example.com", "zoe@example.com"]


def test_recipients_override_wins_and_is_deduped(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", " ops@example.com, ops@example.com ,cto@example.com ")
    db = _fake_db(admins=[_admin("ignored@example.com")])
    assert backup_email.resolve_recipients(db) == ["cto@example.com", "ops@example.com"]


def test_recipients_skip_admins_with_no_address(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "")
    db = _fake_db(admins=[_admin(None), _admin("real@example.com")])
    assert backup_email.resolve_recipients(db) == ["real@example.com"]


# --- the cases where nothing is sent ---------------------------------------

def test_skipped_when_email_is_turned_off(monkeypatch, archive):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", False)
    outcome, sent = _send(archive, _fake_db())
    assert outcome.status == "skipped"
    assert "AUTO_BACKUP_EMAIL_ENABLED" in outcome.detail
    assert sent == {}


def test_skipped_when_no_smtp_is_configured(monkeypatch, archive):
    """The stated condition: mail only goes out if the user has email set up."""
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    outcome, sent = _send(archive, _fake_db(smtp=None, admins=[_admin("a@example.com")]))
    assert outcome.status == "skipped"
    assert "No active SMTP configuration" in outcome.detail
    assert sent == {}


def test_skipped_when_there_is_nobody_to_send_to(monkeypatch, archive, active_smtp):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "")
    outcome, sent = _send(archive, _fake_db(smtp=active_smtp, admins=[]))
    assert outcome.status == "skipped"
    assert "AUTO_BACKUP_EMAIL_TO" in outcome.detail
    assert sent == {}


# --- the cases where something is sent -------------------------------------

def test_archive_is_attached_and_extra_admins_are_cc(monkeypatch, archive, active_smtp):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "")
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_MAX_MB", 15)
    db = _fake_db(smtp=active_smtp, admins=[_admin("amit@example.com"), _admin("zoe@example.com")])

    outcome, sent = _send(archive, db)

    assert outcome.status == "sent"
    assert sent["to"] == "amit@example.com"
    assert sent["cc"] == ["zoe@example.com"]
    assert sent["email_type"] == "automatic_backup"
    assert sent["attachments"] == [(b"encrypted-archive-bytes", archive.name)]
    assert archive.name in sent["subject"]


def test_single_recipient_gets_no_cc_header(monkeypatch, archive, active_smtp):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "solo@example.com")
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_MAX_MB", 15)

    outcome, sent = _send(archive, _fake_db(smtp=active_smtp))

    assert outcome.status == "sent"
    assert sent["cc"] is None


def test_oversized_archive_still_sends_a_notice_without_the_attachment(
    monkeypatch, archive, active_smtp
):
    """The admin needs to learn the backup exists even when it is too big to mail."""
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "ops@example.com")
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_MAX_MB", 0)

    outcome, sent = _send(archive, _fake_db(smtp=active_smtp))

    assert outcome.status == "sent"
    assert sent["attachments"] is None
    assert "0 MB limit" in outcome.detail
    assert "not attached" in sent["html_body"]


def test_company_profile_supplies_the_email_header(monkeypatch, archive, active_smtp):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "ops@example.com")
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_MAX_MB", 15)
    company = CompanyProfile(name="Acme Traders", address="Mumbai", email="hi@acme.example")

    outcome, sent = _send(archive, _fake_db(smtp=active_smtp, company=company))

    assert outcome.status == "sent"
    assert "Acme Traders" in sent["html_body"]


def test_missing_company_profile_does_not_stop_the_email(monkeypatch, archive, active_smtp):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "ops@example.com")
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_MAX_MB", 15)

    outcome, sent = _send(archive, _fake_db(smtp=active_smtp, company=None))

    assert outcome.status == "sent"
    assert "Simple Invoicing" in sent["html_body"]


# --- failure is reported, never raised -------------------------------------

def test_smtp_failure_is_reported_not_raised(monkeypatch, archive, active_smtp):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_TO", "ops@example.com")
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_MAX_MB", 15)

    async def boom(**_kwargs):
        raise RuntimeError("connection refused")

    with patch.object(backup_email, "SessionLocal", return_value=_fake_db(smtp=active_smtp)), patch.object(
        backup_email, "send_email", boom
    ):
        outcome = asyncio.run(
            backup_email.email_backup_archive(
                archive_path=archive, created_at=CREATED_AT, migration_head=None
            )
        )

    assert outcome.status == "failed"
    assert "connection refused" in outcome.detail


def test_a_broken_session_is_reported_not_raised(monkeypatch, archive):
    monkeypatch.setattr(settings, "AUTO_BACKUP_EMAIL_ENABLED", True)
    db = MagicMock()
    db.query.side_effect = RuntimeError("database is gone")

    with patch.object(backup_email, "SessionLocal", return_value=db):
        outcome = asyncio.run(
            backup_email.email_backup_archive(
                archive_path=archive, created_at=CREATED_AT, migration_head=None
            )
        )

    assert outcome.status == "failed"
    assert "database is gone" in outcome.detail
    db.close.assert_called_once()


@pytest.mark.parametrize(
    "size,expected",
    [(512, "512 B"), (2048, "2.0 KB"), (5 * 1024 * 1024, "5.00 MB")],
)
def test_format_size(size, expected):
    assert backup_email._format_size(size) == expected
