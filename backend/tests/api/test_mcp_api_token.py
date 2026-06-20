"""Tests for static MCP API token authentication."""

import pytest
from unittest.mock import patch

from src.api.deps import get_current_user
from src.models.user import User, UserRole
from src.core.security import get_password_hash
from app_main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client_without_auth_override():
    """TestClient without the global get_current_user override from conftest.py."""
    # Remove the global override from conftest
    saved_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        yield TestClient(app)
    finally:
        if saved_override:
            app.dependency_overrides[get_current_user] = saved_override


def test_static_mcp_token_auth_success(client_without_auth_override, db_session):
    """Bearer with MCP_API_TOKEN should authenticate as admin without JWT."""
    # Seed an admin user
    admin = User(
        email="admin@example.com",
        full_name="Admin User",
        role=UserRole.admin,
        hashed_password=get_password_hash("secret"),
    )
    db_session.add(admin)
    db_session.commit()

    static_token = "test-static-token-abc123"

    with patch("src.api.deps.settings.MCP_API_TOKEN", static_token):
        response = client_without_auth_override.get(
            "/api/products/",
            headers={"Authorization": f"Bearer {static_token}"},
        )
        assert response.status_code == 200


def test_static_mcp_token_auth_invalid_token(client_without_auth_override, db_session):
    """Wrong bearer token should still return 401."""
    # Seed an admin user
    admin = User(
        email="admin@example.com",
        full_name="Admin User",
        role=UserRole.admin,
        hashed_password=get_password_hash("secret"),
    )
    db_session.add(admin)
    db_session.commit()

    with patch("src.api.deps.settings.MCP_API_TOKEN", "correct-token"):
        response = client_without_auth_override.get(
            "/api/products/",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401


def test_static_mcp_token_no_token_configured(client_without_auth_override, db_session):
    """When MCP_API_TOKEN is not set, static auth path is skipped, normal JWT required."""
    # Seed an admin user
    admin = User(
        email="admin@example.com",
        full_name="Admin User",
        role=UserRole.admin,
        hashed_password=get_password_hash("secret"),
    )
    db_session.add(admin)
    db_session.commit()

    with patch("src.api.deps.settings.MCP_API_TOKEN", None):
        # Passing any token without MCP_API_TOKEN set should fall through to JWT and fail
        response = client_without_auth_override.get(
            "/api/products/",
            headers={"Authorization": "Bearer some-random-token"},
        )
        assert response.status_code == 401


def test_static_mcp_token_no_users_in_db(client_without_auth_override):
    """When MCP_API_TOKEN matches but DB has no users, return 401."""
    with patch("src.api.deps.settings.MCP_API_TOKEN", "token-no-users"):
        response = client_without_auth_override.get(
            "/api/products/",
            headers={"Authorization": "Bearer token-no-users"},
        )
        assert response.status_code == 401
        assert "No users found" in response.json()["detail"]


def test_mcp_token_returns_admin_not_staff(client_without_auth_override, db_session):
    """MCP token should prefer admin user even when other users exist."""
    # Seed staff user first (lower id)
    staff = User(
        email="staff@example.com",
        full_name="Staff User",
        role=UserRole.staff,
        hashed_password=get_password_hash("secret"),
    )
    db_session.add(staff)
    # Seed admin after
    admin = User(
        email="admin@example.com",
        full_name="Admin User",
        role=UserRole.admin,
        hashed_password=get_password_hash("secret"),
    )
    db_session.add(admin)
    db_session.commit()

    static_token = "prefer-admin-token"

    with patch("src.api.deps.settings.MCP_API_TOKEN", static_token):
        response = client_without_auth_override.get(
            "/api/products/",
            headers={"Authorization": f"Bearer {static_token}"},
        )
        assert response.status_code == 200
