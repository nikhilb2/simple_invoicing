"""`search` and `fetch` — the two tools ChatGPT connectors require."""

from __future__ import annotations

import json

import pytest

from src.core.config import settings
from src.mcp_server.connector import DEEP_LINKS, deep_link, parse_identifier


def _ledger_payload(name: str):
    return {
        "name": name,
        "address": "5 Search Street",
        "gst": "",
        "opening_balance": None,
        "phone_number": "+91 9111111111",
        "email": "search@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def _product_payload(name: str, sku: str):
    return {
        "sku": sku,
        "name": name,
        "description": "A searchable widget",
        "hsn_sac": "1234",
        "price": 100.0,
        "purchase_price": 60.0,
        "gst_rate": 18.0,
        "unit": "Pieces",
        "allow_decimal": False,
        "maintain_inventory": True,
        "is_producable": False,
        "production_cost": None,
        "reorder_level": 0,
        "initial_quantity": 5,
        "track_serials": False,
    }


@pytest.fixture
def seeded(client, company):
    headers = {"X-Company-Id": str(company.id)}
    ledger = client.post("/api/ledgers/", json=_ledger_payload("Zenith Traders"), headers=headers)
    assert ledger.status_code == 200, ledger.text
    product = client.post("/api/products/", json=_product_payload("Zenith Widget", "ZW-1"), headers=headers)
    assert product.status_code == 200, product.text
    return {"ledger": ledger.json(), "product": product.json()}


def _structured(body):
    return body["result"]["structuredContent"]


def test_search_finds_across_corpora(mcp_call, seeded):
    payload = _structured(mcp_call.call_tool("search", {"query": "Zenith"}))
    ids = {result["id"] for result in payload["results"]}
    assert f"ledger:{seeded['ledger']['id']}" in ids
    assert f"product:{seeded['product']['id']}" in ids


def test_search_results_carry_a_real_deep_link(mcp_call, seeded):
    payload = _structured(mcp_call.call_tool("search", {"query": "Zenith"}))
    for result in payload["results"]:
        # ChatGPT renders no citation at all without a real url.
        assert result["url"].startswith(settings.PUBLIC_APP_BASE_URL.rstrip("/"))
        assert result["title"]


def test_search_returns_the_payload_twice(mcp_call, seeded):
    """ChatGPT reads structuredContent; other clients read the JSON string."""
    result = mcp_call.call_tool("search", {"query": "Zenith"})["result"]
    assert result["structuredContent"] == json.loads(result["content"][0]["text"])


def test_search_can_be_restricted_by_type(mcp_call, seeded):
    payload = _structured(mcp_call.call_tool("search", {"query": "Zenith", "types": ["ledger"]}))
    assert all(result["id"].startswith("ledger:") for result in payload["results"])


def test_search_honours_the_limit(mcp_call, client, company):
    headers = {"X-Company-Id": str(company.id)}
    for index in range(8):
        client.post("/api/ledgers/", json=_ledger_payload(f"Limitcase {index}"), headers=headers)
    payload = _structured(mcp_call.call_tool("search", {"query": "Limitcase", "limit": 3}))
    assert len(payload["results"]) == 3


def test_search_with_an_empty_query_returns_nothing(mcp_call, seeded):
    payload = _structured(mcp_call.call_tool("search", {"query": "  "}))
    assert payload["results"] == []


def test_fetch_a_ledger_renders_markdown_not_json(mcp_call, seeded):
    payload = _structured(mcp_call.call_tool("fetch", {"id": f"ledger:{seeded['ledger']['id']}"}))
    assert payload["text"].startswith("# Ledger Zenith Traders")
    assert "5 Search Street" in payload["text"]
    assert payload["url"].endswith(f"/ledgers/{seeded['ledger']['id']}")


def test_fetch_metadata_is_a_flat_string_map(mcp_call, seeded):
    payload = _structured(mcp_call.call_tool("fetch", {"id": f"ledger:{seeded['ledger']['id']}"}))
    assert isinstance(payload["metadata"], dict)
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in payload["metadata"].items())


def test_fetch_a_product_works_without_a_get_by_id_route(mcp_call, seeded):
    """There is no GET /api/products/{id}; fetch pages the list instead."""
    payload = _structured(mcp_call.call_tool("fetch", {"id": f"product:{seeded['product']['id']}"}))
    assert "Zenith Widget" in payload["title"]
    assert "ZW-1" in payload["text"]


def test_fetch_returns_the_payload_twice(mcp_call, seeded):
    result = mcp_call.call_tool("fetch", {"id": f"ledger:{seeded['ledger']['id']}"})["result"]
    assert result["structuredContent"] == json.loads(result["content"][0]["text"])


def test_fetch_an_unknown_type_explains_the_id_format(mcp_call, seeded):
    result = mcp_call.call_tool("fetch", {"id": "widget:1"})["result"]
    assert result["isError"] is True
    assert "Unknown record type" in result["content"][0]["text"]


def test_fetch_a_missing_record_is_a_tool_error(mcp_call, seeded):
    result = mcp_call.call_tool("fetch", {"id": "ledger:999999"})["result"]
    assert result["isError"] is True
    assert "No ledger found" in result["content"][0]["text"]


def test_fetch_without_an_id_is_a_tool_error(mcp_call, seeded):
    result = mcp_call.call_tool("fetch", {"id": ""})["result"]
    assert result["isError"] is True


def test_search_and_fetch_declare_an_output_schema(mcp_call, company):
    tools = {tool["name"]: tool for tool in mcp_call.list_tools()}
    assert "outputSchema" in tools["search"]
    assert "outputSchema" in tools["fetch"]
    assert tools["search"]["outputSchema"]["required"] == ["results"]


def test_search_is_scoped_to_the_principals_company(mcp_call, client, db_session, company, seeded):
    from src.models.company import CompanyProfile
    from tests.mcp.conftest import make_principal

    other = CompanyProfile(
        name="Elsewhere", address="", gst="", phone_number="", currency_code="INR",
        email="", website="", bank_name="", branch_name="", account_name="",
        account_number="", ifsc_code="",
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    client.post("/api/ledgers/", json=_ledger_payload("Zenith Elsewhere"),
                headers={"X-Company-Id": str(other.id)})

    payload = _structured(
        mcp_call.call_tool("search", {"query": "Zenith"}, principal=make_principal(company_id=company.id))
    )
    titles = " ".join(result["title"] for result in payload["results"])
    assert "Zenith Elsewhere" not in titles


def test_every_corpus_has_a_deep_link_template():
    from src.mcp_server.connector import SEARCH_CORPORA

    for corpus in SEARCH_CORPORA:
        assert corpus["kind"] in DEEP_LINKS


def test_deep_link_uses_the_public_app_origin():
    assert deep_link("invoice", 7).startswith(settings.PUBLIC_APP_BASE_URL.rstrip("/"))
    assert deep_link("invoice", 7).endswith("invoice_id=7")


def test_identifier_parsing():
    assert parse_identifier("invoice:123") == ("invoice", "123")
    assert parse_identifier("serial:ABC-123") == ("serial", "ABC-123")
