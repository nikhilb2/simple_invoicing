"""The hand-written ``search`` and ``fetch`` tools.

ChatGPT connectors require exactly these two; Claude benefits from them too,
because "find the invoice for Acme" is one call instead of a guess at which of
130 generated tools to reach for.

Both run over the same in-process HTTP path as every other tool rather than
against a database session of their own. That is deliberate: it inherits the
per-handler tenant filters, keeps the MCP request from holding a database
connection across the whole call, and means the test suite's ``get_db`` override
applies here exactly as it does everywhere else.

Two contract details that are easy to get wrong and silently degrade the client:

* ``url`` must be a real deep link, or ChatGPT renders no citation at all.
* the payload must be returned **twice** — as ``structuredContent`` *and* as a
  JSON string inside ``content``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.core.config import settings
from src.mcp_server.config import (
    SCOPE_READ,
    SEARCH_DEFAULT_LIMIT,
    SEARCH_FANOUT_LIMIT,
    SEARCH_MAX_LIMIT,
)
from src.mcp_server.dispatch import ToolResult, raw_request
from src.mcp_server.principal import Principal
from src.mcp_server.schema import ArgumentPlan

logger = logging.getLogger(__name__)

# Deep-link templates, all in one dict so the frontend track has a single file to
# honour. `{id}` is substituted with the record id.
DEEP_LINKS: dict[str, str] = {
    "invoice": "/invoices-view?invoice_id={id}",
    "ledger": "/ledgers/{id}",
    "product": "/products-inventory?product_id={id}",
    "credit_note": "/credit-notes?cn_id={id}",
    "payment": "/cash-bank?payment_id={id}",
    "serial": "/products-inventory?serial={id}",
}


def deep_link(kind: str, identifier: Any) -> str:
    template = DEEP_LINKS.get(kind)
    base = settings.PUBLIC_APP_BASE_URL.rstrip("/")
    if not template:
        return base
    return base + template.format(id=identifier)


# --- corpora --------------------------------------------------------------
# `GET /api/payments/` has no `search` parameter, so payments are not searchable
# in v1 — `fetch("payment:12")` still resolves them by id.
SEARCH_CORPORA: tuple[dict[str, Any], ...] = (
    {"kind": "invoice", "path": "/api/invoices/", "label": "Invoice"},
    {"kind": "ledger", "path": "/api/ledgers/", "label": "Ledger"},
    {"kind": "product", "path": "/api/products/", "label": "Product"},
    {"kind": "credit_note", "path": "/api/credit-notes/", "label": "Credit note"},
    {"kind": "serial", "path": "/api/serials/", "label": "Serial"},
)

FETCH_ROUTES: dict[str, str] = {
    "invoice": "/api/invoices/{id}",
    "ledger": "/api/ledgers/{id}",
    "credit_note": "/api/credit-notes/{id}",
    "payment": "/api/payments/{id}",
}

# Products have no GET-by-id route, so `fetch("product:9")` pages the product
# list looking for it. Bounded so a large catalogue cannot turn one fetch into
# an unbounded scan.
PRODUCT_SCAN_PAGE_SIZE = 100
PRODUCT_SCAN_MAX_PAGES = 10


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value if value is not None else "")


def _date(value: Any) -> str:
    if not value:
        return ""
    return str(value)[:10]


def _row_title(kind: str, row: dict[str, Any]) -> str:
    if kind == "invoice":
        return f"Invoice {row.get('invoice_number') or row.get('id')} — {row.get('ledger_name') or 'unknown party'}"
    if kind == "ledger":
        return f"Ledger {row.get('name') or row.get('id')}"
    if kind == "product":
        return f"{row.get('name') or 'Product'} ({row.get('sku') or row.get('id')})"
    if kind == "credit_note":
        return f"Credit note {row.get('credit_note_number') or row.get('id')}"
    if kind == "payment":
        return f"Payment {row.get('payment_number') or row.get('id')} — {_money(row.get('amount'))}"
    if kind == "serial":
        return f"Serial {row.get('serial_number')}"
    return str(row.get("id"))  # pragma: no cover


def _row_identifier(kind: str, row: dict[str, Any]) -> str:
    if kind == "serial":
        return str(row.get("serial_number"))
    return str(row.get("id"))


def _items_of(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


# --- markdown rendering ---------------------------------------------------
# `text` is fed to the *answering* model, not shown raw, so it is compact
# markdown rather than a JSON dump.

def _render_invoice(row: dict[str, Any]) -> str:
    lines = [
        f"# Invoice {row.get('invoice_number') or row.get('id')}",
        "",
        f"- Party: {row.get('ledger_name') or '—'}"
        + (f" (GST {row['ledger_gst']})" if row.get("ledger_gst") else ""),
        f"- Type: {row.get('voucher_type', 'sales')}",
        f"- Date: {_date(row.get('invoice_date'))}"
        + (f" · Due {_date(row.get('due_date'))}" if row.get("due_date") else ""),
        f"- Status: {row.get('status', 'active')} · Payment: {row.get('payment_status', 'unpaid')}",
    ]
    items = row.get("items") or []
    if items:
        lines += ["", "| Item | Qty | Rate | Amount |", "| --- | ---: | ---: | ---: |"]
        for item in items[:50]:
            lines.append(
                f"| {item.get('product_name') or item.get('description') or item.get('product_id')} "
                f"| {item.get('quantity')} | {_money(item.get('unit_price'))} | {_money(item.get('line_total'))} |"
            )
        if len(items) > 50:
            lines.append(f"| … {len(items) - 50} more lines | | | |")
    lines += [
        "",
        f"**Taxable** {_money(row.get('total_taxable_amount') or row.get('taxable_amount'))} · "
        f"**Tax** {_money(row.get('total_tax_amount'))} · **Total** {_money(row.get('total_amount'))}",
    ]
    return "\n".join(lines)


def _render_ledger(row: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Ledger {row.get('name')}",
            "",
            f"- Address: {row.get('address') or '—'}",
            f"- GST: {row.get('gst') or '—'}",
            f"- Phone: {row.get('phone_number') or '—'} · Email: {row.get('email') or '—'}",
            f"- Opening balance: {_money(row.get('opening_balance'))}",
            f"- Current balance: {_money(row.get('balance') or row.get('closing_balance'))}",
        ]
    )


def _render_product(row: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {row.get('name')} ({row.get('sku')})",
            "",
            f"- Price: {_money(row.get('price'))} · Purchase: {_money(row.get('purchase_price'))}",
            f"- GST rate: {row.get('gst_rate')}% · HSN/SAC: {row.get('hsn_sac') or '—'}",
            f"- Unit: {row.get('unit')} · Reorder level: {row.get('reorder_level')}",
            f"- Tracks serials: {bool(row.get('track_serials'))} · Inventory: {bool(row.get('maintain_inventory'))}",
            f"- Description: {row.get('description') or '—'}",
        ]
    )


def _render_credit_note(row: dict[str, Any]) -> str:
    lines = [
        f"# Credit note {row.get('credit_note_number')}",
        "",
        f"- Ledger id: {row.get('ledger_id')}",
        f"- Type: {row.get('credit_note_type')} · Status: {row.get('status')}",
        f"- Reason: {row.get('reason') or '—'}",
        f"- Against invoices: {', '.join(str(i) for i in (row.get('invoice_ids') or [])) or '—'}",
        "",
        f"**Taxable** {_money(row.get('taxable_amount'))} · **Total** {_money(row.get('total_amount'))}",
    ]
    return "\n".join(lines)


def _render_payment(row: dict[str, Any]) -> str:
    allocations = row.get("invoice_allocations") or []
    lines = [
        f"# Payment {row.get('payment_number') or row.get('id')}",
        "",
        f"- Type: {row.get('voucher_type')} · Amount: {_money(row.get('amount'))}",
        f"- Date: {_date(row.get('date'))} · Mode: {row.get('mode') or '—'}",
        f"- Ledger id: {row.get('ledger_id')} · Account: {row.get('account_display_name') or '—'}",
        f"- Status: {row.get('status')} · Reference: {row.get('reference') or '—'}",
    ]
    if allocations:
        lines += ["", "Allocated against:"]
        for allocation in allocations[:25]:
            lines.append(
                f"- Invoice {allocation.get('invoice_number') or allocation.get('invoice_id')}: "
                f"{_money(allocation.get('allocated_amount'))}"
            )
    return "\n".join(lines)


def _render_serial(row: dict[str, Any]) -> str:
    product = row.get("product") or {}
    lines = [
        f"# Serial {row.get('serial_number')}",
        "",
        f"- Status: {row.get('status')}",
        f"- Product: {product.get('name')} ({product.get('sku')})",
    ]
    for key, label in (("purchase_invoice", "Purchased on"), ("sales_invoice", "Sold on")):
        ref = row.get(key)
        if ref:
            lines.append(f"- {label}: invoice {ref.get('invoice_number') or ref.get('id')} ({_date(ref.get('invoice_date'))})")
    return "\n".join(lines)


_RENDERERS = {
    "invoice": _render_invoice,
    "ledger": _render_ledger,
    "product": _render_product,
    "credit_note": _render_credit_note,
    "payment": _render_payment,
    "serial": _render_serial,
}

MAX_TEXT_CHARS = 8_000


def _metadata(kind: str, row: dict[str, Any]) -> dict[str, str]:
    """A flat ``str -> str`` map, as the connector contract requires."""
    metadata: dict[str, str] = {"type": kind}
    for key in (
        "invoice_number",
        "credit_note_number",
        "payment_number",
        "serial_number",
        "sku",
        "name",
        "ledger_name",
        "status",
        "payment_status",
        "voucher_type",
    ):
        value = row.get(key)
        if value not in (None, ""):
            metadata[key] = str(value)
    for key in ("total_amount", "amount", "price"):
        if row.get(key) is not None:
            metadata[key] = _money(row[key])
    for key in ("invoice_date", "date", "created_at"):
        if row.get(key):
            metadata[key] = _date(row[key])
            break
    return metadata


# --- search ---------------------------------------------------------------

async def run_search(registry, principal: Principal, arguments: dict[str, Any]) -> ToolResult:
    query = str(arguments.get("query") or "").strip()
    try:
        limit = int(arguments.get("limit") or SEARCH_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = SEARCH_DEFAULT_LIMIT
    limit = max(1, min(limit, SEARCH_MAX_LIMIT))

    requested = arguments.get("types")
    if isinstance(requested, str):
        requested = [requested]
    wanted = {str(item) for item in requested} if requested else None

    corpora = [c for c in SEARCH_CORPORA if wanted is None or c["kind"] in wanted]
    if not query:
        return _connector_result({"results": []})

    # Ask each corpus for the full limit rather than an even share: matches often
    # concentrate in one corpus, and a share-based budget would cap "Zenith" at
    # two ledgers even when nothing else matched at all.
    per_corpus = limit
    semaphore = asyncio.Semaphore(SEARCH_FANOUT_LIMIT)

    async def one(corpus: dict[str, Any]) -> list[dict[str, str]]:
        async with semaphore:
            try:
                response = await raw_request(
                    registry,
                    "search",
                    principal,
                    "GET",
                    corpus["path"],
                    params=[("search", query), ("page", "1"), ("page_size", str(per_corpus))],
                )
            except Exception:  # noqa: BLE001 - one dead corpus must not fail the search
                logger.exception("MCP search: corpus %s failed", corpus["kind"])
                return []
            if response.status_code >= 400:
                logger.warning(
                    "MCP search: corpus %s returned HTTP %s", corpus["kind"], response.status_code
                )
                return []
            try:
                payload = response.json()
            except ValueError:  # pragma: no cover
                return []
            results = []
            for row in _items_of(payload)[:per_corpus]:
                identifier = _row_identifier(corpus["kind"], row)
                results.append(
                    {
                        "id": f"{corpus['kind']}:{identifier}",
                        "title": _row_title(corpus["kind"], row),
                        "url": deep_link(corpus["kind"], identifier),
                    }
                )
            return results

    gathered = await asyncio.gather(*(one(corpus) for corpus in corpora))

    # Interleave so no single corpus monopolises the result list.
    results: list[dict[str, str]] = []
    index = 0
    while len(results) < limit and any(index < len(bucket) for bucket in gathered):
        for bucket in gathered:
            if index < len(bucket) and len(results) < limit:
                results.append(bucket[index])
        index += 1

    return _connector_result({"results": results})


# --- fetch ----------------------------------------------------------------

def parse_identifier(identifier: str) -> tuple[str, str]:
    kind, _, rest = str(identifier).partition(":")
    return kind.strip(), rest.strip()


async def run_fetch(registry, principal: Principal, arguments: dict[str, Any]) -> ToolResult:
    identifier = str(arguments.get("id") or "").strip()
    if not identifier:
        return _error("fetch requires an `id` such as \"invoice:123\".")

    kind, key = parse_identifier(identifier)
    if not key:
        return _error(
            f"Unrecognised id {identifier!r}. Ids look like \"invoice:123\", \"ledger:45\", "
            "\"product:9\", \"credit_note:7\", \"payment:12\" or \"serial:ABC123\"."
        )

    if kind == "serial":
        row = await _fetch_serial(registry, principal, key)
    elif kind == "product":
        row = await _fetch_product(registry, principal, key)
    elif kind in FETCH_ROUTES:
        row = await _fetch_by_route(registry, principal, kind, key)
    else:
        return _error(
            f"Unknown record type {kind!r}. Known types: "
            + ", ".join(sorted({*FETCH_ROUTES, "product", "serial"}))
            + "."
        )

    if row is None:
        return _error(f"No {kind.replace('_', ' ')} found for id {identifier!r}.")

    renderer = _RENDERERS.get(kind)
    text = renderer(row) if renderer else json.dumps(row, default=str)[:MAX_TEXT_CHARS]
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n… [truncated]"

    payload = {
        "id": identifier,
        "title": _row_title(kind, row),
        "text": text,
        "url": deep_link(kind, _row_identifier(kind, row)),
        "metadata": _metadata(kind, row),
    }
    return _connector_result(payload)


async def _fetch_by_route(registry, principal: Principal, kind: str, key: str) -> dict[str, Any] | None:
    path = FETCH_ROUTES[kind].format(id=key)
    response = await raw_request(registry, "fetch", principal, "GET", path)
    if response.status_code >= 400:
        return None
    try:
        payload = response.json()
    except ValueError:  # pragma: no cover
        return None
    return payload if isinstance(payload, dict) else None


async def _fetch_serial(registry, principal: Principal, code: str) -> dict[str, Any] | None:
    response = await raw_request(
        registry, "fetch", principal, "GET", "/api/serials/scan", params=[("code", code)]
    )
    if response.status_code >= 400:
        return None
    try:
        payload = response.json()
    except ValueError:  # pragma: no cover
        return None
    if not isinstance(payload, dict):
        return None
    return payload.get("serial")


async def _fetch_product(registry, principal: Principal, key: str) -> dict[str, Any] | None:
    """No GET-by-id route exists for products, so page the list — bounded."""
    try:
        product_id = int(key)
    except (TypeError, ValueError):
        product_id = None

    for page in range(1, PRODUCT_SCAN_MAX_PAGES + 1):
        response = await raw_request(
            registry,
            "fetch",
            principal,
            "GET",
            "/api/products/",
            params=[("page", str(page)), ("page_size", str(PRODUCT_SCAN_PAGE_SIZE))],
        )
        if response.status_code >= 400:
            return None
        try:
            payload = response.json()
        except ValueError:  # pragma: no cover
            return None
        rows = _items_of(payload)
        for row in rows:
            if product_id is not None and row.get("id") == product_id:
                return row
            if row.get("sku") == key:
                return row
        if isinstance(payload, dict) and page >= (payload.get("total_pages") or 1):
            break
        if not rows:
            break
    return None


# --- result shaping -------------------------------------------------------

def _connector_result(payload: dict[str, Any]) -> ToolResult:
    # Returned twice on purpose: ChatGPT reads structuredContent, other clients
    # read the JSON string in content.
    return ToolResult(
        content=[{"type": "text", "text": json.dumps(payload, default=str, ensure_ascii=False)}],
        structured=payload,
        is_error=False,
    )


def _error(message: str) -> ToolResult:
    return ToolResult(content=[{"type": "text", "text": message}], is_error=True)


# --- tool specs -----------------------------------------------------------

def _spec(**kwargs):
    from src.mcp_server.registry import ToolSpec

    return ToolSpec(**kwargs)


def _build_search_spec():
    return _spec(
        name="search",
        method="GET",
        path="",
        tag="discovery",
        description=(
            "Search invoices, ledgers, products, credit notes and serial numbers by free text. "
            "Returns matching records as {id, title, url}; pass an id to `fetch` for the full "
            "record. Payments are not text-searchable — reach them with fetch(\"payment:<id>\")."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search term."},
                "limit": {
                    "type": "integer",
                    "description": f"Maximum results to return (default {SEARCH_DEFAULT_LIMIT}, max {SEARCH_MAX_LIMIT}).",
                },
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": [c["kind"] for c in SEARCH_CORPORA]},
                    "description": "Restrict the search to these record types.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                        },
                        "required": ["id", "title", "url"],
                    },
                }
            },
            "required": ["results"],
        },
        plan=ArgumentPlan(),
        annotations={
            "title": "Search records",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        required_scopes=frozenset({SCOPE_READ}),
        is_write=False,
        is_email=False,
        admin_only=False,
        in_core=True,
        handler="search",
    )


def _build_fetch_spec():
    return _spec(
        name="fetch",
        method="GET",
        path="",
        tag="discovery",
        description=(
            "Fetch one record in full by the id returned from `search`: \"invoice:123\", "
            "\"ledger:45\", \"product:9\", \"credit_note:7\", \"payment:12\" or \"serial:ABC123\". "
            "Returns readable text plus a deep link into the app."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Record id in `type:key` form, e.g. \"invoice:123\".",
                }
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "text": {"type": "string"},
                "url": {"type": "string"},
                "metadata": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["id", "title", "text", "url"],
        },
        plan=ArgumentPlan(),
        annotations={
            "title": "Fetch a record",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        required_scopes=frozenset({SCOPE_READ}),
        is_write=False,
        is_email=False,
        admin_only=False,
        in_core=True,
        handler="fetch",
    )


SEARCH_TOOL = _build_search_spec()
FETCH_TOOL = _build_fetch_spec()

HANDLERS = {"search": run_search, "fetch": run_fetch}
