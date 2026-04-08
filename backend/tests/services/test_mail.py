import pytest
from unittest.mock import MagicMock, patch
import asyncio
from src.services.mail import send_email, _get_active_smtp_config, _build_message, _send_sync
from src.models.smtp_config import SMTPConfig

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def active_config():
    config = SMTPConfig()
    config.is_active = True
    config.host = "smtp.example.com"
    config.port = 587
    config.username = "user"
    config.from_email = "from@example.com"
    config.from_name = "Sender"
    config.use_starttls = True
    return config

def test_get_active_smtp_config_success(mock_db, active_config):
    mock_db.query().filter().first.return_value = active_config
    result = _get_active_smtp_config(mock_db)
    assert result == active_config

def test_get_active_smtp_config_none(mock_db):
    mock_db.query().filter().first.return_value = None
    with pytest.raises(RuntimeError, match="No active SMTP configuration found"):
        _get_active_smtp_config(mock_db)

def test_build_message():
    to = "to@example.com"
    subject = "Test"
    html = "<h1>Hello</h1>"
    from_e = "from@example.com"
    from_n = "Sender"
    cc = ["cc@example.com"]
    attachments = [(b"data", "test.pdf")]

    msg = _build_message(to, subject, html, from_e, from_n, attachments, cc)
    
    assert msg["Subject"] == subject
    assert msg["To"] == to
    assert "Sender <from@example.com>" in msg["From"]
    assert msg["Cc"] == "cc@example.com"
    
    # Check parts
    parts = msg.get_payload()
    assert len(parts) == 2
    assert parts[0].get_content_type() == "text/html"
    # Check PDF subtype
    assert parts[1].get_content_type() == "application/pdf"

@pytest.mark.anyio
async def test_send_email_orchestration(mock_db, active_config):
    mock_db.query().filter().first.return_value = active_config
    
    with patch("src.services.mail._send_sync") as mock_send_sync:
        await send_email(mock_db, "to@example.com", "Sub", "<html></html>")
        mock_send_sync.assert_called_once()
        # Verify the first argument to _send_sync was indeed our config
        args, _ = mock_send_sync.call_args
        assert args[0] == active_config


# ---------------------------------------------------------------------------
# _send_sync tests
# ---------------------------------------------------------------------------

@pytest.fixture
def smtp_cfg():
    """Minimal MagicMock config for _send_sync tests (avoids encrypt/decrypt)."""
    cfg = MagicMock()
    cfg.host = "smtp.example.com"
    cfg.port = 587
    cfg.username = "user"
    cfg.password = "secret"
    cfg.use_starttls = True
    return cfg


@pytest.fixture
def simple_msg():
    from email.mime.multipart import MIMEMultipart
    msg = MIMEMultipart()
    msg["To"] = "to@example.com"
    msg["Subject"] = "Test"
    return msg


def test_send_sync_uses_smtp_and_calls_starttls(smtp_cfg, simple_msg):
    """use_starttls=True on a non-465 port uses smtplib.SMTP and calls starttls()."""
    smtp_cfg.use_starttls = True
    smtp_cfg.port = 587

    with patch("smtplib.SMTP") as mock_smtp_cls, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl_cls:
        mock_server = mock_smtp_cls.return_value.__enter__.return_value

        _send_sync(smtp_cfg, simple_msg)

        mock_smtp_cls.assert_called_once_with(smtp_cfg.host, smtp_cfg.port, timeout=10)
        mock_smtp_ssl_cls.assert_not_called()
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with(smtp_cfg.username, smtp_cfg.password)
        mock_server.send_message.assert_called_once_with(simple_msg, to_addrs=["to@example.com"])


def test_send_sync_uses_smtp_ssl_when_use_starttls_false(smtp_cfg, simple_msg):
    """use_starttls=False uses smtplib.SMTP_SSL and does not call starttls()."""
    smtp_cfg.use_starttls = False
    smtp_cfg.port = 587

    with patch("smtplib.SMTP") as mock_smtp_cls, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl_cls:
        mock_server = mock_smtp_ssl_cls.return_value.__enter__.return_value

        _send_sync(smtp_cfg, simple_msg)

        mock_smtp_ssl_cls.assert_called_once_with(smtp_cfg.host, smtp_cfg.port, timeout=10)
        mock_smtp_cls.assert_not_called()
        mock_server.starttls.assert_not_called()
        mock_server.login.assert_called_once_with(smtp_cfg.username, smtp_cfg.password)
        mock_server.send_message.assert_called_once_with(simple_msg, to_addrs=["to@example.com"])


def test_send_sync_uses_smtp_ssl_for_port_465(smtp_cfg, simple_msg):
    """Port 465 triggers smtplib.SMTP_SSL even when use_starttls=True."""
    smtp_cfg.use_starttls = True
    smtp_cfg.port = 465

    with patch("smtplib.SMTP") as mock_smtp_cls, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl_cls:
        mock_server = mock_smtp_ssl_cls.return_value.__enter__.return_value

        _send_sync(smtp_cfg, simple_msg)

        mock_smtp_ssl_cls.assert_called_once_with(smtp_cfg.host, smtp_cfg.port, timeout=10)
        mock_smtp_cls.assert_not_called()
        mock_server.starttls.assert_not_called()
        mock_server.login.assert_called_once_with(smtp_cfg.username, smtp_cfg.password)
        mock_server.send_message.assert_called_once_with(simple_msg, to_addrs=["to@example.com"])


def test_send_sync_includes_cc_in_recipients(smtp_cfg):
    """Cc addresses are included in the to_addrs passed to send_message."""
    from email.mime.multipart import MIMEMultipart
    msg = MIMEMultipart()
    msg["To"] = "to@example.com"
    msg["Cc"] = "cc1@example.com, cc2@example.com"
    msg["Subject"] = "Test"

    smtp_cfg.use_starttls = True
    smtp_cfg.port = 587

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = mock_smtp_cls.return_value.__enter__.return_value

        _send_sync(smtp_cfg, msg)

        _, kwargs = mock_server.send_message.call_args
        assert kwargs["to_addrs"] == ["to@example.com", "cc1@example.com", "cc2@example.com"]
