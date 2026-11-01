"""The reminder's "last payment" line must only count money received.

A ledger can be both customer and supplier. Before this, the single reminder picked
the newest active payment of *any* voucher type, so a payment made *to* the party
was reported as their last payment, while the bulk reminder (which filters on
receipts) reported the right one. Both now share one query.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

RECEIPT_DATE = datetime(2026, 3, 1, 10, 0, 0)
PAYMENT_DATE = datetime(2026, 3, 20, 10, 0, 0)


def _create_ledger(client):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": "Dual Role Ledger",
            "address": "Mumbai",
            "gst": "27ABCDE1234F1Z0",
            "phone_number": "9999999999",
            "email": "ledger@example.com",
            "website": "",
            "bank_name": "",
            "branch_name": "",
            "account_name": "",
            "account_number": "",
            "ifsc_code": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_product(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "REM-001",
            "name": "Reminder Product",
            "description": "",
            "hsn_sac": "9988",
            "price": 100,
            "gst_rate": 0,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _add_inventory(client, product_id, quantity=50):
    response = client.post(
        "/api/inventory/adjust",
        json={"product_id": product_id, "quantity": quantity},
    )
    assert response.status_code == 200, response.text


def _create_invoice(client, ledger_id, product_id, unit_price):
    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "sales",
            "tax_inclusive": False,
            "apply_round_off": False,
            "invoice_date": "2026-02-01",
            "due_date": "2026-02-15",
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": unit_price}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_voucher(client, ledger_id, voucher_type, amount, dt, allocations=None):
    response = client.post(
        "/api/payments/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": voucher_type,
            "amount": amount,
            "date": dt.isoformat(),
            "mode": "bank",
            "invoice_allocations": allocations or [],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _send_single_reminder(client, ledger_id):
    with patch("src.api.routes.email.send_email", new=AsyncMock()) as send_email_mock:
        response = client.post(f"/api/email/payment-reminder/{ledger_id}", json={})
    assert response.status_code == 200, response.text
    send_email_mock.assert_awaited_once()
    return send_email_mock.await_args.kwargs["html_body"]


def _seed(client):
    invoice_numbers = iter(["INV-000101", "INV-000102"])
    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ), patch(
        "src.api.routes.payments.generate_next_number",
        return_value="PAY-000101",
    ):
        ledger_id = _create_ledger(client)
        product_id = _create_product(client)
        _add_inventory(client, product_id)
        invoice = _create_invoice(client, ledger_id, product_id, 1000)
    return ledger_id, invoice


def test_single_reminder_reports_the_last_receipt_not_the_last_payment_out(client):
    ledger_id, invoice = _seed(client)

    _create_voucher(
        client,
        ledger_id,
        "receipt",
        100,
        RECEIPT_DATE,
        [{"invoice_id": invoice["id"], "allocated_amount": 100}],
    )
    # Money paid *out* to the same party, later than the receipt.
    _create_voucher(client, ledger_id, "payment", 200, PAYMENT_DATE)

    html_body = _send_single_reminder(client, ledger_id)

    assert "Last payment received on 01 Mar 2026" in html_body
    assert "20 Mar 2026" not in html_body


def test_single_reminder_omits_the_line_when_nothing_was_ever_received(client):
    ledger_id, _invoice = _seed(client)

    # Only an outgoing payment, so there is no "last payment received" to show.
    _create_voucher(client, ledger_id, "payment", 200, PAYMENT_DATE)

    html_body = _send_single_reminder(client, ledger_id)

    assert "Last payment received on" not in html_body
    assert "20 Mar 2026" not in html_body
