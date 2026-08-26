"""Execute one ``tools/call`` against the real HTTP endpoint, in process.

Dispatching over HTTP rather than calling handlers or services directly is the
whole point: ``get_current_user``, ``get_active_company``, ``require_roles``,
pydantic validation, ``response_model`` serialisation and every per-handler
tenant filter run exactly as they do for the REST API, so MCP cannot drift from
the API's behaviour or its authorization rules. Each in-process request also gets
its own ``get_db`` session, isolated from the MCP request's own.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx

from src.core.security import create_access_token
from src.mcp_server.config import (
    BINARY_CONTENT_TYPES,
    INTERNAL_TOKEN_TTL_SECONDS,
    MCP_TOOL_HEADER,
)
from src.mcp_server.errors import flatten_detail
from src.mcp_server.principal import Principal
from src.mcp_server.registry import ToolRegistry, ToolSpec
from src.mcp_server.truncation import clamp_page_size, truncate_payload, truncate_text

logger = logging.getLogger(__name__)


class DispatcherBug(RuntimeError):
    """The dispatcher produced a request the app rejected as unauthenticated.

    We minted the internal token ourselves, so a 401 coming back is our fault,
    never the caller's. It must surface as a JSON-RPC internal error — turning it
    into an outer HTTP 401 would send the client round the OAuth flow forever.
    """


@dataclass
class ToolResult:
    content: list[dict[str, Any]] = field(default_factory=list)
    structured: dict[str, Any] | None = None
    is_error: bool = False

    def to_mcp(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"content": self.content, "isError": self.is_error}
        if self.structured is not None:
            payload["structuredContent"] = self.structured
        return payload


def text_result(text: str, *, is_error: bool = False, structured: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(content=[{"type": "text", "text": text}], structured=structured, is_error=is_error)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=None, default=str, ensure_ascii=False)


def _as_structured(payload: Any) -> dict[str, Any]:
    """MCP requires ``structuredContent`` to be a JSON object."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"items": payload}
    return {"value": payload}


def split_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> tuple[dict, dict, Any, int | None, list[str]]:
    """Re-split the flat argument bag into path / query / body / company_id."""
    plan = spec.plan
    path_values: dict[str, Any] = {}
    query: dict[str, Any] = {}
    body: Any = None
    company_id: int | None = None

    known = set(plan.path_params) | set(plan.query_params) | set(plan.body_params)
    if plan.body_passthrough:
        known.add("body")
    if plan.accepts_company:
        known.add("company_id")
    unknown = sorted(set(arguments) - known)

    for name in plan.path_params:
        if name in arguments:
            path_values[name] = arguments[name]
    for name in plan.query_params:
        if name in arguments and arguments[name] is not None:
            query[name] = arguments[name]

    if plan.body_passthrough:
        if "body" in arguments:
            body = arguments["body"]
    elif plan.body_params:
        supplied = {name: arguments[name] for name in plan.body_params if name in arguments}
        if supplied or plan.body_required:
            body = supplied

    if plan.accepts_company and arguments.get("company_id") is not None:
        try:
            company_id = int(arguments["company_id"])
        except (TypeError, ValueError):
            company_id = None

    return path_values, query, body, company_id, unknown


def _build_url(spec: ToolSpec, path_values: dict[str, Any]) -> str:
    url = spec.path
    for name in spec.plan.path_params:
        placeholder = "{" + name + "}"
        if name not in path_values:
            raise KeyError(name)
        url = url.replace(placeholder, str(path_values[name]))
    return url


def _normalise_query(query: dict[str, Any]) -> list[tuple[str, str]]:
    """httpx wants scalars or repeated keys; booleans must go over as json-ish text."""
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        if isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            for item in value:
                pairs.append((key, "true" if item is True else "false" if item is False else str(item)))
        elif isinstance(value, dict):
            pairs.append((key, _dumps(value)))
        else:
            pairs.append((key, str(value)))
    return pairs


async def dispatch(
    registry: ToolRegistry,
    spec: ToolSpec,
    arguments: dict[str, Any],
    principal: Principal,
) -> ToolResult:
    """Run one tool and shape the response for a model to read."""
    arguments = dict(arguments or {})
    arguments, page_clamped = clamp_page_size(arguments)

    path_values, query, body, company_id, unknown = split_arguments(spec, arguments)
    if unknown:
        valid = sorted(spec.input_schema.get("properties", {}))
        return text_result(
            f"Unknown argument(s): {', '.join(unknown)}. Valid arguments: {', '.join(valid) or 'none'}.",
            is_error=True,
        )

    try:
        url = _build_url(spec, path_values)
    except KeyError as exc:
        return text_result(f"Missing required argument: {exc.args[0]}", is_error=True)

    try:
        response = await raw_request(
            registry,
            spec.name,
            principal,
            spec.method,
            url,
            params=_normalise_query(query),
            json_body=body,
            company_id=company_id,
        )
    except httpx.HTTPError as exc:  # pragma: no cover - ASGITransport rarely raises
        logger.exception("MCP dispatch transport failure for %s", spec.name)
        return text_result(f"Transport error calling {spec.name}: {exc}", is_error=True)

    return build_result(spec, response, page_clamped=page_clamped)


