def _ledger_payload(name: str, opening_balance=None):
    return {
        "name": name,
        "address": "123 Opening Street",
        "gst": "27ABCDE1234F1Z5",
        "opening_balance": opening_balance,
        "phone_number": "+91 9999999999",
        "email": "ledger@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def test_create_ledger_creates_opening_balance_payment(client):
    create_response = client.post("/api/ledgers/", json=_ledger_payload("Opening Ledger A", 150.25))
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()

    assert created["opening_balance"] == 150.25

    get_response = client.get(f"/api/ledgers/{created['id']}")
    assert get_response.status_code == 200, get_response.text
    fetched = get_response.json()
    assert fetched["opening_balance"] == 150.25

    payments_response = client.get("/api/payments/", params={"ledger_id": created["id"]})
    assert payments_response.status_code == 200, payments_response.text
    payments = payments_response.json()
    assert len(payments) == 1
    assert payments[0]["voucher_type"] == "opening_balance"
    assert payments[0]["amount"] == 150.25
    assert payments[0]["payment_number"] is None


def test_update_ledger_updates_and_clears_opening_balance(client):
    create_response = client.post("/api/ledgers/", json=_ledger_payload("Opening Ledger B", 100))
    assert create_response.status_code == 200, create_response.text
    ledger_id = create_response.json()["id"]

    update_response = client.put(f"/api/ledgers/{ledger_id}", json=_ledger_payload("Opening Ledger B", -40))
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["opening_balance"] == -40

    payments_response = client.get("/api/payments/", params={"ledger_id": ledger_id})
    assert payments_response.status_code == 200, payments_response.text
    payments = payments_response.json()
    assert len(payments) == 1
    assert payments[0]["amount"] == -40
    assert payments[0]["voucher_type"] == "opening_balance"

    clear_response = client.put(f"/api/ledgers/{ledger_id}", json=_ledger_payload("Opening Ledger B", None))
    assert clear_response.status_code == 200, clear_response.text
    cleared = clear_response.json()
    assert cleared["opening_balance"] is None

    payments_after_clear = client.get("/api/payments/", params={"ledger_id": ledger_id}).json()
    assert payments_after_clear == []
