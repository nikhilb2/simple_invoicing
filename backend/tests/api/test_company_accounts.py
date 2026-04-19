def _ledger_payload(name: str, gst: str):
    return {
        "name": name,
        "address": "123 Finance Street",
        "gst": gst,
        "opening_balance": None,
        "phone_number": "+91 9999999999",
        "email": "ledger@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def test_company_account_create_list_and_deactivate(client):
    create_response = client.post(
        "/api/company-accounts/",
        json={
            "account_type": "bank",
            "display_name": "Main HDFC",
            "bank_name": "HDFC Bank",
            "opening_balance": 1000,
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    assert created["display_name"] == "Main HDFC"
    assert created["account_type"] == "bank"
    assert created["is_active"] is True

    list_active = client.get("/api/company-accounts/")
    assert list_active.status_code == 200, list_active.text
    active_items = list_active.json()
    assert len(active_items) == 1
    assert active_items[0]["id"] == created["id"]

    deactivate_response = client.delete(f"/api/company-accounts/{created['id']}")
    assert deactivate_response.status_code == 200, deactivate_response.text

    list_after_deactivate = client.get("/api/company-accounts/")
    assert list_after_deactivate.status_code == 200, list_after_deactivate.text
    assert list_after_deactivate.json() == []

    list_including_inactive = client.get("/api/company-accounts/", params={"include_inactive": True})
    assert list_including_inactive.status_code == 200, list_including_inactive.text
    all_items = list_including_inactive.json()
    assert len(all_items) == 1
    assert all_items[0]["is_active"] is False


def test_payment_supports_company_account_assignment_and_unassignment(client):
    ledger_response = client.post("/api/ledgers/", json=_ledger_payload("Ledger Cash Flow", "27ABCDE1234F1Z5"))
    assert ledger_response.status_code == 200, ledger_response.text
    ledger_id = ledger_response.json()["id"]

    account_response = client.post(
        "/api/company-accounts/",
        json={
            "account_type": "cash",
            "display_name": "Cash In Hand",
            "opening_balance": 250,
        },
    )
    assert account_response.status_code == 200, account_response.text
    account = account_response.json()

    payment_response = client.post(
        "/api/payments/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "receipt",
            "amount": 500,
            "account_id": account["id"],
            "mode": "cash",
        },
    )
    assert payment_response.status_code == 200, payment_response.text
    payment = payment_response.json()
    assert payment["account_id"] == account["id"]
    assert payment["account_display_name"] == "Cash In Hand"
    assert payment["account_type"] == "cash"

    update_response = client.put(
        f"/api/payments/{payment['id']}",
        json={
            "voucher_type": "receipt",
            "amount": 500,
            "account_id": None,
            "mode": "cash",
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["account_id"] is None
    assert updated["account_display_name"] is None

    day_book_response = client.get(
        "/api/ledgers/day-book",
        params={"from_date": "2000-01-01", "to_date": "2100-12-31"},
    )
    assert day_book_response.status_code == 200, day_book_response.text
    entries = [entry for entry in day_book_response.json()["entries"] if entry["entry_type"] == "payment"]
    assert len(entries) == 1
    assert entries[0]["account_display_name"] is None


def test_account_only_cash_bank_entry_lifecycle(client):
    account_response = client.post(
        "/api/company-accounts/",
        json={
            "account_type": "cash",
            "display_name": "Cash Counter",
            "opening_balance": 0,
        },
    )
    assert account_response.status_code == 200, account_response.text
    account_id = account_response.json()["id"]

    create_response = client.post(
        "/api/payments/",
        json={
            "voucher_type": "payment",
            "amount": 1200,
            "account_id": account_id,
            "mode": "cash",
            "notes": "ATM withdrawal",
            "date": "2026-04-19T10:00:00",
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    assert created["ledger_id"] is None
    assert created["account_id"] == account_id
    assert created["notes"] == "ATM withdrawal"

    update_response = client.put(
        f"/api/payments/{created['id']}",
        json={
            "voucher_type": "receipt",
            "amount": 800,
            "account_id": account_id,
            "mode": "cash",
            "notes": "Cash deposit",
            "date": "2026-04-20T09:30:00",
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["voucher_type"] == "receipt"
    assert updated["amount"] == 800
    assert updated["notes"] == "Cash deposit"

    delete_response = client.delete(f"/api/payments/{created['id']}")
    assert delete_response.status_code == 200, delete_response.text

    list_active_response = client.get("/api/payments/")
    assert list_active_response.status_code == 200, list_active_response.text
    active_ids = [item["id"] for item in list_active_response.json()]
    assert created["id"] not in active_ids

    list_all_response = client.get("/api/payments/", params={"include_cancelled": True})
    assert list_all_response.status_code == 200, list_all_response.text
    cancelled = [item for item in list_all_response.json() if item["id"] == created["id"]]
    assert len(cancelled) == 1
    assert cancelled[0]["status"] == "cancelled"
