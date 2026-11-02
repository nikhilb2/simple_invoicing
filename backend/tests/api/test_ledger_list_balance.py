def _create_ledger(client, name, opening_balance=None):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": name,
            "address": "1 Balance Road",
            "phone_number": "9876543210",
            "opening_balance": opening_balance,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_product(client, sku, price, stock=100):
    response = client.post("/api/products/", json={"sku": sku, "name": sku, "price": price, "gst_rate": 0})
    assert response.status_code == 200, response.text
    product_id = response.json()["id"]
    # Sales invoices draw down stock, so seed enough of it to post them.
    adjust = client.post("/api/inventory/adjust", json={"product_id": product_id, "quantity": stock})
    assert adjust.status_code == 200, adjust.text
    return product_id


def _balances_by_name(client):
    response = client.get("/api/ledgers/", params={"page_size": 100})
    assert response.status_code == 200, response.text
    return {item["name"]: item["balance"] for item in response.json()["items"]}


def test_ledger_list_reports_zero_balance_for_a_fresh_ledger(client):
    _create_ledger(client, "Blank Ledger")
    assert _balances_by_name(client)["Blank Ledger"] == 0


def test_ledger_list_balance_covers_opening_sales_and_receipts(client):
    product = _create_product(client, "BAL-1", 100)
    ledger_id = _create_ledger(client, "Balance Buyer", opening_balance=500)

    invoice = client.post(
        "/api/invoices/",
        json={
            "voucher_type": "sales",
            "ledger_id": ledger_id,
            "items": [{"product_id": product, "quantity": 2, "unit_price": 100, "gst_rate": 0}],
        },
    )
    assert invoice.status_code == 200, invoice.text

    receipt = client.post(
        "/api/payments/",
        json={"ledger_id": ledger_id, "voucher_type": "receipt", "amount": 300, "mode": "bank"},
    )
    assert receipt.status_code == 200, receipt.text

    # 500 opening (Dr) + 200 sales (Dr) - 300 receipt (Cr)
    assert _balances_by_name(client)["Balance Buyer"] == 400


def test_ledger_list_balance_is_negative_when_the_ledger_is_in_credit(client):
    product = _create_product(client, "BAL-2", 100)
    ledger_id = _create_ledger(client, "Supplier Ledger")

    purchase = client.post(
        "/api/invoices/",
        json={
            "voucher_type": "purchase",
            "ledger_id": ledger_id,
            "items": [{"product_id": product, "quantity": 3, "unit_price": 100, "gst_rate": 0}],
        },
    )
    assert purchase.status_code == 200, purchase.text

    payment = client.post(
        "/api/payments/",
        json={"ledger_id": ledger_id, "voucher_type": "payment", "amount": 100, "mode": "bank"},
    )
    assert payment.status_code == 200, payment.text

    # 100 payment (Dr) - 300 purchase (Cr)
    assert _balances_by_name(client)["Supplier Ledger"] == -200


def test_ledger_list_balance_matches_the_statement_closing_balance(client):
    product = _create_product(client, "BAL-3", 250)
    ledger_id = _create_ledger(client, "Statement Buyer", opening_balance=-125)

    invoice = client.post(
        "/api/invoices/",
        json={
            "voucher_type": "sales",
            "ledger_id": ledger_id,
            "items": [{"product_id": product, "quantity": 2, "unit_price": 250, "gst_rate": 0}],
        },
    )
    assert invoice.status_code == 200, invoice.text

    invoice_item_id = invoice.json()["items"][0]["id"]
    credit_note = client.post(
        "/api/credit-notes/",
        json={
            "ledger_id": ledger_id,
            "invoice_ids": [invoice.json()["id"]],
            "credit_note_type": "return",
            "items": [{"invoice_id": invoice.json()["id"], "invoice_item_id": invoice_item_id, "quantity": 1}],
        },
    )
    assert credit_note.status_code in (200, 201), credit_note.text

    statement = client.get(
        f"/api/ledgers/{ledger_id}/statement",
        params={"from_date": "1990-01-01", "to_date": "2999-12-31"},
    )
    assert statement.status_code == 200, statement.text

    closing_balance = statement.json()["closing_balance"]
    # 500 sales (Dr) - 125 opening (Cr) - 250 returned on the credit note (Cr)
    assert closing_balance == 125
    assert _balances_by_name(client)["Statement Buyer"] == closing_balance
