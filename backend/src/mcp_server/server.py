"""JSON-RPC method handlers for the MCP server.

A stateless server needs exactly five methods: ``initialize``,
``notifications/initialized``, ``tools/list``, ``tools/call`` and ``ping``.
Everything else is answered with ``-32601 Method not found`` at HTTP 200 —
JSON-RPC errors are *not* HTTP errors, and only the auth gate in
:mod:`src.mcp_server.transport` produces a real HTTP status.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.analytics import mcp_tool_context
from src.mcp_server.config import (
    LATEST_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_TITLE,
    SERVER_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from src.mcp_server.dispatch import DispatcherBug, dispatch, text_result
from src.mcp_server.errors import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    rpc_error,
    rpc_result,
)
from src.mcp_server.principal import Principal
from src.mcp_server.registry import ToolRegistry
from src.mcp_server.telemetry import pop_intent, track_initialize, track_tool_call

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Tools for a GST invoicing and inventory system. Start with `search` to find a record "
    "by name or number, then `fetch` its id for the full document. List tools accept "
    "`page`/`page_size` and most accept a free-text `search` filter. Every call acts on the "
    "company this connection was authorised for unless you pass `company_id`."
)


def negotiate_protocol_version(requested: str | None) -> str:
    """Echo the client's version when we speak it, else offer our newest."""
    if requested and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def is_notification(message: dict[str, Any]) -> bool:
    return "id" not in message


async def handle_message(
    registry: ToolRegistry,
    message: Any,
    principal: Principal,
    *,
    profile: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. Returns None for notifications."""
    if not isinstance(message, dict):
        return rpc_error(None, INVALID_REQUEST, "Invalid Request: expected a JSON-RPC object")

    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if not isinstance(method, str):
        if is_notification(message):
            return None
        return rpc_error(request_id, INVALID_REQUEST, "Invalid Request: missing `method`")

    if method.startswith("notifications/"):
        # initialized / cancelled / progress — nothing to do in a stateless server.
        return None

    # A message with no `id` is a notification and must never be answered, even
    # when it names a request method.
    notification = is_notification(message)

    try:
        if method == "initialize":
            result = _initialize(params)
            track_initialize(principal, params, result["protocolVersion"])
            return _answer(notification, rpc_result(request_id, result))
        if method == "ping":
            return _answer(notification, rpc_result(request_id, {}))
        if method == "tools/list":
            return _answer(
                notification, rpc_result(request_id, _tools_list(registry, principal, profile, tags))
            )
        if method == "tools/call":
            return _answer(
                notification, await _tools_call(registry, principal, request_id, params)
            )
    except DispatcherBug as exc:
        # We minted the internal token, so this is a server bug. It must not
        # become an outer 401, or the client re-runs the OAuth flow forever.
        logger.error("MCP dispatcher bug: %s", exc)
        return _answer(
            notification,
            rpc_error(request_id, INTERNAL_ERROR, "Internal server error while running the tool"),
        )
    except Exception:  # noqa: BLE001 - a handler crash must not kill the session
        logger.exception("MCP: unhandled error in method %s", method)
        return _answer(notification, rpc_error(request_id, INTERNAL_ERROR, "Internal server error"))

    return _answer(notification, rpc_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}"))


def _answer(notification: bool, response: dict[str, Any]) -> dict[str, Any] | None:
    return None if notification else response


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": negotiate_protocol_version(params.get("protocolVersion")),
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": SERVER_NAME,
            "title": SERVER_TITLE,
            "version": SERVER_VERSION,
        },
        "instructions": INSTRUCTIONS,
    }


def _tools_list(
    registry: ToolRegistry,
    principal: Principal,
    profile: str | None,
    tags: list[str] | None,
) -> dict[str, Any]:
    tools = registry.visible_tools(principal, profile=profile, tags=tags)
    return {"tools": [spec.to_mcp() for spec in tools]}


async def _tools_call(
    registry: ToolRegistry,
    principal: Principal,
    request_id: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str) or not name:
        return rpc_error(request_id, INVALID_PARAMS, "tools/call requires a `name`")
    if not isinstance(arguments, dict):
        return rpc_error(request_id, INVALID_PARAMS, "`arguments` must be an object")

    # Analytics only, and never an argument the API sees.
    arguments = dict(arguments)
    intent = pop_intent(arguments)

    spec = registry.get(name)
    if spec is None:
        track_tool_call(principal, name, error="unknown_tool", intent=intent)
        return rpc_error(request_id, INVALID_PARAMS, f"Unknown tool: {name}")

    # Never rely on the client not calling what it cannot see.
    visible, reason = registry.is_visible(spec, principal)
    if not visible:
        track_tool_call(principal, spec.name, spec=spec, error="not_permitted", intent=intent)
        return rpc_result(request_id, text_result(reason or "This tool is not available.", is_error=True).to_mcp())

    started = time.monotonic()
    try:
        with mcp_tool_context(spec.name, intent):
            if spec.handler is not None:
                from src.mcp_server.connector import HANDLERS

                result = await HANDLERS[spec.handler](registry, principal, arguments)
            else:
                result = await dispatch(registry, spec, arguments, principal)
    except Exception:
        track_tool_call(
            principal,
            spec.name,
            spec=spec,
            error="internal_error",
            intent=intent,
            duration_ms=_elapsed_ms(started),
        )
        raise

    track_tool_call(
        principal,
        spec.name,
        spec=spec,
        result=result,
        intent=intent,
        duration_ms=_elapsed_ms(started),
    )
    return rpc_result(request_id, result.to_mcp())


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
