"""JSON-RPC error codes, envelope helpers and FastAPI error flattening."""

from __future__ import annotations

from typing import Any

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

JSONRPC_VERSION = "2.0"


def rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def rpc_error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def flatten_detail(detail: Any) -> str:
    """Render FastAPI's ``detail`` as something a model can act on.

    A pydantic 422 arrives as a list of dicts with ``loc``/``msg``/``type``;
    dumped raw it is unreadable, so each entry becomes one ``field: message``
    line naming the argument the model actually passed.
    """
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        if {"loc", "msg"} <= set(detail):
            return _format_validation_entry(detail)
        return "; ".join(f"{key}: {value}" for key, value in detail.items())
    if isinstance(detail, list):
        lines = []
        for entry in detail:
            if isinstance(entry, dict) and "msg" in entry:
                lines.append(_format_validation_entry(entry))
            else:
                lines.append(str(entry))
        return "\n".join(lines)
    return str(detail)


def _format_validation_entry(entry: dict[str, Any]) -> str:
    location = entry.get("loc") or []
    # Drop the "body"/"query"/"path" prefix: arguments are flat at the tool
    # boundary, so the model never saw that distinction.
    parts = [str(part) for part in location if part not in ("body", "query", "path", "header")]
    field = ".".join(parts) if parts else "request"
    message = entry.get("msg", "invalid value")
    return f"{field}: {message}"
