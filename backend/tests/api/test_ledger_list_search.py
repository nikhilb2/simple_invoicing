def _create_ledger(client, name, phone_number="9876543210", gst=None, email=None):
    payload = {
        "name": name,
        "address": "1 Search Road",
        "phone_number": phone_number,
    }
    if gst is not None:
        payload["gst"] = gst
    if email is not None:
        payload["email"] = email
    response = client.post("/api/ledgers/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _search_names(client, search, params=None):
    query = {"page_size": 100, "search": search}
    if params:
        query.update(params)
    response = client.get("/api/ledgers/", params=query)
    assert response.status_code == 200, response.text
    body = response.json()
    return [item["name"] for item in body["items"]], body["total"]


def _setup_search_ledgers(client):
    _create_ledger(
        client,
        "Alpha Traders",
        phone_number="9876543210",
        gst="27ABCDE1234F1Z0",
        email="alpha@example.com",
    )
    _create_ledger(client, "Beta Traders", phone_number="9123456789")
    _create_ledger(client, "50% Off Traders", phone_number="9000000000")
    _create_ledger(client, "Under_Score Traders", phone_number="9111111111")


def test_ledger_list_search_matches_gst(client):
    _setup_search_ledgers(client)
    names, total = _search_names(client, "ABCDE1234")
    assert names == ["Alpha Traders"]
    assert total == 1


def test_ledger_list_search_matches_gst_case_insensitively(client):
    _setup_search_ledgers(client)
    names, total = _search_names(client, "abcde1234")
    assert names == ["Alpha Traders"]
    assert total == 1


def test_ledger_list_search_matches_phone_fragment(client):
    _setup_search_ledgers(client)
    names, total = _search_names(client, "7654")
    assert names == ["Alpha Traders"]
    assert total == 1


def test_ledger_list_search_matches_email_fragment(client):
    _setup_search_ledgers(client)
    names, total = _search_names(client, "example.com")
    assert names == ["Alpha Traders"]
    assert total == 1


def test_ledger_list_search_by_name_is_unchanged(client):
    _setup_search_ledgers(client)
    names, total = _search_names(client, "Beta")
    assert names == ["Beta Traders"]
    assert total == 1


def test_ledger_list_search_escapes_percent(client):
    _setup_search_ledgers(client)
    names, total = _search_names(client, "50%")
    assert names == ["50% Off Traders"]
    assert total == 1


def test_ledger_list_search_escapes_underscore(client):
    _setup_search_ledgers(client)
    names, total = _search_names(client, "_")
    assert names == ["Under_Score Traders"]
    assert total == 1


def test_ledger_list_search_by_gst_works_with_balance_desc_sort(client):
    _setup_search_ledgers(client)
    names, total = _search_names(client, "ABCDE1234", {"sort": "balance_desc"})
    assert names == ["Alpha Traders"]
    assert total == 1
