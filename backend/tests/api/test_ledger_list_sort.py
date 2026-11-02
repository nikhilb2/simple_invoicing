def _create_ledger(client, name, opening_balance=None):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": name,
            "address": "1 Sort Road",
            "phone_number": "9876543210",
            "opening_balance": opening_balance,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _list_names(client, params=None):
    query = {"page_size": 100}
    if params:
        query.update(params)
    response = client.get("/api/ledgers/", params=query)
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()["items"]]


def _setup_names(client):
    _create_ledger(client, "Zulu Ledger")
    _create_ledger(client, "Alpha Ledger")
    _create_ledger(client, "Mike Ledger")


def test_ledger_list_default_order_is_name_a_to_z(client):
    _setup_names(client)
    assert _list_names(client) == ["Alpha Ledger", "Mike Ledger", "Zulu Ledger"]


def test_ledger_list_sort_name_is_explicit_a_to_z(client):
    _setup_names(client)
    assert _list_names(client, {"sort": "name"}) == ["Alpha Ledger", "Mike Ledger", "Zulu Ledger"]


def test_ledger_list_sort_reverse_name_is_z_to_a(client):
    _setup_names(client)
    assert _list_names(client, {"sort": "-name"}) == ["Zulu Ledger", "Mike Ledger", "Alpha Ledger"]


def test_ledger_list_sort_newest_is_reverse_creation_order(client):
    _create_ledger(client, "Newest Alpha")
    _create_ledger(client, "Newest Beta")
    _create_ledger(client, "Newest Gamma")
    assert _list_names(client, {"sort": "newest"}) == ["Newest Gamma", "Newest Beta", "Newest Alpha"]


def test_ledger_list_sort_balance_desc_orders_by_closing_balance(client):
    _create_ledger(client, "Low Ledger", opening_balance=-200)
    _create_ledger(client, "High Ledger", opening_balance=500)
    _create_ledger(client, "Mid Ledger", opening_balance=100)
    assert _list_names(client, {"sort": "balance_desc"}) == ["High Ledger", "Mid Ledger", "Low Ledger"]


def test_ledger_list_sort_balance_desc_paginates_after_sorting(client):
    _create_ledger(client, "Low Ledger", opening_balance=-200)
    _create_ledger(client, "High Ledger", opening_balance=500)
    _create_ledger(client, "Mid Ledger", opening_balance=100)
    first_page = _list_names(client, {"sort": "balance_desc", "page": 1, "page_size": 2})
    second_page = _list_names(client, {"sort": "balance_desc", "page": 2, "page_size": 2})
    assert first_page == ["High Ledger", "Mid Ledger"]
    assert second_page == ["Low Ledger"]


def test_ledger_list_unknown_sort_returns_422(client):
    _create_ledger(client, "Only Ledger")
    response = client.get("/api/ledgers/", params={"sort": "bogus"})
    assert response.status_code == 422
