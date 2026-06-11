"""Tests for POST /api/email/bulk-dues-reminder"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.routes.email import BulkDuesReminderRequest, send_bulk_dues_reminder
from src.models.buyer import Buyer as Ledger
from src.models.invoice import Invoice
from src.models.user import User, UserRole


def _invoice(
    *,
    id: int,
    ledger_id: int = 1,
    total_amount: float = 1000.0,
    due_date: datetime = datetime(2026, 6, 15),
    voucher_type: str = "sales",
    status: str = "active",
) -> Invoice:
    inv = Invoice()
    inv.id = id
    inv.ledger_id = ledger_id
    inv.total_amount = total_amount
    inv.due_date = due_date
    inv.voucher_type = voucher_type
    inv.status = status
    inv.invoice_number = f"INV-{id:03d}"
    inv.invoice_date = datetime(2026, 5, 1)
    inv.ledger_name = f"Ledger {ledger_id}"
    inv.company_id = 1
    return inv


class TestBulkDuesReminderRequest:
    def test_defaults(self):
        req = BulkDuesReminderRequest()
        assert req.due_date_from is None
        assert req.due_date_to is None
        assert req.ledger_id is None
        assert req.subject is None
        assert req.message is None

    def test_with_filters(self):
        req = BulkDuesReminderRequest(
            due_date_from=date(2026, 6, 1),
            due_date_to=date(2026, 6, 30),
            ledger_id=5,
        )
        assert req.due_date_from == date(2026, 6, 1)
        assert req.due_date_to == date(2026, 6, 30)
        assert req.ledger_id == 5


class TestBulkDuesReminderEndpoint:
    def test_no_invoices_returns_empty(self):
        """When the query returns no invoices, the endpoint returns zero counts."""
        db = MagicMock()
        db.query().filter().filter().order_by().all.return_value = []

        active_company = SimpleNamespace(id=1)
        current_user = SimpleNamespace(id=1)

        import asyncio
        result = asyncio.run(
            send_bulk_dues_reminder(
                payload=BulkDuesReminderRequest(),
                db=db,
                current_user=current_user,
                active_company=active_company,
            )
        )

        assert result == {"sent": 0, "failed": 0, "results": []}

    def test_all_invoices_fully_paid_returns_empty(self):
        """Invoices with remaining_amount == 0 are skipped."""
        inv = _invoice(id=1)

        db = MagicMock()
        db.query().filter().filter().order_by().all.return_value = [inv]

        from src.services.invoice_payments import InvoicePaymentSummary

        summary = InvoicePaymentSummary(
            invoice_id=1,
            credited_amount=0,
            paid_amount=1000.0,
            remaining_amount=0,
            outstanding_amount=0,
            payment_status="paid",
            due_in_days=0,
        )

        active_company = SimpleNamespace(id=1)
        current_user = SimpleNamespace(id=1)

        with patch(
            "src.api.routes.email.build_invoice_payment_summaries",
            return_value={1: summary},
        ):
            import asyncio

            result = asyncio.run(
                send_bulk_dues_reminder(
                    payload=BulkDuesReminderRequest(),
                    db=db,
                    current_user=current_user,
                    active_company=active_company,
                )
            )

        assert result == {"sent": 0, "failed": 0, "results": []}

    def test_sends_reminder_to_ledger_with_dues(self):
        """An outstanding invoice triggers a reminder to its ledger."""
        inv = _invoice(id=1, ledger_id=10, total_amount=1000.0)

        db = MagicMock()
        db.query().filter().filter().order_by().all.return_value = [inv]

        from src.services.invoice_payments import InvoicePaymentSummary

        summary = InvoicePaymentSummary(
            invoice_id=1,
            credited_amount=0,
            paid_amount=0,
            remaining_amount=1000.0,
            outstanding_amount=1000.0,
            payment_status="unpaid",
            due_in_days=5,
        )

        ledger = Ledger()
        ledger.id = 10
        ledger.name = "Test Ledger"
        ledger.email = "ledger@example.com"

        # Second db.query() call is for ledgers lookup
        db.query().filter().order_by().all.return_value = [inv]
        db.query().filter().all.return_value = [ledger]

        active_company = SimpleNamespace(id=1, name="TestCo", currency_code="INR")
        current_user = SimpleNamespace(id=1)

        with patch(
            "src.api.routes.email.build_invoice_payment_summaries",
            return_value={1: summary},
        ), patch(
            "src.api.routes.email._send_payment_reminder_for_ledger",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = {
                "ledger_id": 10,
                "ledger_name": "Test Ledger",
                "email": "ledger@example.com",
                "status": "sent",
                "error": None,
            }

            import asyncio

            result = asyncio.run(
                send_bulk_dues_reminder(
                    payload=BulkDuesReminderRequest(),
                    db=db,
                    current_user=current_user,
                    active_company=active_company,
                )
            )

        assert result["sent"] == 1
        assert result["failed"] == 0
        assert len(result["results"]) == 1
        assert result["results"][0]["status"] == "sent"

    def test_handles_ledger_not_found(self):
        """When a ledger ID from invoices has no matching ledger, it's skipped."""
        inv = _invoice(id=1, ledger_id=99)

        db = MagicMock()
        db.query().filter().filter().order_by().all.return_value = [inv]

        from src.services.invoice_payments import InvoicePaymentSummary

        summary = InvoicePaymentSummary(
            invoice_id=1,
            credited_amount=0,
            paid_amount=0,
            remaining_amount=500.0,
            outstanding_amount=500.0,
            payment_status="partial",
            due_in_days=10,
        )

        # Ledgers lookup returns empty list for ID 99
        db.query().filter().all.return_value = []

        active_company = SimpleNamespace(id=1)
        current_user = SimpleNamespace(id=1)

        with patch(
            "src.api.routes.email.build_invoice_payment_summaries",
            return_value={1: summary},
        ):
            import asyncio

            result = asyncio.run(
                send_bulk_dues_reminder(
                    payload=BulkDuesReminderRequest(),
                    db=db,
                    current_user=current_user,
                    active_company=active_company,
                )
            )

        assert result["sent"] == 0
        assert result["failed"] == 0
        assert len(result["results"]) == 1
        assert result["results"][0]["status"] == "skipped"
        assert "Ledger not found" in result["results"][0]["error"]

    def test_ledger_filter_is_respected(self):
        """When ledger_id filter is provided, only that ledger's invoices are queried."""
        inv = _invoice(id=1, ledger_id=5)

        db = MagicMock()
        db.query().filter().filter().filter().order_by().all.return_value = [inv]

        from src.services.invoice_payments import InvoicePaymentSummary

        summary = InvoicePaymentSummary(
            invoice_id=1,
            credited_amount=0,
            paid_amount=0,
            remaining_amount=500.0,
            outstanding_amount=500.0,
            payment_status="partial",
            due_in_days=10,
        )

        ledger = Ledger()
        ledger.id = 5
        ledger.name = "Target Ledger"
        ledger.email = "target@example.com"

        db.query().filter().all.return_value = [ledger]

        active_company = SimpleNamespace(id=1)
        current_user = SimpleNamespace(id=1)

        with patch(
            "src.api.routes.email.build_invoice_payment_summaries",
            return_value={1: summary},
        ), patch(
            "src.api.routes.email._send_payment_reminder_for_ledger",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = {
                "ledger_id": 5,
                "ledger_name": "Target Ledger",
                "email": "target@example.com",
                "status": "sent",
                "error": None,
            }

            import asyncio

            result = asyncio.run(
                send_bulk_dues_reminder(
                    payload=BulkDuesReminderRequest(ledger_id=5),
                    db=db,
                    current_user=current_user,
                    active_company=active_company,
                )
            )

        assert result["sent"] == 1
        assert len(result["results"]) == 1
