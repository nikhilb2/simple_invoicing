"""Turn one OpenAPI operation into a single flat, self-contained ``inputSchema``.

Three things happen here:

1. **``$ref`` inlining.** Measuring the real spec found zero recursive schemas and
   a largest transitive closure of 9, so refs are inlined outright rather than
   emitted as ``$defs`` — a self-contained schema is what MCP clients expect. A
   visited-set still guards against a future cycle rather than blowing the stack.
2. **Pruning.** FastAPI emits ``title`` on every property and
   ``anyOf: [X, {"type": "null"}]`` on every optional. Dropping those is most of
   the token cost of a 130-tool list.
3. **Flattening.** Path params, then query params, then the request body's
   properties hoisted to the top level. Models pick flat arguments far more
   reliably than a nested ``{"body": {...}}``, and the measured spec has zero
   query-param/body-property name collisions to make hoisting ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Keys worth keeping on a pruned schema node. Everything else FastAPI emits is
# either noise (`title`) or unrepresentable to a model.
_KEEP_KEYS = (
    "type",
    "format",
    "enum",
    "const",
    "default",
    "description",
    "items",
    "properties",
    "required",
    "additionalProperties",
    "anyOf",
    "oneOf",
    "allOf",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
)

_NULL = {"type": "null"}


class SchemaCollisionError(ValueError):
    """A body property and a query/path parameter fight over the same argument name."""


class RecursiveSchemaError(ValueError):
    """A ``$ref`` cycle was found while inlining."""


@dataclass(frozen=True)
class ArgumentPlan:
    """Where each top-level argument goes when the call is dispatched."""

    path_params: tuple[str, ...] = ()
    query_params: tuple[str, ...] = ()
    body_params: tuple[str, ...] = ()
    body_required: bool = False
    body_passthrough: bool = False
    accepts_company: bool = False


@dataclass
class _InlineStats:
    max_depth: int = 0
    cycles: list[str] = field(default_factory=list)


def _resolve_ref(ref: str, components: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = ref.rsplit("/", 1)[-1]
    target = components.get(name)
    if target is None:
        raise KeyError(f"Unresolvable $ref: {ref}")
    return name, target


def inline_refs(
    schema: Any,
    components: dict[str, Any],
    *,
    _chain: tuple[str, ...] = (),
    _stats: _InlineStats | None = None,
    strict: bool = False,
) -> Any:
    """Recursively replace every ``$ref`` with its target.

    ``_chain`` is the stack of schema names currently being expanded. A repeat
    means a cycle: in ``strict`` mode that raises (the build-time assert), and
    otherwise it degrades to a bare ``{"type": "object"}`` so a future recursive
    model cannot take the server down.
    """
    stats = _stats if _stats is not None else _InlineStats()

    if isinstance(schema, list):
        return [inline_refs(item, components, _chain=_chain, _stats=stats, strict=strict) for item in schema]
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        name, target = _resolve_ref(schema["$ref"], components)
        if name in _chain:
            stats.cycles.append(name)
            if strict:
                raise RecursiveSchemaError(f"Recursive $ref chain: {' -> '.join((*_chain, name))}")
            return {"type": "object", "description": f"Recursive reference to {name}."}
        chain = (*_chain, name)
        stats.max_depth = max(stats.max_depth, len(chain))
        merged = {k: v for k, v in schema.items() if k != "$ref"}
        resolved = inline_refs(target, components, _chain=chain, _stats=stats, strict=strict)
        if isinstance(resolved, dict):
            return {**resolved, **merged}
        return resolved  # pragma: no cover - components are always objects

    return {
        key: inline_refs(value, components, _chain=_chain, _stats=stats, strict=strict)
        for key, value in schema.items()
    }


def prune(schema: Any) -> Any:
    """Drop ``title`` noise and collapse ``anyOf`` null-unions."""
    if isinstance(schema, list):
        return [prune(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    node = {key: value for key, value in schema.items() if key in _KEEP_KEYS}

    for union_key in ("anyOf", "oneOf"):
        members = node.get(union_key)
        if not isinstance(members, list):
            continue
        non_null = [m for m in members if m != _NULL and m != {"type": "null", "title": None}]
        non_null = [m for m in non_null if not (isinstance(m, dict) and m.get("type") == "null" and len(m) == 1)]
        if len(non_null) == len(members):
            continue
        if len(non_null) == 1:
            collapsed = {**prune(non_null[0])}
            for carry in ("description", "default"):
                if carry in node and carry not in collapsed:
                    collapsed[carry] = node[carry]
            return collapsed
        if non_null:
            node[union_key] = non_null
        else:  # everything was null
            node.pop(union_key)

    if "properties" in node and isinstance(node["properties"], dict):
        node["properties"] = {key: prune(value) for key, value in node["properties"].items()}
    for key in ("items", "additionalProperties"):
        if key in node and isinstance(node[key], (dict, list)):
            node[key] = prune(node[key])
    for key in ("anyOf", "oneOf", "allOf"):
        if key in node and isinstance(node[key], list):
            node[key] = [prune(item) for item in node[key]]

    return node


def _parameter_schema(parameter: dict[str, Any], components: dict[str, Any], strict: bool) -> dict[str, Any]:
    raw = parameter.get("schema", {})
    node = prune(inline_refs(raw, components, strict=strict))
    if not isinstance(node, dict):  # pragma: no cover - defensive
        node = {}
    description = parameter.get("description")
    if description and "description" not in node:
        node["description"] = description
    return node


def build_input_schema(
    operation: dict[str, Any],
    components: dict[str, Any],
    *,
    strict: bool = False,
) -> tuple[dict[str, Any], ArgumentPlan]:
    """Return ``(inputSchema, ArgumentPlan)`` for one OpenAPI operation."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    path_params: list[str] = []
    query_params: list[str] = []
    accepts_company = False

    for parameter in operation.get("parameters", []):
        location = parameter.get("in")
        name = parameter["name"]
        if location == "header":
            # Header params are never tool arguments. The one header this API
            # uses is X-Company-Id, replaced by a synthetic `company_id`.
            if name.lower() == "x-company-id":
                accepts_company = True
            continue
        if location == "cookie":  # pragma: no cover - none exist
            continue
        node = _parameter_schema(parameter, components, strict)
        if name in properties:
            raise SchemaCollisionError(f"Duplicate parameter name {name!r}")
        properties[name] = node
        if location == "path":
            path_params.append(name)
            required.append(name)
        else:
            query_params.append(name)
            if parameter.get("required"):
                required.append(name)

    body_params: list[str] = []
    body_required = False
    body_passthrough = False

    request_body = operation.get("requestBody")
    if request_body:
        content = request_body.get("content", {})
        json_schema = content.get("application/json", {}).get("schema")
        body_required = bool(request_body.get("required", False))
        if json_schema is not None:
            resolved = prune(inline_refs(json_schema, components, strict=strict))
            if isinstance(resolved, dict) and isinstance(resolved.get("properties"), dict):
                body_required_names = set(resolved.get("required") or [])
                for name, node in resolved["properties"].items():
                    if name in properties:
                        raise SchemaCollisionError(
                            f"Body property {name!r} collides with a query/path parameter "
                            f"in {operation.get('operationId')}"
                        )
                    properties[name] = node
                    body_params.append(name)
                    if body_required and name in body_required_names:
                        required.append(name)
            else:
                # Non-object body (a bare list, a scalar, a union that did not
                # collapse). Passed straight through as one `body` argument.
                body_passthrough = True
                node = resolved if isinstance(resolved, dict) else {}
                node.setdefault("description", "Request body, passed through unchanged.")
                properties["body"] = node
                if body_required:
                    required.append("body")

    if accepts_company:
        properties["company_id"] = {
            "type": "integer",
            "description": (
                "Optional. Act on this company instead of the one this connection is "
                "bound to. Only companies you can access are permitted."
            ),
        }

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = sorted(set(required), key=required.index)

    plan = ArgumentPlan(
        path_params=tuple(path_params),
        query_params=tuple(query_params),
        body_params=tuple(body_params),
        body_required=body_required,
        body_passthrough=body_passthrough,
        accepts_company=accepts_company,
    )
    return schema, plan


def iter_refs(schema: Any):
    """Yield every ``$ref`` string still present in a schema (should be none)."""
    if isinstance(schema, dict):
        if "$ref" in schema:
            yield schema["$ref"]
        for value in schema.values():
            yield from iter_refs(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from iter_refs(item)
