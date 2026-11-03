from datetime import datetime, timedelta
from unittest.mock import patch

from tests.api.test_invoice_dues_allocations import (
    _add_inventory,
    _create_invoice,
    _create_ledger,
    _create_product,
    _create_receipt,
)


def _buckets_by_key(body):
    return {bucket["key"]: bucket for bucket in body["buckets"]}


def test_dues_ageing_buckets_remaining_amounts(client):
    today = datetime.utcnow().date()

    invoice_numbers = iter(
        [
            "INV-535001",
            "INV-535002",
            "INV-535003",
            "INV-535004",
            "INV-535005",
            "INV-535006",
            "INV-535007",
            "INV-535008",
            "INV-535009",
        ]
    )
    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ), patch(
        "src.api.routes.payments.generate_next_number",
        side_effect=["PAY-535001", "PAY-535002", "PAY-535003", "PAY-535004"],
    ):
        ledger_id = _create_ledger(client)
        product_id = _create_product(client)
        _add_inventory(client, product_id)

        _create_invoice(
            client,
            ledger_id,
            product_id,
            100,
            (today + timedelta(days=5)).isoformat(),
            today.isoformat(),
        )
        _create_invoice(
            client,
            ledger_id,
            product_id,
            50,
            today.isoformat(),
            today.isoformat(),
        )
        _create_invoice(
            client,
            ledger_id,
            product_id,
            200,
            (today - timedelta(days=10)).isoformat(),
            today.isoformat(),
        )
        partly_paid = _create_invoice(
            client,
            ledger_id,
            product_id,
            300,
            (today - timedelta(days=40)).isoformat(),
            today.isoformat(),
        )
        _create_invoice(
            client,
            ledger_id,
            product_id,
            150,
            (today - timedelta(days=70)).isoformat(),
            today.isoformat(),
        )
        _create_invoice(
            client,
            ledger_id,
            product_id,
            400,
            (today - timedelta(days=100)).isoformat(),
            today.isoformat(),
        )
        fully_paid = _create_invoice(
            client,
            ledger_id,
            product_id,
            120,
            (today - timedelta(days=20)).isoformat(),
            today.isoformat(),
        )

        _create_receipt(
            client,
            ledger_id,
            100,
            [{"invoice_id": partly_paid["id"], "allocated_amount": 100}],
            datetime.utcnow().isoformat(),
        )
        _create_receipt(
            client,
            ledger_id,
            120,
            [{"invoice_id": fully_paid["id"], "allocated_amount": 120}],
            datetime.utcnow().isoformat(),
        )

        response = client.get("/api/invoices/dues/ageing")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["as_of_date"] == today.isoformat()
        assert body["total_invoice_count"] == 6
        assert body["total_remaining"] == 1100

        buckets = _buckets_by_key(body)
        assert [bucket["key"] for bucket in body["buckets"]] == [
            "not_yet_due",
            "1_30",
            "31_60",
            "61_90",
            "over_90",
        ]
        assert buckets["not_yet_due"] == {
            "key": "not_yet_due",
            "label": "Not yet due",
            "invoice_count": 2,
            "total_remaining": 150,
        }
        assert buckets["1_30"]["invoice_count"] == 1
        assert buckets["1_30"]["total_remaining"] == 200
        assert buckets["31_60"]["invoice_count"] == 1
        assert buckets["31_60"]["total_remaining"] == 200
        assert buckets["61_90"]["invoice_count"] == 1
        assert buckets["61_90"]["total_remaining"] == 150
        assert buckets["over_90"]["invoice_count"] == 1
        assert buckets["over_90"]["total_remaining"] == 400


def test_dues_ageing_responds_to_ledger_and_search_filters(client):
    today = datetime.utcnow().date()

    invoice_numbers = iter(["INV-535101", "INV-535102", "INV-535103", "INV-535104"])
    with patch(
        "src.services.invoice_processor.generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ):
        ledger_id = _create_ledger(client)
        product_id = _create_product(client)
        _add_inventory(client, product_id)
        _create_invoice(
            client,
            ledger_id,
            product_id,
            100,
            (today - timedelta(days=10)).isoformat(),
            today.isoformat(),
        )

        by_ledger = client.get(
            "/api/invoices/dues/ageing", params={"ledger_id": ledger_id}
        )
        assert by_ledger.status_code == 200, by_ledger.text
        assert by_ledger.json()["total_invoice_count"] == 1
        assert by_ledger.json()["total_remaining"] == 100

        by_other_ledger = client.get(
            "/api/invoices/dues/ageing", params={"ledger_id": ledger_id + 999}
        )
        assert by_other_ledger.status_code == 200, by_other_ledger.text
        assert by_other_ledger.json()["total_invoice_count"] == 0

        by_search = client.get(
            "/api/invoices/dues/ageing", params={"search": "Dues"}
        )
        assert by_search.status_code == 200, by_search.text
        assert by_search.json()["total_invoice_count"] == 1

        no_match = client.get(
            "/api/invoices/dues/ageing", params={"search": "no such ledger"}
        )
        assert no_match.status_code == 200, no_match.text
        assert no_match.json()["total_invoice_count"] == 0
        assert no_match.json()["total_remaining"] == 0
