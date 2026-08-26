"""Walk ``app.openapi()`` into the tool catalog, and hold the dispatch client.

The registry is built **lazily on the first MCP request** and cached, never at
import time: building it forces ``app.openapi()``, and the app must be free to
finish wiring its routers first.

Build-time invariants (each one is also a test):

* every tool name is unique and ≤ 64 characters;
* no ``$ref`` survives into any ``inputSchema``;
* no body property collides with a query or path parameter;
* the only header parameter in the whole spec is ``X-Company-Id``;
* the MCP endpoint itself never appears in the spec, so no tool can call it.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from src.core.config import settings
from src.mcp_server.config import (
    INTERNAL_BASE_URL,
    PROFILE_ALL,
    PROFILE_CORE,
    SCOPE_ADMIN,
    SCOPE_READ,
    SCOPE_SEND_EMAIL,
    SCOPE_WRITE,
    VALID_PROFILES,
)
from src.mcp_server.naming import MAX_TOOL_NAME_LENGTH, generate_tool_name
from src.mcp_server.overrides import (
    CORE_TOOLS,
    DESCRIPTION_OVERRIDES,
    EMAIL_PATH_PREFIX,
    EXCLUDED_OPERATIONS,
    EXCLUDED_PATH_PREFIXES,
    NAME_OVERRIDES,
    OPEN_WORLD_OPERATIONS,
)
from src.mcp_server.principal import Principal
from src.mcp_server.schema import ArgumentPlan, build_input_schema, iter_refs

logger = logging.getLogger(__name__)

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


class RegistryError(RuntimeError):
    """A build-time invariant of the tool catalog was violated."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    method: str
    path: str
    tag: str
    description: str
    input_schema: dict[str, Any]
    plan: ArgumentPlan
    annotations: dict[str, Any]
    required_scopes: frozenset[str]
    is_write: bool
    is_email: bool
    admin_only: bool
    in_core: bool
    output_schema: dict[str, Any] | None = None
    handler: str | None = None  # set for the hand-written search/fetch tools

    def to_mcp(self) -> dict[str, Any]:
        tool: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": self.annotations,
        }
        # Generated tools deliberately omit outputSchema: truncation injects a
        # `_truncated` member, which would violate a declared output schema.
        if self.output_schema is not None:
            tool["outputSchema"] = self.output_schema
        return tool


# --- role introspection ---------------------------------------------------

def _iter_dependants(dependant) -> Iterable[Any]:
    yield dependant
    for sub in getattr(dependant, "dependencies", ()) or ():
        yield from _iter_dependants(sub)


def _roles_for_route(route) -> set[str] | None:
    """Roles enforced by ``require_roles`` on this route, or None if unguarded."""
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return None
    found = False
    roles: set[str] = set()
    for dep in _iter_dependants(dependant):
        call = getattr(dep, "call", None)
        if call is None:
            continue
        if getattr(call, "__qualname__", "").startswith("require_roles."):
            found = True
            for cell in getattr(call, "__closure__", None) or ():
                try:
                    value = cell.cell_contents
                except ValueError:  # pragma: no cover - empty cell
                    continue
                if isinstance(value, tuple):
                    roles.update(str(getattr(item, "value", item)) for item in value)
    return roles if found else None


def _role_index(app) -> dict[tuple[str, str], set[str]]:
    """Map ``(METHOD, path)`` -> enforced roles, for every guarded route.

    Indexed under both the with- and without-trailing-slash spellings, because
    the codebase's double-decorator convention registers each route twice and
    only one spelling reaches the OpenAPI document.
    """
    index: dict[tuple[str, str], set[str]] = {}
    for route in getattr(app, "routes", []):
        roles = _roles_for_route(route)
        if roles is None:
            continue
        path = getattr(route, "path", None)
        if not path:
            continue
        variants = {path, path.rstrip("/"), path.rstrip("/") + "/"}
        for method in getattr(route, "methods", ()) or ():
            for variant in variants:
                index[(method.upper(), variant)] = roles
    return index


# --- catalog build --------------------------------------------------------

def _is_excluded(method: str, path: str) -> bool:
    if (method, path) in EXCLUDED_OPERATIONS:
        return True
    return any(path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES)


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _annotations(method: str, path: str, name: str, is_email: bool) -> dict[str, Any]:
    annotations: dict[str, Any] = {"title": _humanize(name)}
    if method == "GET":
        annotations["readOnlyHint"] = True
    else:
        annotations["readOnlyHint"] = False
    if method in ("PUT", "DELETE"):
        annotations["idempotentHint"] = True
    if method == "DELETE" or is_email:
        annotations["destructiveHint"] = True
    elif method != "GET":
        annotations["destructiveHint"] = False
    if (method, path) in OPEN_WORLD_OPERATIONS:
        annotations["openWorldHint"] = True
    else:
        annotations["openWorldHint"] = False
    return annotations


