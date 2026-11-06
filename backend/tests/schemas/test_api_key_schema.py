"""Schema-level tests for ApiKeyCreate (issue #668).

The API-level regression lives in tests/api/test_api_keys.py; these run the
validator directly so they execute without the app stack.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.schemas.api_key import ApiKeyCreate


def _create(name: str) -> ApiKeyCreate:
    return ApiKeyCreate(
        name=name,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )


def test_name_with_surrounding_spaces_is_stripped():
    assert _create("  CI key  ").name == "CI key"


def test_whitespace_only_name_is_rejected():
    with pytest.raises(ValidationError):
        _create("   ")


def test_tabs_only_name_is_rejected():
    with pytest.raises(ValidationError):
        _create("\t\t")


def test_empty_name_is_rejected():
    with pytest.raises(ValidationError):
        _create("")


def test_normal_name_is_unchanged():
    assert _create("Deploy key").name == "Deploy key"
