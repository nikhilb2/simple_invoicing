"""New passwords are limited to bcrypt's 72 bytes (issue #653)."""

import pytest
from pydantic import ValidationError

from src.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)


def _build(model, password):
    if model is ChangePasswordRequest:
        return model(current_password="OldPass@123", new_password=password)
    if model is VerifyEmailRequest:
        return model(token="t", full_name="Owner", new_password=password)
    return model(token="t", new_password=password)


MODELS = [ChangePasswordRequest, VerifyEmailRequest, ResetPasswordRequest]


@pytest.mark.parametrize("model", MODELS)
def test_72_bytes_is_accepted(model):
    assert _build(model, "a" * 72).new_password == "a" * 72


@pytest.mark.parametrize("model", MODELS)
def test_73_bytes_is_rejected(model):
    with pytest.raises(ValidationError, match="72 bytes"):
        _build(model, "a" * 73)


@pytest.mark.parametrize("model", MODELS)
def test_limit_counts_bytes_not_characters(model):
    assert _build(model, "é" * 36).new_password == "é" * 36
    with pytest.raises(ValidationError, match="72 bytes"):
        _build(model, "é" * 37)


@pytest.mark.parametrize("model", MODELS)
def test_short_password_still_rejected(model):
    with pytest.raises(ValidationError):
        _build(model, "short")


def test_login_accepts_existing_long_password():
    assert LoginRequest(email="a@example.com", password="a" * 100).password == "a" * 100
