"""Streamable-HTTP transport for the MCP endpoint — hand-rolled, no ``mcp`` dep.

Three constraints drove hand-rolling this rather than mounting the official SDK:

* ``StreamableHTTPSessionManager`` only runs inside an app **lifespan**, and
  ``tests/conftest.py`` builds ``TestClient(app)`` bare — which never runs
  lifespan — so a lifespan requirement would 500 the endpoint under every one of
  the 30+ existing test files.
* the 401 challenge must be emitted *before* any JSON-RPC parsing, which means
  wrapping the SDK anyway — at which point it is selling ~80 lines of envelope.
* ``requirements.txt`` is fully pinned with no lockfile, and ``fastapi==0.115.0``
  pins ``starlette<0.39``, while ``mcp`` keeps ratcheting its starlette floor.

Registered with ``app.add_route``, never ``app.mount``: mounting makes bare
``/mcp`` issue a 307 to ``/mcp/`` and several MCP clients drop the POST body on a
307. ``add_route`` also bypasses OpenAPI, so the endpoint can never appear in
``app.openapi()`` and therefore can never become a tool that calls itself.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.core.config import settings
from src.mcp_server.config import (
    ALL_SCOPES,
    FALLBACK_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from src.mcp_server.errors import PARSE_ERROR, INVALID_REQUEST, rpc_error
from src.mcp_server.principal import Unauthenticated, resolve_principal
from src.mcp_server.registry import get_registry
from src.mcp_server.server import handle_message

logger = logging.getLogger(__name__)

# The canonical mount plus an `/api`-prefixed alias, so a self-hoster stuck
# behind an `/api`-only proxy can still run it. Only one is ever *advertised*
# (settings.MCP_RESOURCE_URI) — two advertised resource URIs would break audience
# validation.
MCP_ROUTES = ("/mcp", "/mcp/", "/api/mcp", "/api/mcp/")

EXPOSED_HEADERS = ("WWW-Authenticate", "Mcp-Session-Id", "MCP-Protocol-Version")


def register_mcp(app) -> None:
    """Register the MCP endpoint on ``app``. Idempotent."""
    if getattr(app.state, "mcp_registered", False):
        return
    for path in MCP_ROUTES:
        app.add_route(path, mcp_endpoint, methods=["POST", "GET", "DELETE"], include_in_schema=False)
    app.state.mcp_registered = True


# --- the auth challenge ---------------------------------------------------

def protected_resource_metadata_url() -> str:
    base = settings.PUBLIC_API_BASE_URL.rstrip("/")
    return f"{base}/.well-known/oauth-protected-resource/mcp"


def challenge_header(description: str = "Authentication required") -> str:
    scopes = " ".join(ALL_SCOPES)
    return (
        'Bearer error="invalid_token", '
        f'error_description="{description}", '
        f'resource_metadata="{protected_resource_metadata_url()}", '
        f'scope="{scopes}"'
    )


def unauthorized(description: str = "Authentication required") -> Response:
    """A real HTTP 401.

    Not a 200 carrying ``isError: true`` — that produces no auth prompt in
    Claude at all; it silently degrades to the model telling the user to sign in.
    """
    return JSONResponse(
        {
            "error": "invalid_token",
            "error_description": description,
            "resource_metadata": protected_resource_metadata_url(),
        },
        status_code=401,
        headers={"WWW-Authenticate": challenge_header(description)},
    )


# --- origin validation (DNS-rebinding protection) -------------------------

def _configured_origins() -> set[str]:
    """CORS origins, mirrored from app_main without importing it (circular)."""
    raw = os.getenv("CORS_ORIGINS", "")
    if raw.strip():
        origins = {origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()}
    else:
        origins = {
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "https://invoicing.nikhilbhatia.com",
        }
    origins.add(settings.PUBLIC_APP_BASE_URL.rstrip("/"))
    origins.add(settings.PUBLIC_API_BASE_URL.rstrip("/"))
    return origins


def origin_allowed(origin: str | None) -> bool:
    """Non-browser clients send no Origin; those are fine. Browsers must match."""
    if not origin:
        return True
    normalised = origin.rstrip("/")
    if normalised in _configured_origins():
        return True
    host = urlparse(normalised).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1")


# --- endpoint -------------------------------------------------------------

async def mcp_endpoint(request: Request) -> Response:
    if not settings.MCP_ENABLED:
        return JSONResponse({"detail": "MCP is disabled on this server"}, status_code=404)

    method = request.method.upper()
    if method == "GET":
        # Stateless server: there is no server-initiated stream to open.
        return JSONResponse(
            {"detail": "This MCP endpoint is stateless; use POST."},
            status_code=405,
            headers={"Allow": "POST, DELETE"},
        )
    if method == "DELETE":
        # Session termination. Nothing to terminate, but answer politely.
        return Response(status_code=200)
    if method != "POST":  # pragma: no cover - add_route limits the verbs
        return JSONResponse({"detail": "Method not allowed"}, status_code=405)

    if not origin_allowed(request.headers.get("origin")):
        logger.warning("MCP: rejected request from disallowed origin %r", request.headers.get("origin"))
        return JSONResponse({"detail": "Origin not allowed"}, status_code=403)

    protocol_version = request.headers.get("mcp-protocol-version") or FALLBACK_PROTOCOL_VERSION
    if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        return JSONResponse(
            {
                "detail": f"Unsupported MCP-Protocol-Version: {protocol_version}",
                "supported": list(SUPPORTED_PROTOCOL_VERSIONS),
            },
            status_code=400,
        )

    # The auth gate runs *before* the body is parsed.
    try:
        principal = await resolve_principal(request)
    except Unauthenticated as exc:
        return unauthorized(str(exc) or "Authentication required")
    except Exception:  # noqa: BLE001 - a broken token store must not 500 silently
        logger.exception("MCP: principal resolution failed")
        return unauthorized("Authentication required")

    raw = await request.body()
    try:
        message = json.loads(raw) if raw else None
    except ValueError as exc:
        return _json(rpc_error(None, PARSE_ERROR, f"Parse error: {exc}"), protocol_version)

    if message is None:
        return _json(rpc_error(None, INVALID_REQUEST, "Invalid Request: empty body"), protocol_version)

    registry = get_registry(request.app)
    profile = request.query_params.get("profile")
    tags_param = request.query_params.get("tags")
    tags = [tag for tag in tags_param.split(",")] if tags_param else None

    if isinstance(message, list):
        if not message:
            return _json(rpc_error(None, INVALID_REQUEST, "Invalid Request: empty batch"), protocol_version)
        responses = []
        for entry in message:
            response = await handle_message(registry, entry, principal, profile=profile, tags=tags)
            if response is not None:
                responses.append(response)
        if not responses:
            return Response(status_code=202, headers=_headers(protocol_version))
        return _json(responses, protocol_version)

    response = await handle_message(registry, message, principal, profile=profile, tags=tags)
    if response is None:
        # A notification. 202 with an empty body, per the transport spec.
        return Response(status_code=202, headers=_headers(protocol_version))
    return _json(response, protocol_version)


def _headers(protocol_version: str) -> dict[str, str]:
    return {"MCP-Protocol-Version": protocol_version}


def _json(payload: Any, protocol_version: str) -> Response:
    # JSON-RPC errors are HTTP 200 with an `error` member. Only the auth gate and
    # protocol-version negotiation produce real HTTP error statuses.
    return JSONResponse(payload, status_code=200, headers=_headers(protocol_version))
