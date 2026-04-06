import pytest
from unittest.mock import MagicMock, patch
import asyncio
from src.services.mail import send_email, _get_active_smtp_config, _build_message
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
    config.use_tls = True
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
