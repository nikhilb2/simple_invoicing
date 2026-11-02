def _ledger_payload(**overrides):
    payload = {
        "name": "Whitespace Ledger",
        "address": "12 Validation Street",
        "gst": "",
        "opening_balance": None,
        "phone_number": "+91 9000000000",
        "email": "ledger@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }
    payload.update(overrides)
    return payload


def test_create_rejects_whitespace_only_name(client):
    response = client.post("/api/ledgers/", json=_ledger_payload(name="   "))
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][-1] == "name"


def test_update_rejects_whitespace_only_name(client):
    created = client.post("/api/ledgers/", json=_ledger_payload())
    assert created.status_code == 200, created.text
    ledger_id = created.json()["id"]

    response = client.put(f"/api/ledgers/{ledger_id}", json=_ledger_payload(name="\t \n"))
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][-1] == "name"


def test_create_rejects_whitespace_only_address(client):
    response = client.post("/api/ledgers/", json=_ledger_payload(address="  "))
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][-1] == "address"


def test_create_allows_empty_phone_but_strips_it(client):
    # phone_number stays optional: tests/core/test_validation.py builds a
    # LedgerCreate with an empty one, and the column accepts an empty string.
    response = client.post("/api/ledgers/", json=_ledger_payload(phone_number="   "))
    assert response.status_code == 200, response.text
    assert response.json()["phone_number"] == ""


def test_create_strips_required_text(client):
    response = client.post(
        "/api/ledgers/",
        json=_ledger_payload(
            name="  Trimmed Ledger  ",
            address=" 42 Trim Street ",
            phone_number=" +91 9111111111 ",
        ),
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["name"] == "Trimmed Ledger"
    assert created["address"] == "42 Trim Street"
    assert created["phone_number"] == "+91 9111111111"