def build_specs(app, *, strict: bool = True) -> tuple[dict[str, ToolSpec], dict[str, Any]]:
    """Build the tool catalog. Returns ``(specs_by_name, measurements)``."""
    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    roles = _role_index(app)

    specs: dict[str, ToolSpec] = {}
    measurements = {
        "operations": 0,
        "excluded": 0,
        "skipped_multipart": 0,
        "header_params": set(),
        "collisions": [],
        "tools": 0,
    }

    for path, item in spec.get("paths", {}).items():
        for method_lower, operation in item.items():
            if method_lower not in HTTP_METHODS:
                continue
            method = method_lower.upper()
            measurements["operations"] += 1

            for parameter in operation.get("parameters", []):
                if parameter.get("in") == "header":
                    measurements["header_params"].add(parameter["name"])

            if _is_excluded(method, path):
                measurements["excluded"] += 1
                continue

            request_body = operation.get("requestBody") or {}
            content_types = set(request_body.get("content", {}))
            if "multipart/form-data" in content_types:
                # No file uploads over MCP.
                measurements["skipped_multipart"] += 1
                continue

            tags = operation.get("tags") or []
            tag = tags[0] if tags else "system"
            name = NAME_OVERRIDES.get((method, path)) or generate_tool_name(method, path, tags[0] if tags else None)

            if len(name) > MAX_TOOL_NAME_LENGTH:
                raise RegistryError(f"Tool name too long ({len(name)}): {name}")
            if name in specs:
                other = specs[name]
                measurements["collisions"].append((name, f"{other.method} {other.path}", f"{method} {path}"))
                raise RegistryError(
                    f"Duplicate tool name {name!r}: {other.method} {other.path} and {method} {path}. "
                    f"Pin one of them in src/mcp_server/overrides.NAME_OVERRIDES."
                )

            input_schema, plan = build_input_schema(operation, components, strict=strict)
            leaked = list(iter_refs(input_schema))
            if leaked:
                raise RegistryError(f"Unresolved $ref in inputSchema for {name}: {leaked[:3]}")

            is_write = method in WRITE_METHODS
            is_email = path.startswith(EMAIL_PATH_PREFIX)
            route_roles = roles.get((method, path)) or roles.get((method, path.rstrip("/"))) or set()
            admin_only = route_roles == {"admin"}

            required: set[str] = set()
            if is_email:
                required.add(SCOPE_SEND_EMAIL)
            elif is_write:
                required.add(SCOPE_WRITE)
            else:
                required.add(SCOPE_READ)
            if admin_only:
                required.add(SCOPE_ADMIN)

            description = DESCRIPTION_OVERRIDES.get((method, path))
            if not description:
                description = operation.get("summary") or operation.get("description") or ""
            if not description:
                description = f"{_humanize(name)}."
            description = f"{description.rstrip()} ({method} {path})"

            specs[name] = ToolSpec(
                name=name,
                method=method,
                path=path,
                tag=tag,
                description=description,
                input_schema=input_schema,
                plan=plan,
                annotations=_annotations(method, path, name, is_email),
                required_scopes=frozenset(required),
                is_write=is_write,
                is_email=is_email,
                admin_only=admin_only,
                in_core=name in CORE_TOOLS,
            )

    # --- build-time invariants --------------------------------------------
    unknown_headers = measurements["header_params"] - {"X-Company-Id"}
    if unknown_headers:
        raise RegistryError(
            "Unexpected header parameters in the OpenAPI spec — headers are never exposed "
            f"as tool arguments, so these would be silently unreachable: {sorted(unknown_headers)}"
        )

    unknown_core = CORE_TOOLS - set(specs)
    if unknown_core:
        raise RegistryError(
            f"overrides.CORE_TOOLS names tools that do not exist: {sorted(unknown_core)}"
        )

    for mcp_path in ("/mcp", "/mcp/", "/api/mcp", "/api/mcp/"):
        if mcp_path in spec.get("paths", {}):
            raise RegistryError(
                f"{mcp_path} appears in app.openapi() — the MCP endpoint must be registered "
                "with app.add_route (which bypasses OpenAPI), or it becomes a tool that calls itself."
            )

    measurements["header_params"] = sorted(measurements["header_params"])
    measurements["tools"] = len(specs)
    return specs, measurements


