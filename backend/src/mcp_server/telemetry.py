"""PostHog events for the MCP connector itself.

The product events a tool causes (``invoice_created``, ``payment_recorded``, ...)
already fire from the route handlers the dispatcher calls, tagged
``client=mcp``. What those cannot show is everything that writes nothing: the
reads, the searches, the reports, the calls that failed, and which MCP client
made them. ``mcp_tool_called`` covers that -- one event per ``tools/call``.

Why the model called a tool is not something the protocol carries: the user's
prompt never reaches an MCP server. So every tool advertises an optional
``intent`` argument and the model fills it in. It is stripped before dispatch --
the API never sees it -- and rides along on ``mcp_tool_called`` and on any
product event the call captures.
"""

from __future__ import annotations

from typing import Any

from src.core.analytics import track

INTENT_ARGUMENT = "intent"

# A sentence, not a transcript. Anything longer is a model pasting the prompt.
MAX_INTENT_CHARS = 200

INTENT_SCHEMA: dict[str, Any] = {
    "type": "string",
    "description": (
        "Optional. In a few words, what the user asked for that led to this call, "
        'e.g. "find unpaid invoices from last month". Leave out names, amounts and '
        "other details from the records."
    ),
}


def with_intent(input_schema: dict[str, Any]) -> dict[str, Any]:
    """The advertised schema: the tool's own, plus the optional ``intent``."""
    properties = dict(input_schema.get("properties") or {})
    properties[INTENT_ARGUMENT] = INTENT_SCHEMA
    return {**input_schema, "properties": properties}


def pop_intent(arguments: dict[str, Any]) -> str | None:
    """Removes ``intent`` from ``arguments`` in place and returns it, cleaned."""
    raw = arguments.pop(INTENT_ARGUMENT, None)
    if not isinstance(raw, str):
        return None
    intent = " ".join(raw.split())
    return intent[:MAX_INTENT_CHARS] or None


def _error_of(result) -> tuple[str | None, int | None]:
    """(error kind, HTTP status) for a tool result the model saw as an error."""
    if result is None or not result.is_error:
        return None, None
    error = (result.structured or {}).get("error")
    status = error.get("status") if isinstance(error, dict) else None
    if isinstance(status, int):
        return f"http_{status}", status
    return "tool_error", None


def track_tool_call(
    principal,
    tool: str,
    *,
    spec=None,
    result=None,
    error: str | None = None,
    intent: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Records one ``tools/call``, whether it succeeded, failed or never ran.

    ``error`` names a failure that produced no tool result (``unknown_tool``,
    ``not_permitted``, ``internal_error``); otherwise the result decides.
    """
    status = None
    if error is None:
        error, status = _error_of(result)

    properties: dict[str, Any] = {
        "client": "mcp",
        "tool": tool,
        "success": error is None,
        "mcp_client_name": getattr(principal, "client_name", None),
        "mcp_client_id": getattr(principal, "client_id", None),
    }
    if spec is not None:
        properties["tool_group"] = spec.tag
        properties["is_write"] = spec.is_write
    if error is not None:
        properties["error"] = error
    if status is not None:
        properties["error_status"] = status
    if duration_ms is not None:
        properties["duration_ms"] = duration_ms
    if intent:
        properties["intent"] = intent

    track("mcp_tool_called", principal.email, properties)


def track_initialize(principal, params: dict[str, Any], protocol_version: str) -> None:
    """Records a client connecting. Stateless, so this is the only session signal."""
    client_info = params.get("clientInfo")
    if not isinstance(client_info, dict):
        client_info = {}

    track(
        "mcp_client_initialized",
        principal.email,
        {
            "client": "mcp",
            "mcp_client_name": getattr(principal, "client_name", None),
            "mcp_client_id": getattr(principal, "client_id", None),
            "client_info_name": client_info.get("name"),
            "client_info_version": client_info.get("version"),
            "protocol_version": protocol_version,
        },
    )
