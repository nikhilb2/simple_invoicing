import pytest
from unittest.mock import MagicMock, patch
import asyncio
import src.services.mail
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
    # We mock password property to avoid Fernet dependency in basic tests if needed, 
    # but here we'll just mock the server login anyway.
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
    attachments = [(b"data", "test.txt")]

    msg = _build_message(to, subject, html, from_e, from_n, attachments, cc)
    
    assert msg["Subject"] == subject
    assert msg["To"] == to
    assert "Sender <from@example.com>" in msg["From"]
    assert msg["Cc"] == "cc@example.com"
    
    # Check parts
    parts = msg.get_payload()
    # Multipart has child parts: 1 HTML text, 1 attachment
    assert len(parts) == 2
    assert parts[0].get_content_type() == "text/html"
    assert parts[1].get_content_type() == "application/octet-stream"

@pytest.mark.anyio
async def test_send_email_orchestration(mock_db, active_config):
    mock_db.query().filter().first.return_value = active_config
    
    # We patch run_in_executor directly on the loop to return an awaitable
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        # Mocking an awaitable response for lead executor
        future = asyncio.Future()
        future.set_result(None)
        mock_loop.run_in_executor.return_value = future
        mock_get_loop.return_value = mock_loop
        
        await send_email(mock_db, "to@example.com", "Sub", "<html></html>")
        
        assert mock_loop.run_in_executor.called
        # Verify it was called with the correct send_sync function partial
        # args[0] is None (default executor), args[1] is the partial
        args, _ = mock_loop.run_in_executor.call_args
        assert args[0] is None
        assert args[1].func == src.services.mail._send_sync