# --- discovery tools ------------------------------------------------------

def _discovery_specs() -> dict[str, ToolSpec]:
    from src.mcp_server.connector import FETCH_TOOL, SEARCH_TOOL

    return {SEARCH_TOOL.name: SEARCH_TOOL, FETCH_TOOL.name: FETCH_TOOL}


# --- registry -------------------------------------------------------------

class ToolRegistry:
    """Cached tool catalog plus the long-lived in-process HTTP client."""

    def __init__(self, app):
        self.app = app
        self.specs, self.measurements = build_specs(app)
        self.specs.update(_discovery_specs())
        self._client: httpx.AsyncClient | None = None
        self._client_lock = threading.Lock()

    # -- dispatch client --
    @property
    def client(self) -> httpx.AsyncClient:
        """One long-lived client — ``ASGITransport`` has no connection pool to reuse.

        ``raise_app_exceptions=False`` is not optional: without it, an unhandled
        exception in any endpoint propagates out of the in-process call and kills
        the MCP session instead of becoming a mappable 500.
        """
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
                    self._client = httpx.AsyncClient(
                        transport=transport,
                        base_url=INTERNAL_BASE_URL,
                        timeout=60.0,
                    )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- lookup --
    def get(self, name: str) -> ToolSpec | None:
        return self.specs.get(name)

    def golden_triples(self) -> list[tuple[str, str, str]]:
        """``(name, method, path)`` for every generated tool, sorted by name.

        This is the contract with already-connected clients: a route rename must
        surface as a reviewed diff against ``tests/mcp/golden_tools.txt``, not as
        a silently broken saved prompt.
        """
        return sorted(
            (spec.name, spec.method, spec.path)
            for spec in self.specs.values()
            if spec.handler is None
        )

    # -- gating --
    def is_visible(self, spec: ToolSpec, principal: Principal) -> tuple[bool, str | None]:
        """Whether ``principal`` may see and call ``spec``, and why not if not."""
        if (spec.is_write or spec.is_email) and not settings.MCP_WRITE_ENABLED:
            return False, (
                "Write tools are disabled on this server (MCP_WRITE_ENABLED is off)."
            )
        missing = sorted(scope for scope in spec.required_scopes if scope not in principal.scopes)
        if missing:
            return False, (
                f"This tool requires the {', '.join(missing)} scope"
                f"{'s' if len(missing) > 1 else ''}, which this connection was not granted."
            )
        return True, None

    def visible_tools(
        self,
        principal: Principal,
        *,
        profile: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[ToolSpec]:
        profile = resolve_profile(profile)
        tag_filter = {tag.strip() for tag in tags if tag.strip()} if tags else None
        out: list[ToolSpec] = []
        for spec in self.specs.values():
            visible, _ = self.is_visible(spec, principal)
            if not visible:
                continue
            if spec.handler is None:
                # search/fetch are always offered; generated tools honour the profile.
                if profile == PROFILE_CORE and not spec.in_core:
                    continue
                if tag_filter is not None and spec.tag not in tag_filter:
                    continue
            out.append(spec)
        return sorted(out, key=lambda item: item.name)


def resolve_profile(profile: str | None) -> str:
    candidate = (profile or settings.MCP_DEFAULT_PROFILE or PROFILE_CORE).strip().lower()
    if candidate not in VALID_PROFILES:
        return PROFILE_CORE if settings.MCP_DEFAULT_PROFILE == PROFILE_CORE else PROFILE_ALL
    return candidate


_registry: ToolRegistry | None = None
_registry_lock = threading.Lock()


def get_registry(app) -> ToolRegistry:
    """Lazily build (and cache) the registry for ``app``."""
    global _registry
    if _registry is None or _registry.app is not app:
        with _registry_lock:
            if _registry is None or _registry.app is not app:
                _registry = ToolRegistry(app)
                logger.info(
                    "MCP registry built: %s tools from %s operations (%s excluded, %s multipart skipped)",
                    _registry.measurements["tools"],
                    _registry.measurements["operations"],
                    _registry.measurements["excluded"],
                    _registry.measurements["skipped_multipart"],
                )
    return _registry


def reset_registry() -> None:
    """Drop the cached registry (tests that mutate routes or overrides use this)."""
    global _registry
    _registry = None


__all__ = [
    "RegistryError",
    "ToolRegistry",
    "ToolSpec",
    "build_specs",
    "get_registry",
    "reset_registry",
    "resolve_profile",
]
