"""DEPLOYMENT_MODE and the signup switches derived from it."""

import logging

import pytest
from pydantic import ValidationError

from src.core.config import Settings

BASE = {"DATABASE_URL": "sqlite:///./test.db", "SECRET_KEY": "testsecret"}


def test_defaults_are_single_tenant_with_signup_off():
    s = Settings(**BASE)

    assert s.DEPLOYMENT_MODE == "single_tenant"
    assert s.is_shared_hosting is False
    assert s.password_signup_enabled is False
    assert s.google_auth_enabled is False
    assert s.google_signup_enabled is False
    assert s.MAX_COMPANIES_PER_USER == 3
    assert s.PLATFORM_SMTP_PORT == 587
    assert s.PLATFORM_SMTP_FROM_NAME == "Simple Invoicing"
    assert s.PLATFORM_SMTP_USE_STARTTLS is True
    assert s.MIGRATION_DATABASE_URL is None


def test_unknown_deployment_mode_is_rejected():
    with pytest.raises(ValidationError):
        Settings(**BASE, DEPLOYMENT_MODE="multi")


def test_password_signup_needs_shared_hosting_and_platform_smtp():
    assert Settings(**BASE, DEPLOYMENT_MODE="shared_hosting", PLATFORM_SMTP_HOST="smtp.example.com").password_signup_enabled
    assert not Settings(**BASE, DEPLOYMENT_MODE="shared_hosting").password_signup_enabled
    assert not Settings(**BASE, PLATFORM_SMTP_HOST="smtp.example.com").password_signup_enabled


def test_google_login_works_in_any_mode_but_signup_needs_shared_hosting():
    google = {"OAUTH_GOOGLE_CLIENT_ID": "id", "OAUTH_GOOGLE_CLIENT_SECRET": "secret"}

    single = Settings(**BASE, **google)
    assert single.google_auth_enabled is True
    assert single.google_signup_enabled is False

    # Google proves the address itself, so no platform SMTP is needed.
    shared = Settings(**BASE, **google, DEPLOYMENT_MODE="shared_hosting")
    assert shared.google_signup_enabled is True

    half = Settings(**BASE, OAUTH_GOOGLE_CLIENT_ID="id", DEPLOYMENT_MODE="shared_hosting")
    assert half.google_auth_enabled is False
    assert half.google_signup_enabled is False


def test_shared_hosting_without_platform_smtp_warns_signup_disabled(caplog):
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        Settings(**BASE, DEPLOYMENT_MODE="shared_hosting")

    assert "Signup disabled" in caplog.text
    assert "PLATFORM_SMTP_HOST" in caplog.text


@pytest.mark.parametrize(
    "extra",
    [
        {},  # single tenant never offers signup, so there is nothing to warn about
        {"DEPLOYMENT_MODE": "shared_hosting", "PLATFORM_SMTP_HOST": "smtp.example.com"},
    ],
)
def test_no_signup_warning_when_not_applicable(caplog, extra):
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        Settings(**BASE, **extra)

    assert "Signup disabled" not in caplog.text
