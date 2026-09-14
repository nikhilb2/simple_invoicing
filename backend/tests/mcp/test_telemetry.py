"""PostHog sees MCP activity: every tool call, and which tool caused each write."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.core import analytics
from src.core.config import settings
from src.mcp_server.telemetry import MAX_INTENT_CHARS
from tests.api.test_analytics_events import RecordingClient
from tests.mcp.conftest import make_principal
from tests.mcp.test_dispatch import _ledger_payload


@pytest.fixture
def events(monkeypatch):
    recorder = RecordingClient()
    monkeypatch.setattr(analytics, "_client", recorder)
    monkeypatch.setattr(analytics, "_init_attempted", True)
    yield recorder
    analytics.bind_request(None, "api")


@pytest.fixture
def writes_on(monkeypatch):
    monkeypatch.setattr(settings, "MCP_WRITE_ENABLED", True)


def _find(events, name):
    return [e for e in events.captured if e[0] == name]


def test_every_tool_advertises_an_optional_intent(mcp_call):
    for tool in mcp_call.list_tools(query={"profile": "all"}):
        schema = tool["inputSchema"]
        assert "intent" in schema["properties"], tool["name"]
        assert "intent" not in schema.get("required", []), tool["name"]


def test_a_read_captures_mcp_tool_called(mcp_call, company, events):
    principal = replace(make_principal(company_id=company.id, client_id="abc"), client_name="Claude")

    mcp_call.call_tool(
        "ledgers_list",
        {"intent": "  see who we\n sell to  "},
        principal=principal,
    )

    (_, distinct_id, props), = _find(events, "mcp_tool_called")
    assert distinct_id == principal.email
    assert props["client"] == "mcp"
    assert props["tool"] == "ledgers_list"
    assert props["success"] is True
    assert props["is_write"] is False
    assert props["mcp_client_name"] == "Claude"
    assert props["mcp_client_id"] == "abc"
    assert props["intent"] == "see who we sell to"
    assert isinstance(props["duration_ms"], int)


def test_intent_is_not_passed_to_the_api(mcp_call, company, events):
    result = mcp_call.call_tool("ledgers_list", {"intent": "anything"})["result"]
    assert result["isError"] is False


def test_intent_is_truncated(mcp_call, company, events):
    mcp_call.call_tool("ledgers_list", {"intent": "x" * 1000})

    (_, _, props), = _find(events, "mcp_tool_called")
    assert len(props["intent"]) == MAX_INTENT_CHARS


def test_a_write_tags_its_product_event_with_the_tool(mcp_call, company, events, writes_on):
    result = mcp_call.call_tool(
        "ledgers_create",
        {**_ledger_payload("Via Claude"), "intent": "add a new customer"},
    )["result"]
    assert result["isError"] is False, result

    (_, _, props), = _find(events, "ledger_created")
    assert props["client"] == "mcp"
    assert props["mcp_tool"] == "ledgers_create"
    assert props["mcp_intent"] == "add a new customer"

    (_, _, call), = _find(events, "mcp_tool_called")
    assert call["is_write"] is True


def test_a_failed_call_records_its_status(mcp_call, company, events):
    mcp_call.call_tool("ledgers_get", {"ledger_id": 999999})

    (_, _, props), = _find(events, "mcp_tool_called")
    assert props["success"] is False
    assert props["error"] == "http_404"
    assert props["error_status"] == 404


def test_an_unknown_tool_is_recorded(mcp_call, company, events):
    mcp_call.call_tool("no_such_tool", {})

    (_, _, props), = _find(events, "mcp_tool_called")
    assert props["tool"] == "no_such_tool"
    assert props["error"] == "unknown_tool"


def test_the_tool_does_not_leak_onto_later_events(mcp_call, client, company, events):
    mcp_call.call_tool("ledgers_list", {"intent": "look around"})
    events.captured.clear()

    client.post(
        "/api/ledgers/",
        json=_ledger_payload("Typed In"),
        headers={"X-Company-Id": str(company.id)},
    )

    (_, _, props), = _find(events, "ledger_created")
    assert "mcp_tool" not in props
    assert "mcp_intent" not in props


def test_initialize_records_the_client(mcp_call, company, events):
    mcp_call.request(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "claude-ai", "version": "0.1.0"},
            "capabilities": {},
        },
    )

    (_, _, props), = _find(events, "mcp_client_initialized")
    assert props["client_info_name"] == "claude-ai"
    assert props["client_info_version"] == "0.1.0"
    assert props["protocol_version"] == "2025-06-18"
