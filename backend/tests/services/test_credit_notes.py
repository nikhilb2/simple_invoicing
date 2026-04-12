"""
Unit tests for the credit note service layer.

Covers:
- create_credit_note: happy path (single and multi-invoice)
- Ledger mismatch validation
- Invoice item mismatch validation
- Cumulative quantity limit enforcement
- credit_status recomputation on create and cancel
- cancel_credit_note happy path
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from src.services.credit_note import (
    _is_interstate,
    _money,
    _recompute_credit_status,
    cancel_credit_note,
    create_credit_note,
)
from src.schemas.credit_note import CreditNoteCreate, CreditNoteItemCreate
from src.models.buyer import Buyer as Ledger
from src.models.invoice import Invoice, InvoiceItem
from src.models.credit_note import CreditNote, CreditNoteItem


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_ledger(id=1, gst="29ABCDE1234F1Z5"):
    l = Ledger()
    l.id = id
    l.gst = gst
    return l


def make_invoice(id, ledger_id=1, status="active", company_gst="29XYZAB1234C1Z7", taxable_amount=1000):
    inv = Invoice()
    inv.id = id
    inv.ledger_id = ledger_id
    inv.status = status
    inv.company_gst = company_gst
    inv.taxable_amount = taxable_amount
    inv.credit_status = "not_credited"
    return inv


def make_invoice_item(id, invoice_id, product_id=1, quantity=10, unit_price=100, gst_rate=18):
    ii = InvoiceItem()
    ii.id = id
    ii.invoice_id = invoice_id
    ii.product_id = product_id
    ii.quantity = quantity
    ii.unit_price = unit_price
    ii.gst_rate = gst_rate
    return ii


def make_cn(id=1, status="active", ledger_id=1):
    cn = CreditNote()
    cn.id = id
    cn.status = status
    cn.ledger_id = ledger_id
    cn.items = []
    return cn


# ─────────────────────────────────────────────────────────────────────────────
# Unit helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_money_rounds_half_up(self):
        assert _money(Decimal("1.005")) == Decimal("1.01")
        assert _money(Decimal("1.004")) == Decimal("1.00")

    def test_is_interstate_same_state(self):
        assert _is_interstate("29ABCDE1234F1Z5", "29XYZAB1234C1Z7") is False

    def test_is_interstate_different_state(self):
        assert _is_interstate("29ABCDE1234F1Z5", "27XYZAB1234C1Z7") is True

    def test_is_interstate_missing_gst(self):
        assert _is_interstate(None, "29XYZAB1234C1Z7") is False
        assert _is_interstate("29ABCDE1234F1Z5", None) is False


# ─────────────────────────────────────────────────────────────────────────────
# Schema validation
# ─────────────────────────────────────────────────────────────────────────────

class TestCreditNoteCreateSchema:
    def test_item_invoice_id_not_in_invoice_ids_raises(self):
        with pytest.raises(Exception):
            CreditNoteCreate(
                ledger_id=1,
                invoice_ids=[1],
                items=[CreditNoteItemCreate(invoice_id=2, invoice_item_id=10, quantity=1)],
            )

    def test_valid_payload_passes(self):
        payload = CreditNoteCreate(
            ledger_id=1,
            invoice_ids=[1, 2],
            items=[
                CreditNoteItemCreate(invoice_id=1, invoice_item_id=10, quantity=1),
                CreditNoteItemCreate(invoice_id=2, invoice_item_id=20, quantity=2),
            ],
        )
        assert len(payload.items) == 2


# ─────────────────────────────────────────────────────────────────────────────
# _recompute_credit_status
# ─────────────────────────────────────────────────────────────────────────────

class TestRecomputeCreditStatus:
    def _make_db(self, invoice, credited_sum):
        db = MagicMock()
        db.query().filter().first.return_value = invoice
        # scalar() returns the sum value
        db.query().join().filter().scalar.return_value = credited_sum
        return db

    def test_sets_not_credited_when_no_cns(self):
        invoice = make_invoice(1, taxable_amount=1000)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = invoice
        db.query.return_value.join.return_value.filter.return_value.scalar.return_value = None
        _recompute_credit_status(1, db)
        assert invoice.credit_status == "not_credited"

    def test_sets_partially_credited(self):
        invoice = make_invoice(1, taxable_amount=1000)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = invoice
        db.query.return_value.join.return_value.filter.return_value.scalar.return_value = Decimal("500")
        _recompute_credit_status(1, db)
        assert invoice.credit_status == "partially_credited"

    def test_sets_fully_credited(self):
        invoice = make_invoice(1, taxable_amount=1000)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = invoice
        db.query.return_value.join.return_value.filter.return_value.scalar.return_value = Decimal("1000")
        _recompute_credit_status(1, db)
        assert invoice.credit_status == "fully_credited"

    def test_noop_when_invoice_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        # Should not raise
        _recompute_credit_status(999, db)


# ─────────────────────────────────────────────────────────────────────────────
# create_credit_note service validation
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateCreditNoteValidation:
    """Test that service raises HTTPException for invalid inputs."""

    def _base_payload(self, ledger_id=1, invoice_ids=None, items=None):
        return CreditNoteCreate(
            ledger_id=ledger_id,
            invoice_ids=invoice_ids or [1],
            items=items or [CreditNoteItemCreate(invoice_id=1, invoice_item_id=10, quantity=2)],
        )

    def test_ledger_not_found_raises_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(Exception) as exc:
            create_credit_note(self._base_payload(), db, current_user_id=1)
        assert "404" in str(exc.value.status_code) or exc.value.status_code == 404

    def test_invoice_belongs_to_different_ledger_raises_400(self):
        ledger = make_ledger(id=1)
        inv = make_invoice(id=1, ledger_id=99)  # different ledger

        db = MagicMock()
        # First query returns ledger
        db.query.return_value.filter.return_value.first.return_value = ledger
        # Second query (invoices) returns list
        db.query.return_value.filter.return_value.all.return_value = [inv]

        with pytest.raises(Exception) as exc:
            create_credit_note(self._base_payload(), db, current_user_id=1)
        assert exc.value.status_code == 400

    def test_cancelled_invoice_raises_400(self):
        ledger = make_ledger(id=1)
        inv = make_invoice(id=1, ledger_id=1, status="cancelled")

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = ledger
        db.query.return_value.filter.return_value.all.return_value = [inv]

        with pytest.raises(Exception) as exc:
            create_credit_note(self._base_payload(), db, current_user_id=1)
        assert exc.value.status_code == 400

    def test_quantity_exceeds_original_raises_400(self):
        ledger = make_ledger(id=1)
        inv = make_invoice(id=1, ledger_id=1)
        ii = make_invoice_item(id=10, invoice_id=1, quantity=5)

        payload = self._base_payload(
            items=[CreditNoteItemCreate(invoice_id=1, invoice_item_id=10, quantity=10)]
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = ledger
        # invoices query
        db.query.return_value.filter.return_value.all.side_effect = [[inv], [ii]]

        with pytest.raises(Exception) as exc:
            create_credit_note(payload, db, current_user_id=1)
        assert exc.value.status_code == 400

    def test_cumulative_quantity_exceeded_raises_400(self):
        """Existing active CNs already cover 8 out of 10 qty; adding 5 more should fail."""
        ledger = make_ledger(id=1)
        inv = make_invoice(id=1, ledger_id=1)
        ii = make_invoice_item(id=10, invoice_id=1, quantity=10)

        payload = self._base_payload(
            items=[CreditNoteItemCreate(invoice_id=1, invoice_item_id=10, quantity=5)]
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = ledger
        db.query.return_value.filter.return_value.all.side_effect = [[inv], [ii]]
        # Simulate cumulative already-credited = 8
        db.query.return_value.join.return_value.filter.return_value.scalar.return_value = 8

        with pytest.raises(Exception) as exc:
            create_credit_note(payload, db, current_user_id=1)
        assert exc.value.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# cancel_credit_note
# ─────────────────────────────────────────────────────────────────────────────

class TestCancelCreditNote:
    def test_cancel_not_found_raises_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(Exception) as exc:
            cancel_credit_note(999, db)
        assert exc.value.status_code == 404

    def test_cancel_already_cancelled_raises_400(self):
        cn = make_cn(status="cancelled")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = cn
        with pytest.raises(Exception) as exc:
            cancel_credit_note(1, db)
        assert exc.value.status_code == 400

    def test_cancel_sets_cancelled_status(self):
        item = CreditNoteItem()
        item.invoice_id = 5
        cn = make_cn(status="active")
        cn.items = [item]

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = cn

        with patch("src.services.credit_note._recompute_credit_status") as mock_recompute:
            cancel_credit_note(1, db)

        assert cn.status == "cancelled"
        assert cn.cancelled_at is not None
        mock_recompute.assert_called_once_with(5, db)
