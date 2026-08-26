"""Catalog invariants — every one of these is also a build-time assert.

The measurements here were re-derived from ``app.openapi()``, not copied from the
design doc. If a route is added or removed these numbers move, and that is the
point: the change should be seen and acknowledged.
"""

from __future__ import annotations

import pytest

from app_main import app
from src.mcp_server.naming import MAX_TOOL_NAME_LENGTH, generate_tool_name
from src.mcp_server.overrides import (
    CORE_TOOLS,
    EXCLUDED_OPERATIONS,
    EXCLUDED_PATH_PREFIXES,
    NAME_OVERRIDES,
)
from src.mcp_server.registry import RegistryError, build_specs, get_registry
from src.mcp_server.schema import (
    RecursiveSchemaError,
    SchemaCollisionError,
    build_input_schema,
    inline_refs,
    iter_refs,
    prune,
)

# Measured against the real spec on 2026-08-26.
EXPECTED_OPERATIONS = 144  # 143 tagged + GET /api/health
EXPECTED_TOOLS = 130  # generated only; `search` and `fetch` are added on top
EXPECTED_EXCLUDED = 13
EXPECTED_MULTIPART_SKIPPED = 1


@pytest.fixture(scope="module")
def registry():
    return get_registry(app)


def test_operation_count_matches_measurement(registry):
    assert registry.measurements["operations"] == EXPECTED_OPERATIONS


def test_tool_count_matches_measurement(registry):
    assert registry.measurements["tools"] == EXPECTED_TOOLS
    # …plus the two hand-written discovery tools.
    assert len(registry.specs) == EXPECTED_TOOLS + 2


def test_exclusion_counts(registry):
    assert registry.measurements["excluded"] == EXPECTED_EXCLUDED
    assert registry.measurements["skipped_multipart"] == EXPECTED_MULTIPART_SKIPPED


def test_only_header_parameter_is_company_id(registry):
    """Header params are never tool arguments, so any *other* header would be
    silently unreachable from MCP."""
    assert registry.measurements["header_params"] == ["X-Company-Id"]


def test_no_name_collisions(registry):
    assert registry.measurements["collisions"] == []
    names = [spec.name for spec in registry.specs.values()]
    assert len(names) == len(set(names))


def test_names_are_short_and_well_formed(registry):
    for name in registry.specs:
        assert len(name) <= MAX_TOOL_NAME_LENGTH, name
        assert name == name.lower(), name
        assert name.replace("_", "").isalnum(), name


def test_every_input_schema_is_self_contained(registry):
    for name, spec in registry.specs.items():
        leaked = list(iter_refs(spec.input_schema))
        assert leaked == [], f"{name} leaked $refs: {leaked}"
        assert spec.input_schema["type"] == "object"


def test_zero_recursive_schemas():
    """Refs are inlined outright rather than emitted as $defs; that is only safe
    because nothing in this spec is self-referential. Strict mode raises if that
    ever stops being true."""
    spec = app.openapi()
    components = spec["components"]["schemas"]
    for name, schema in components.items():
        try:
            inline_refs(schema, components, strict=True)
        except RecursiveSchemaError as exc:  # pragma: no cover - would be a real finding
            pytest.fail(f"{name} is recursive: {exc}")


def test_zero_query_body_collisions():
    """A body property that shadows a query parameter would silently win. There
    are none today; assert it so a future one fails CI."""
    spec = app.openapi()
    components = spec["components"]["schemas"]
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if "multipart/form-data" in (operation.get("requestBody") or {}).get("content", {}):
                continue
            try:
                build_input_schema(operation, components, strict=True)
            except SchemaCollisionError as exc:  # pragma: no cover
                pytest.fail(f"{method.upper()} {path}: {exc}")


def test_excluded_paths_produce_no_tool(registry):
    for spec in registry.specs.values():
        for prefix in EXCLUDED_PATH_PREFIXES:
            assert not spec.path.startswith(prefix), f"{spec.name} exposes {spec.path}"
        assert (spec.method, spec.path) not in EXCLUDED_OPERATIONS


def test_credential_and_restore_routes_are_unreachable(registry):
    paths = {(spec.method, spec.path) for spec in registry.specs.values()}
    for forbidden in [
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/refresh"),
        ("POST", "/api/auth/change-password"),
        ("POST", "/api/backups/restore"),
        ("POST", "/api/api-keys/"),
        ("POST", "/api/company/select/{company_id}"),
        ("POST", "/api/oauth/token"),
        ("POST", "/api/oauth/register"),
    ]:
        assert forbidden not in paths


