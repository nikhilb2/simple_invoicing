import pytest
import os
from pydantic import ValidationError
from src.core.config import Settings

def test_config_production_requires_smtp_key():
    # Make sure we don't accidentally load it from the host environment
    env = {
        "DATABASE_URL": "sqlite:///./test.db",
        "SECRET_KEY": "testsecret",
        "ENVIRONMENT": "production"
    }

    # Should raise ValueError or ValidationError missing SMTP_ENCRYPTION_KEY
    with pytest.raises(ValueError, match="SMTP_ENCRYPTION_KEY is required in production environment"):
        Settings(**env)

def test_config_development_allows_missing_smtp_key():
    env = {
        "DATABASE_URL": "sqlite:///./test.db",
        "SECRET_KEY": "testsecret",
        "ENVIRONMENT": "development"
    }

    # Should not raise an error
    settings = Settings(**env)
    assert settings.SMTP_ENCRYPTION_KEY is None


def test_production_disables_unconfigured_mcp_with_logged_warning(caplog, capsys):
    """MCP misconfiguration must be visible through standard warning logging."""
    import logging

    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        settings = Settings(
            DATABASE_URL="sqlite:///./test.db",
            SECRET_KEY="testsecret",
            ENVIRONMENT="production",
            SMTP_ENCRYPTION_KEY="test-key",
            MCP_ENABLED=True,
            PUBLIC_API_BASE_URL="http://localhost:8000",
            PUBLIC_APP_BASE_URL="http://localhost:5173",
        )

    assert settings.MCP_ENABLED is False
    assert "MCP disabled" in caplog.text
    assert "PUBLIC_API_BASE_URL and PUBLIC_APP_BASE_URL" in caplog.text
    assert capsys.readouterr().out == ""


def test_configured_production_mcp_emits_no_warning(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        settings = Settings(
            DATABASE_URL="sqlite:///./test.db",
            SECRET_KEY="testsecret",
            ENVIRONMENT="production",
            SMTP_ENCRYPTION_KEY="test-key",
            MCP_ENABLED=True,
            PUBLIC_API_BASE_URL="https://api.example.com",
            PUBLIC_APP_BASE_URL="https://app.example.com",
        )

    assert settings.MCP_ENABLED is True
    assert "MCP disabled" not in caplog.text


def test_backend_startup_banner_remains_visible():
    """Preserve the banner on stdout rather than relying on Uvicorn INFO logging."""
    import subprocess
    import sys
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "DATABASE_URL": "sqlite:///./test.db",
        "SECRET_KEY": "testsecret",
        "ENVIRONMENT": "development",
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [sys.executable, "-c", "from src.core.config import settings"],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=15,
    )

    assert "Backend running in development mode" in result.stdout
