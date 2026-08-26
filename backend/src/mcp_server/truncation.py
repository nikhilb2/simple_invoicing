"""Keep one tool result inside a sane share of the model's context.

Four strategies, applied in order and only as far as needed:

1. **Clamp ``page_size`` in the arguments**, before the call. The REST API allows
   up to 500 rows; a 500-row list would consume the whole context, so the
   argument is rewritten rather than the response repaired after the fact.
2. **Recursive string clamping.** The company profile carries a base64 logo, and
   a single string can blow the budget on its own.
3. **Envelope-aware item slicing.** Paginated responses wrap their rows in
   ``items``; the array is sliced and a ``_truncated`` note attached so the model
   knows more exist and how to reach them.
4. **A final byte guard**, in case something exotic is still oversized.
"""

from __future__ import annotations

import json
from typing import Any

from src.mcp_server.config import (
    HARD_RESPONSE_BYTES,
    MAX_CSV_BYTES,
    MAX_CSV_ROWS,
    MAX_PAGE_SIZE,
    MAX_RESPONSE_BYTES,
    MAX_STRING_CHARS,
)

_TRUNCATION_KEY = "_truncated"
# Preferred list keys, in order, when deciding what to slice.
_ENVELOPE_KEYS = ("items", "results", "rows", "data", "entries", "records")


def json_size(payload: Any) -> int:
    try:
        return len(json.dumps(payload, default=str).encode("utf-8"))
    except (TypeError, ValueError):  # pragma: no cover - default=str covers this
        return len(str(payload).encode("utf-8"))


def clamp_page_size(arguments: dict[str, Any], limit: int = MAX_PAGE_SIZE) -> tuple[dict[str, Any], bool]:
    """Cap ``page_size``/``limit`` arguments. Returns ``(arguments, clamped)``."""
    clamped = False
    result = dict(arguments)
    for key in ("page_size", "limit", "per_page"):
        value = result.get(key)
        if value is None:
            continue
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        if numeric > limit:
            result[key] = limit
            clamped = True
    return result, clamped


def clamp_strings(payload: Any, max_chars: int = MAX_STRING_CHARS) -> tuple[Any, int]:
    """Recursively shorten long strings. Returns ``(payload, clamped_count)``."""
    count = 0

    def walk(node: Any) -> Any:
        nonlocal count
        if isinstance(node, str):
            if len(node) > max_chars:
                count += 1
                return node[:max_chars] + f"… [truncated, {len(node)} chars total]"
            return node
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        return node

    return walk(payload), count


def _pick_list_key(payload: dict[str, Any]) -> str | None:
    for key in _ENVELOPE_KEYS:
        if isinstance(payload.get(key), list) and payload[key]:
            return key
    # Fall back to whichever list value is the largest.
    candidates = [
        (json_size(value), key)
        for key, value in payload.items()
        if isinstance(value, list) and value
    ]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _fit_items(items: list[Any], budget: int) -> int:
    """Largest prefix length of ``items`` whose JSON fits in ``budget`` bytes."""
    low, high, best = 0, len(items), 0
    while low <= high:
        middle = (low + high) // 2
        if json_size(items[:middle]) <= budget:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


def truncate_payload(
    payload: Any,
    *,
    budget: int | None = None,
    hard_budget: int | None = None,
) -> tuple[Any, dict[str, Any] | None]:
    """Shrink ``payload`` to fit ``budget``. Returns ``(payload, note)``.

    Budgets are read from the module at call time, not bound as defaults, so a
    test can shrink them without manufacturing megabytes of fixtures.
    """
    budget = MAX_RESPONSE_BYTES if budget is None else budget
    hard_budget = HARD_RESPONSE_BYTES if hard_budget is None else hard_budget
    if json_size(payload) <= budget:
        return payload, None

    note: dict[str, Any] = {}

    payload, clamped_strings = clamp_strings(payload)
    if clamped_strings:
        note["long_fields_shortened"] = clamped_strings
    if json_size(payload) <= budget:
        return _attach(payload, note), note or None

    if isinstance(payload, list):
        total = len(payload)
        kept = _fit_items(payload, budget)
        note.update(
            {
                "returned": kept,
                "total": total,
                "hint": "Result truncated. Narrow the query or request a later page.",
            }
        )
        return payload[:kept], note

    if isinstance(payload, dict):
        key = _pick_list_key(payload)
        if key is not None:
            items = payload[key]
            overhead = json_size({k: v for k, v in payload.items() if k != key})
            kept = _fit_items(items, max(budget - overhead, 1024))
            note.update(
                {
                    "field": key,
                    "returned": kept,
                    "total": payload.get("total", len(items)),
                    "hint": (
                        "Result truncated to fit the response budget. Use `page`/`page_size` "
                        "or a narrower filter to see the rest."
                    ),
                }
            )
            payload = {**payload, key: items[:kept]}
            return _attach(payload, note), note

    # Nothing structural to slice — fall back to the hard guard.
    if json_size(payload) > hard_budget:
        note.update(
            {
                "returned": 0,
                "hint": "Response was too large to return. Narrow the query.",
                "original_bytes": json_size(payload),
            }
        )
        return {_TRUNCATION_KEY: note}, note
    return _attach(payload, note), note or None


def _attach(payload: Any, note: dict[str, Any]) -> Any:
    if note and isinstance(payload, dict):
        return {**payload, _TRUNCATION_KEY: note}
    return payload


def truncate_text(
    text: str,
    *,
    max_rows: int | None = None,
    max_bytes: int | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Trim a CSV/text body to a row budget, then to a byte budget."""
    max_rows = MAX_CSV_ROWS if max_rows is None else max_rows
    max_bytes = MAX_CSV_BYTES if max_bytes is None else max_bytes
    note: dict[str, Any] = {}
    lines = text.splitlines()
    if len(lines) > max_rows:
        note["returned_rows"] = max_rows
        note["total_rows"] = len(lines)
        lines = lines[:max_rows]
        text = "\n".join(lines)
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore")
        note["truncated_bytes"] = len(encoded)
    if note:
        note["hint"] = "Output truncated. Download the full file from the app."
        text = text + f"\n… [truncated: {note}]"
        return text, note
    return text, None