def test_oauth_server_routes_produce_no_tool(registry):
    """A tool that mints or revokes tokens is the same privilege escalation as an
    API-key minting tool. Excluded explicitly, not merely by the OAuth router
    happening to set include_in_schema=False."""
    for spec in registry.specs.values():
        assert not spec.path.startswith("/api/oauth"), spec.name
        assert not spec.path.startswith("/.well-known"), spec.name


def test_whoami_survives_the_auth_exclusion(registry):
    assert registry.specs["whoami"].path == "/api/auth/me"


def test_no_slash_duplicate_routes_produce_one_tool_each(registry):
    """The double-decorator convention registers `/api/invoices` and
    `/api/invoices/`; only the documented one becomes a tool."""
    by_path = {}
    for spec in registry.specs.values():
        if spec.path:
            by_path.setdefault((spec.method, spec.path.rstrip("/")), []).append(spec.name)
    duplicates = {key: names for key, names in by_path.items() if len(names) > 1}
    assert duplicates == {}


def test_multipart_operations_are_skipped(registry):
    paths = {spec.path for spec in registry.specs.values()}
    assert "/api/products/import-csv" not in paths


def test_email_tools_need_the_send_email_scope(registry):
    from src.mcp_server.config import SCOPE_SEND_EMAIL, SCOPE_WRITE

    for spec in registry.specs.values():
        if spec.is_email:
            assert SCOPE_SEND_EMAIL in spec.required_scopes
            assert SCOPE_WRITE not in spec.required_scopes
            assert spec.annotations["destructiveHint"] is True


def test_annotations_follow_the_method(registry):
    for spec in registry.specs.values():
        if spec.handler is not None:
            continue
        assert spec.annotations["readOnlyHint"] is (spec.method == "GET")
        if spec.method in ("PUT", "DELETE"):
            assert spec.annotations["idempotentHint"] is True
        if spec.method == "DELETE":
            assert spec.annotations["destructiveHint"] is True


def test_sync_all_is_open_world(registry):
    assert registry.specs["marketplace_sync_all"].annotations["openWorldHint"] is True


def test_generated_tools_omit_output_schema(registry):
    """Truncation injects `_truncated`, which would violate a declared schema."""
    for spec in registry.specs.values():
        tool = spec.to_mcp()
        if spec.handler is None:
            assert "outputSchema" not in tool, spec.name
        else:
            assert "outputSchema" in tool, spec.name


def test_every_tool_has_a_description(registry):
    for spec in registry.specs.values():
        assert spec.description and len(spec.description) > 10, spec.name


def test_core_profile_names_all_exist(registry):
    assert CORE_TOOLS <= set(registry.specs)


def test_name_overrides_all_apply(registry):
    """A stale override key is dead weight and hides a rename."""
    live = {(spec.method, spec.path) for spec in registry.specs.values()}
    excluded = set(EXCLUDED_OPERATIONS)
    for key in NAME_OVERRIDES:
        assert key in live or key in excluded or key[1].startswith(EXCLUDED_PATH_PREFIXES), key


def test_mcp_endpoint_is_absent_from_openapi():
    """add_route bypasses OpenAPI, so no tool can ever call the MCP endpoint."""
    paths = app.openapi()["paths"]
    for path in ("/mcp", "/mcp/", "/api/mcp", "/api/mcp/"):
        assert path not in paths


def test_naming_is_stable_for_known_shapes():
    assert generate_tool_name("GET", "/api/invoices/", "invoices") == "invoices_list"
    assert generate_tool_name("GET", "/api/invoices/{invoice_id}", "invoices") == "invoices_get"
    assert generate_tool_name("POST", "/api/invoices/", "invoices") == "invoices_create"
    assert generate_tool_name("GET", "/api/ledgers/{ledger_id}/statement", "ledgers") == "ledgers_get_statement"
    assert generate_tool_name("DELETE", "/api/credit-notes/{cn_id}", "credit-notes") == "credit_notes_delete"


def test_prune_drops_titles_and_null_unions():
    pruned = prune({"title": "X", "anyOf": [{"type": "string"}, {"type": "null"}]})
    assert pruned == {"type": "string"}


def test_build_specs_rejects_a_duplicate_name(monkeypatch):
    """A collision must fail the build, not silently shadow a tool."""
    import src.mcp_server.registry as registry_module

    original = dict(registry_module.NAME_OVERRIDES)
    original[("GET", "/api/invoices/")] = "ledgers_list"
    monkeypatch.setattr(registry_module, "NAME_OVERRIDES", original)
    with pytest.raises(RegistryError, match="Duplicate tool name"):
        build_specs(app)
