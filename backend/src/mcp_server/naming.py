"""Deterministic tool names derived from tag + method + path.

FastAPI's auto operation ids (``list_invoices_api_invoices__get``) are unusable
as tool names: they are ugly, and they change whenever a *handler function* is
renamed — silently breaking a user's saved prompts. Names here derive from the
router tag, the HTTP method and the path, so only a real route rename moves them,
and :mod:`src.mcp_server.overrides` can pin the ugly ones by hand.

Path parameters never appear in the name; the shape is::

    <tag>_<verb>[_<remaining path segments>]

    GET    /api/invoices/                  -> invoices_list
    GET    /api/invoices/{invoice_id}      -> invoices_get
    POST   /api/invoices/                  -> invoices_create
    GET    /api/ledgers/{id}/statement     -> ledgers_get_statement
    PATCH  /api/marketplace/listings/{id}  -> marketplace_update_listings
"""

from __future__ import annotations

import re

MAX_TOOL_NAME_LENGTH = 64

# The verb is always present, even when path segments follow it, so that
# GET /catalog and GET /catalog/{id} cannot collapse onto the same name.
_VERBS = {
    "GET": ("list", "get"),  # (no path param, has path param)
    "POST": ("create", "create"),
    "PUT": ("update", "update"),
    "PATCH": ("update", "update"),
    "DELETE": ("delete", "delete"),
}


def slugify(value: str) -> str:
    """``credit-notes`` -> ``credit_notes``; ``export-json`` -> ``export_json``."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def path_segments(path: str) -> list[str]:
    """Literal (non-parameter) path segments, with the ``api`` prefix dropped."""
    segments = [
        segment
        for segment in path.split("/")
        if segment and not (segment.startswith("{") and segment.endswith("}"))
    ]
    if segments and segments[0] == "api":
        segments = segments[1:]
    return segments


def path_param_names(path: str) -> list[str]:
    return re.findall(r"\{([^}/]+)\}", path)


def generate_tool_name(method: str, path: str, tag: str | None) -> str:
    """Build the generated (pre-override) tool name for one operation."""
    method = method.upper()
    segments = path_segments(path)
    tag_slug = slugify(tag) if tag else (segments[0] if segments else "api")

    rest = segments
    # Drop the leading segment when it merely repeats the router tag, so
    # /api/invoices/ under tag "invoices" does not become invoices_invoices_list.
    if rest and (rest[0] == tag_slug or slugify(rest[0]) == tag_slug):
        rest = rest[1:]
    rest = [slugify(segment) for segment in rest]

    has_path_param = bool(path_param_names(path))
    verbs = _VERBS.get(method)
    if verbs is None:  # pragma: no cover - defensive; OpenAPI has no other verbs
        raise ValueError(f"Unsupported HTTP method for tool naming: {method}")
    verb = verbs[1] if has_path_param else verbs[0]

    parts = [tag_slug, verb, *rest]
    name = "_".join(part for part in parts if part)
    return name[:MAX_TOOL_NAME_LENGTH]
