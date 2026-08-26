"""Unit tests for the response budget strategies."""

from __future__ import annotations

from src.mcp_server.truncation import (
    clamp_page_size,
    clamp_strings,
    json_size,
    truncate_payload,
    truncate_text,
)


def test_page_size_is_clamped_and_reported():
    arguments, clamped = clamp_page_size({"page_size": 500, "page": 2})
    assert arguments == {"page_size": 50, "page": 2}
    assert clamped is True


def test_page_size_under_the_cap_is_untouched():
    arguments, clamped = clamp_page_size({"page_size": 20})
    assert arguments == {"page_size": 20}
    assert clamped is False


def test_non_numeric_page_size_is_left_for_the_api_to_reject():
    arguments, clamped = clamp_page_size({"page_size": "lots"})
    assert arguments == {"page_size": "lots"}
    assert clamped is False


def test_long_strings_are_clamped_recursively():
    """The company profile carries a base64 logo — one field can blow the budget."""
    payload = {"company": {"logo": "x" * 10_000, "name": "Small"}}
    clamped, count = clamp_strings(payload, max_chars=100)
    assert count == 1
    assert len(clamped["company"]["logo"]) < 200
    assert "10000 chars total" in clamped["company"]["logo"]
    assert clamped["company"]["name"] == "Small"


def test_small_payloads_are_returned_untouched():
    payload = {"items": [{"id": 1}], "total": 1}
    result, note = truncate_payload(payload)
    assert result == payload
    assert note is None


def test_envelope_items_are_sliced_and_annotated():
    payload = {"items": [{"id": i, "name": "n" * 100} for i in range(200)], "total": 200, "page": 1}
    result, note = truncate_payload(payload, budget=4_000)
    assert note is not None
    assert result["_truncated"]["field"] == "items"
    assert result["_truncated"]["total"] == 200
    assert len(result["items"]) == result["_truncated"]["returned"]
    assert len(result["items"]) < 200
    assert json_size(result) <= 6_000
    # The envelope's own metadata survives the slice.
    assert result["page"] == 1


def test_a_bare_list_is_sliced_too():
    payload = [{"id": i, "blob": "b" * 200} for i in range(100)]
    result, note = truncate_payload(payload, budget=2_000)
    assert note["total"] == 100
    assert len(result) == note["returned"] < 100


def test_the_hint_tells_the_model_how_to_get_the_rest():
    payload = {"items": [{"id": i, "name": "n" * 200} for i in range(100)], "total": 100}
    _, note = truncate_payload(payload, budget=2_000)
    assert "page_size" in note["hint"]


def test_an_unsliceable_giant_falls_back_to_the_hard_guard():
    payload = {"blob": "z" * 200_000}
    result, note = truncate_payload(payload, budget=1_000, hard_budget=2_000)
    # Strings are clamped first, so this lands well inside the guard.
    assert json_size(result) <= 2_000
    assert note is not None


def test_csv_is_truncated_by_rows_then_bytes():
    text = "\n".join(f"row,{i}" for i in range(1_000))
    truncated, note = truncate_text(text, max_rows=10, max_bytes=10_000)
    assert note["returned_rows"] == 10
    assert note["total_rows"] == 1_000
    assert "truncated" in truncated


def test_short_csv_is_left_alone():
    truncated, note = truncate_text("a,b\n1,2\n")
    assert note is None
    assert truncated == "a,b\n1,2\n"
