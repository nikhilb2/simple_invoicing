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
