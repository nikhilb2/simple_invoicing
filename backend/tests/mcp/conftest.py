"""Fixtures for the MCP server tests.

The MCP endpoint is registered here rather than relying on ``app_main`` so the
suite is independent of when the integration wiring lands.

``resolve_principal`` is patched on :mod:`src.mcp_server.transport` — the module
that *calls* it — which is the whole reason it is a plain module-level function
and not a FastAPI dependency.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from src.mcp_server import register_mcp
from src.mcp_server import transport as mcp_transport
from src.mcp_server.config import ALL_SCOPES
from src.mcp_server.principal import Principal, Unauthenticated
from src.models.company import CompanyProfile
from src.models.user import User, UserRole

from app_main import app

register_mcp(app)


DEFAULT_SCOPES = frozenset(ALL_SCOPES)


def make_principal(
    *,
    user_id: int = 1,
    email: str = "test@example.com",
    role: str = "admin",
    company_id: int | None = 1,
    scopes=DEFAULT_SCOPES,
    client_id: str | None = "test-client",
) -> Principal:
    return Principal(
        user_id=user_id,
        email=email,
        role=role,
        company_id=company_id,
        scopes=frozenset(scopes),
        client_id=client_id,
    )


@contextmanager
def override_principal(principal: Principal | None = None, **kwargs):
    """Patch ``transport.resolve_principal`` for the duration of the block.

    Pass ``principal=None`` with no kwargs to simulate an unauthenticated caller.
    """
    original = mcp_transport.resolve_principal
    resolved: Principal | None = None

    if principal is None and not kwargs:

        async def _resolve(request):
            raise Unauthenticated("Missing bearer token")

    else:
        resolved = principal if principal is not None else make_principal(**kwargs)

        async def _resolve(request):
            return resolved

    mcp_transport.resolve_principal = _resolve
    try:
        yield resolved
    finally:
        mcp_transport.resolve_principal = original


@pytest.fixture
def mcp_principal(company):
    return make_principal(company_id=company.id)


@pytest.fixture
def company(db_session):
    """A company row for tools to act on."""
    profile = CompanyProfile(
        name="Test Co",
        address="1 Test Street",
        gst="27AAAAA0000A1Z5",
        phone_number="1234567890",
        currency_code="INR",
        email="co@example.com",
        website="",
        bank_name="",
        branch_name="",
        account_name="",
        account_number="",
        ifsc_code="",
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def db_user(db_session):
    user = User(
        email="test@example.com",
        full_name="Test Admin",
        hashed_password="x",
        role=UserRole.admin,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


class MCPCaller:
    """Thin JSON-RPC caller over the TestClient."""

    def __init__(self, client, principal: Principal):
        self.client = client
        self.principal = principal
        self._id = 0

    def raw(self, payload, *, principal: Principal | None = None, headers=None, path="/mcp", params=None):
        with override_principal(principal if principal is not None else self.principal):
            return self.client.post(
                path,
                content=json.dumps(payload) if not isinstance(payload, (str, bytes)) else payload,
                headers={"Content-Type": "application/json", **(headers or {})},
                params=params,
            )

    def request(self, method, params=None, *, principal: Principal | None = None, query=None, path="/mcp"):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        response = self.raw(payload, principal=principal, path=path, params=query)
        assert response.status_code == 200, response.text
        return response.json()

    def call_tool(self, name, arguments=None, *, principal: Principal | None = None):
        return self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            principal=principal,
        )

    def list_tools(self, *, principal: Principal | None = None, query=None):
        body = self.request("tools/list", {}, principal=principal, query=query)
        return body["result"]["tools"]


@pytest.fixture
def mcp_call(client, mcp_principal):
    return MCPCaller(client, mcp_principal)


def tool_result(body):
    """Unwrap a JSON-RPC tools/call response into its MCP result."""
    assert "result" in body, body
    return body["result"]


def result_text(body) -> str:
    return "\n".join(part.get("text", "") for part in tool_result(body).get("content", []))
