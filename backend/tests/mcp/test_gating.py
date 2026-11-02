"""Scope gating, the write kill switch, and the profile filter.

The rule that matters: a tool filtered out of ``tools/list`` must also be
rejected in ``tools/call``. Never rely on the client not calling what it cannot
see.
"""

from __future__ import annotations

import pytest

from src.core.config import settings
from src.mcp_server.config import (
    SCOPE_ADMIN,
    SCOPE_READ,
    SCOPE_SEND_EMAIL,
    SCOPE_WRITE,
)
from tests.mcp.conftest import make_principal


@pytest.fixture
def writes_on(monkeypatch):
    monkeypatch.setattr(settings, "MCP_WRITE_ENABLED", True)
    return True


@pytest.fixture
def all_profile(monkeypatch):
    monkeypatch.setattr(settings, "MCP_DEFAULT_PROFILE", "all")
    return "all"


def names(tools):
    return {tool["name"] for tool in tools}


def test_read_only_token_lists_no_write_tools(mcp_call, company, writes_on, all_profile):
    reader = make_principal(company_id=company.id, scopes={SCOPE_READ})
    listed = names(mcp_call.list_tools(principal=reader))
    assert "invoices_list" in listed
    assert "invoices_create" not in listed
    assert "invoices_cancel" not in listed


def test_read_only_token_calling_a_write_tool_by_name_gets_a_tool_error(
    mcp_call, company, writes_on
):
    reader = make_principal(company_id=company.id, scopes={SCOPE_READ})
    body = mcp_call.call_tool("invoices_create", {"ledger_id": 1, "items": []}, principal=reader)
    result = body["result"]
    assert result["isError"] is True
    assert "invoicing:write" in result["content"][0]["text"]


def test_write_kill_switch_hides_writes_even_with_the_scope(mcp_call, company, monkeypatch, all_profile):
    monkeypatch.setattr(settings, "MCP_WRITE_ENABLED", False)
    writer = make_principal(company_id=company.id, scopes={SCOPE_READ, SCOPE_WRITE})
    listed = names(mcp_call.list_tools(principal=writer))
    assert "invoices_create" not in listed


def test_write_kill_switch_also_blocks_the_call(mcp_call, company, monkeypatch):
    monkeypatch.setattr(settings, "MCP_WRITE_ENABLED", False)
    writer = make_principal(company_id=company.id, scopes={SCOPE_READ, SCOPE_WRITE})
    result = mcp_call.call_tool("invoices_create", {}, principal=writer)["result"]
    assert result["isError"] is True
    assert "MCP_WRITE_ENABLED" in result["content"][0]["text"]


def test_admin_tools_require_the_admin_scope(mcp_call, company, writes_on, all_profile):
    writer = make_principal(company_id=company.id, scopes={SCOPE_READ, SCOPE_WRITE})
    listed = names(mcp_call.list_tools(principal=writer))
    assert "smtp_get_config" not in listed
    assert "users_create" not in listed

    admin = make_principal(
        company_id=company.id, scopes={SCOPE_READ, SCOPE_WRITE, SCOPE_ADMIN}
    )
    listed_admin = names(mcp_call.list_tools(principal=admin))
    assert "smtp_get_config" in listed_admin
    assert "users_create" in listed_admin


def test_email_tools_need_the_send_email_scope_not_write(mcp_call, company, writes_on, all_profile):
    writer = make_principal(company_id=company.id, scopes={SCOPE_READ, SCOPE_WRITE})
    assert "email_send_invoice" not in names(mcp_call.list_tools(principal=writer))

    sender = make_principal(company_id=company.id, scopes={SCOPE_READ, SCOPE_SEND_EMAIL})
    assert "email_send_invoice" in names(mcp_call.list_tools(principal=sender))


def test_email_tools_are_also_behind_the_write_kill_switch(mcp_call, company, monkeypatch, all_profile):
    monkeypatch.setattr(settings, "MCP_WRITE_ENABLED", False)
    sender = make_principal(company_id=company.id, scopes={SCOPE_READ, SCOPE_SEND_EMAIL})
    assert "email_send_invoice" not in names(mcp_call.list_tools(principal=sender))


def test_core_profile_is_much_smaller_than_all(mcp_call, company, writes_on, monkeypatch):
    principal = make_principal(company_id=company.id)

    monkeypatch.setattr(settings, "MCP_DEFAULT_PROFILE", "core")
    core = names(mcp_call.list_tools(principal=principal))

    monkeypatch.setattr(settings, "MCP_DEFAULT_PROFILE", "all")
    every = names(mcp_call.list_tools(principal=principal))

    assert core < every
    assert len(core) < 50
    assert len(every) > 100


def test_profile_query_parameter_overrides_the_default(mcp_call, company, writes_on, monkeypatch):
    monkeypatch.setattr(settings, "MCP_DEFAULT_PROFILE", "core")
    principal = make_principal(company_id=company.id)
    every = names(mcp_call.list_tools(principal=principal, query={"profile": "all"}))
    assert len(every) > 100


def test_tags_query_parameter_narrows_the_list(mcp_call, company, writes_on, all_profile):
    principal = make_principal(company_id=company.id)
    listed = names(mcp_call.list_tools(principal=principal, query={"tags": "invoices"}))
    assert "invoices_list" in listed
    assert "products_list" not in listed
    # search/fetch are always offered — they are how a client finds anything.
    assert {"search", "fetch"} <= listed


def test_search_and_fetch_are_always_listed(mcp_call, company):
    principal = make_principal(company_id=company.id, scopes={SCOPE_READ})
    listed = names(mcp_call.list_tools(principal=principal))
    assert {"search", "fetch"} <= listed


def test_unknown_tool_name_is_a_jsonrpc_invalid_params(mcp_call, company):
    body = mcp_call.call_tool("no_such_tool", {})
    assert body["error"]["code"] == -32602


def test_tool_list_stays_inside_a_sane_token_budget(mcp_call, company, writes_on, monkeypatch):
    """The tool list is prepended to every model turn, so its size is a running
    cost. Pruning `title` and null-unions is most of what keeps it here."""
    import json

    principal = make_principal(company_id=company.id)

    monkeypatch.setattr(settings, "MCP_DEFAULT_PROFILE", "core")
    core_bytes = len(json.dumps(mcp_call.list_tools(principal=principal)).encode())
    assert core_bytes < 60_000, f"core profile grew to {core_bytes} bytes"

    monkeypatch.setattr(settings, "MCP_DEFAULT_PROFILE", "all")
    all_bytes = len(json.dumps(mcp_call.list_tools(principal=principal)).encode())
    assert all_bytes < 150_000, f"full profile grew to {all_bytes} bytes"