def internal_headers(tool_name: str, principal: Principal, company_id: int | None = None) -> dict[str, str]:
    """Headers for one in-process call, including the 60-second internal token."""
    effective_company = company_id if company_id is not None else principal.company_id
    headers = {
        "Authorization": "Bearer "
        + create_access_token(
            principal.email,
            expires_delta=timedelta(seconds=INTERNAL_TOKEN_TTL_SECONDS),
            extra_claims={"src": "mcp", "tool": tool_name},
        ),
        # Audit breadcrumb, and the flag `get_active_company` keys off so a
        # read-only tool never persists a new active company for the human.
        MCP_TOOL_HEADER: tool_name,
        "Accept": "application/json, text/csv;q=0.9, */*;q=0.5",
    }
    if effective_company is not None:
        headers["X-Company-Id"] = str(effective_company)
    return headers


async def raw_request(
    registry: ToolRegistry,
    tool_name: str,
    principal: Principal,
    method: str,
    url: str,
    *,
    params: Any = None,
    json_body: Any = None,
    company_id: int | None = None,
) -> httpx.Response:
    """Perform one authenticated in-process request. Raises on an inner 401."""
    kwargs: dict[str, Any] = {
        "params": params if params is not None else [],
        "headers": internal_headers(tool_name, principal, company_id),
    }
    if json_body is not None:
        kwargs["json"] = json_body

    response = await registry.client.request(method, url, **kwargs)

    if response.status_code == 401:
        # We minted the token ourselves, so this can only be a server bug. It
        # must never escape as an outer HTTP 401, or the client will loop the
        # OAuth flow forever chasing an authorization problem that isn't one.
        logger.error(
            "MCP dispatch got HTTP 401 from %s %s for tool %s — the internal token this "
            "dispatcher minted was rejected. This is a server bug, not a client auth problem.",
            method,
            url,
            tool_name,
        )
        raise DispatcherBug(f"Internal authentication failed while running {tool_name}")

    return response


def build_result(spec: ToolSpec, response: httpx.Response, *, page_clamped: bool = False) -> ToolResult:
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()

    if response.status_code >= 400:
        return _error_result(spec, response, content_type)

    if any(content_type.startswith(binary) for binary in BINARY_CONTENT_TYPES):
        # Never base64 a multi-megabyte PDF into the model's context.
        payload = {
            "content_type": content_type,
            "bytes": len(response.content),
            "note": (
                f"{spec.name} produced a {content_type} document ({len(response.content)} bytes). "
                "Binary documents are not returned over MCP — open or download it from the app."
            ),
        }
        return ToolResult(content=[{"type": "text", "text": _dumps(payload)}], structured=payload)

    if content_type.startswith("text/csv") or content_type in ("text/plain", "text/tab-separated-values"):
        text, note = truncate_text(response.text)
        return ToolResult(content=[{"type": "text", "text": text}], structured={"csv": text, "_truncated": note} if note else {"csv": text})

    if content_type.startswith("application/json") or not content_type:
        try:
            payload = response.json() if response.content else None
        except ValueError:
            return text_result(response.text or "")
        payload, note = truncate_payload(payload)
        structured = _as_structured(payload)
        if note is not None and "_truncated" not in structured:
            # A bare-list response is wrapped into {"items": [...]}, which would
            # otherwise drop the note telling the model that rows are missing.
            structured = {**structured, "_truncated": note}
        if page_clamped:
            structured = {
                **structured,
                "_page_size_clamped": (
                    "page_size was reduced to keep the response inside the model's context; "
                    "page through the rest."
                ),
            }
        return ToolResult(content=[{"type": "text", "text": _dumps(structured)}], structured=structured)

    # Anything else: hand back the text, truncated.
    text, _ = truncate_text(response.text)
    return text_result(text)


def _error_result(spec: ToolSpec, response: httpx.Response, content_type: str) -> ToolResult:
    detail: Any = None
    if content_type.startswith("application/json"):
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            detail = body.get("detail", body)
        else:
            detail = body
    if detail is None:
        detail = response.text.strip() or response.reason_phrase

    message = flatten_detail(detail) or f"HTTP {response.status_code}"
    prefix = {
        400: "Bad request",
        403: "Permission denied",
        404: "Not found",
        409: "Conflict",
        422: "Invalid arguments",
    }.get(response.status_code, f"HTTP {response.status_code}")

    structured = {"error": {"status": response.status_code, "detail": detail, "tool": spec.name}}
    return ToolResult(
        content=[{"type": "text", "text": f"{prefix} ({response.status_code}) from {spec.name}:\n{message}"}],
        structured=structured,
        is_error=True,
    )
