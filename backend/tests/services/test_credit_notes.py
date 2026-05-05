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
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, call, patch

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
    cn.credit_note_number = f"CN-{id:03d}"
    cn.status = status
    cn.ledger_id = ledger_id
    cn.financial_year_id = 1
    cn.credit_note_type = "return"
    cn.reason = "test"
    cn.taxable_amount = 100
    cn.cgst_amount = 9
    cn.sgst_amount = 9
    cn.igst_amount = 0
    cn.total_amount = 118
    cn.created_at = datetime.utcnow()
    cn.cancelled_at = None
    cn.items = []
    cn.invoice_refs = []
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

    def test_discount_payload_requires_discount_amount(self):
        with pytest.raises(Exception):
            CreditNoteCreate(
                ledger_id=1,
                invoice_ids=[1],
                credit_note_type="discount",
                items=[CreditNoteItemCreate(invoice_id=1, invoice_item_id=10)],
            )

    def test_discount_payload_rejects_quantity(self):
        with pytest.raises(Exception):
            CreditNoteCreate(
                ledger_id=1,
                invoice_ids=[1],
                credit_note_type="discount",
                items=[
                    CreditNoteItemCreate(
                        invoice_id=1,
                        invoice_item_id=10,
                        quantity=1,
                        discount_amount_inclusive=Decimal("118"),
                    )
                ],
            )


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

    def test_return_credit_note_increases_inventory(self):
        ledger = make_ledger(id=1)
        inv = make_invoice(id=1, ledger_id=1)
        ii = make_invoice_item(id=10, invoice_id=1, product_id=22, quantity=10, unit_price=100, gst_rate=18)

        payload = CreditNoteCreate(
            ledger_id=1,
            invoice_ids=[1],
            credit_note_type="return",
            items=[CreditNoteItemCreate(invoice_id=1, invoice_item_id=10, quantity=2)],
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = ledger
        db.query.return_value.filter.return_value.all.side_effect = [[inv], [ii]]
        db.query.return_value.join.return_value.filter.return_value.scalar.return_value = 0

        with patch("src.services.credit_note.get_active_fy", return_value=SimpleNamespace(id=1)), \
             patch("src.services.credit_note.get_fy_for_date", return_value=None), \
             patch("src.services.credit_note.generate_next_number", return_value="CN-001"), \
             patch("src.services.credit_note._recompute_credit_status"), \
             patch("src.services.credit_note._change_inventory_quantity") as mock_change_inventory:
            create_credit_note(payload, db, current_user_id=1)

        mock_change_inventory.assert_called_once_with(db, 22, 2, context=ANY)

    def test_discount_credit_note_splits_inclusive_tax(self):
        ledger = make_ledger(id=1)
        inv = make_invoice(id=1, ledger_id=1)
        ii = make_invoice_item(id=10, invoice_id=1, product_id=22, quantity=10, unit_price=100, gst_rate=18)

        payload = CreditNoteCreate(
            ledger_id=1,
            invoice_ids=[1],
            credit_note_type="discount",
            items=[
                CreditNoteItemCreate(
                    invoice_id=1,
                    invoice_item_id=10,
                    discount_amount_inclusive=Decimal("118"),
                )
            ],
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = ledger
        db.query.return_value.filter.return_value.all.side_effect = [[inv], [ii]]

        with patch("src.services.credit_note.get_active_fy", return_value=SimpleNamespace(id=1)), \
             patch("src.services.credit_note.get_fy_for_date", return_value=None), \
             patch("src.services.credit_note.generate_next_number", return_value="CN-001"), \
             patch("src.services.credit_note._recompute_credit_status"), \
             patch("src.services.credit_note._change_inventory_quantity") as mock_change_inventory:
            create_credit_note(payload, db, current_user_id=1)

        added_credit_note_item = None
        added_credit_note = None
        for added_call in db.add.call_args_list:
            candidate = added_call.args[0]
            if isinstance(candidate, CreditNote) and added_credit_note is None:
                added_credit_note = candidate
            if isinstance(candidate, CreditNoteItem):
                added_credit_note_item = candidate
                break

        assert added_credit_note_item is not None
        assert added_credit_note is not None
        assert Decimal(str(added_credit_note_item.taxable_amount)) == Decimal("100.00")
        assert Decimal(str(added_credit_note_item.tax_amount)) == Decimal("18.00")
        assert Decimal(str(added_credit_note_item.line_total)) == Decimal("118.00")
        assert added_credit_note_item.quantity == 1
        assert Decimal(str(added_credit_note.cgst_amount)) == Decimal("9.00")
        assert Decimal(str(added_credit_note.sgst_amount)) == Decimal("9.00")
        assert Decimal(str(added_credit_note.total_amount)) == Decimal("118.00")
        assert Decimal(str(added_credit_note.cgst_amount + added_credit_note.sgst_amount)) == Decimal("18.00")
        mock_change_inventory.assert_not_called()

    def test_discount_credit_note_intrastate_keeps_item_split_equal_for_odd_paise_tax(self):
        ledger = make_ledger(id=1)
        inv = make_invoice(id=1, ledger_id=1)
        ii = make_invoice_item(id=10, invoice_id=1, product_id=22, quantity=10, unit_price=100, gst_rate=18)

        payload = CreditNoteCreate(
            ledger_id=1,
            invoice_ids=[1],
            credit_note_type="discount",
            items=[
                CreditNoteItemCreate(
                    invoice_id=1,
                    invoice_item_id=10,
                    discount_amount_inclusive=Decimal("118.05"),
                )
            ],
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = ledger
        db.query.return_value.filter.return_value.all.side_effect = [[inv], [ii]]

        with patch("src.services.credit_note.get_active_fy", return_value=SimpleNamespace(id=1)), \
             patch("src.services.credit_note.get_fy_for_date", return_value=None), \
             patch("src.services.credit_note.generate_next_number", return_value="CN-001"), \
             patch("src.services.credit_note._recompute_credit_status"), \
             patch("src.services.credit_note._change_inventory_quantity") as mock_change_inventory:
            create_credit_note(payload, db, current_user_id=1)

        added_credit_note_item = None
        added_credit_note = None
        for added_call in db.add.call_args_list:
            candidate = added_call.args[0]
            if isinstance(candidate, CreditNote) and added_credit_note is None:
                added_credit_note = candidate
            if isinstance(candidate, CreditNoteItem):
                added_credit_note_item = candidate

        assert added_credit_note_item is not None
        assert added_credit_note is not None
        assert Decimal(str(added_credit_note_item.taxable_amount)) == Decimal("100.04")
        assert Decimal(str(added_credit_note_item.tax_amount)) == Decimal("18.02")
        assert Decimal(str(added_credit_note_item.line_total)) == Decimal("118.06")
        assert Decimal(str(added_credit_note.cgst_amount)) == Decimal("9.01")
        assert Decimal(str(added_credit_note.sgst_amount)) == Decimal("9.01")
        assert Decimal(str(added_credit_note.cgst_amount + added_credit_note.sgst_amount)) == Decimal("18.02")
        assert Decimal(str(added_credit_note.total_amount)) == Decimal("118.06")
        mock_change_inventory.assert_not_called()


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

    def test_cancel_already_cancelled_hard_deletes(self):
        cn = make_cn(status="cancelled")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = cn
        cancel_credit_note(1, db)
        db.delete.assert_called_once_with(cn)

    def test_cancel_marks_response_cancelled_and_deletes(self):
        item = CreditNoteItem()
        item.id = 1
        item.invoice_id = 5
        item.invoice_item_id = 11
        item.product_id = 22
        item.quantity = 1
        item.unit_price = 100
        item.gst_rate = 18
        item.taxable_amount = 100
        item.tax_amount = 18
        item.line_total = 118

        cn = make_cn(status="active")
        cn.items = [item]

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = cn

        with patch("src.services.credit_note._recompute_credit_status") as mock_recompute, \
             patch("src.services.credit_note._change_inventory_quantity"):
            out = cancel_credit_note(1, db)

        assert out.status == "cancelled"
        assert out.cancelled_at is not None
        db.delete.assert_called_once_with(cn)
        mock_recompute.assert_called_once_with(5, db)

    def test_cancel_return_credit_note_reverses_inventory(self):
        item = CreditNoteItem()
        item.id = 1
        item.invoice_id = 5
        item.invoice_item_id = 11
        item.product_id = 22
        item.quantity = 3
        item.unit_price = 100
        item.gst_rate = 18
        item.taxable_amount = 300
        item.tax_amount = 54
        item.line_total = 354

        cn = make_cn(status="active")
        cn.credit_note_type = "return"
        cn.items = [item]
        cn.invoice_refs = []
        cn.credit_note_number = "CN-001"
        cn.financial_year_id = 1
        cn.reason = "test"
        cn.taxable_amount = 100
        cn.cgst_amount = 9
        cn.sgst_amount = 9
        cn.igst_amount = 0
        cn.total_amount = 118
        cn.created_at = datetime.utcnow()

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = cn

        with patch("src.services.credit_note._recompute_credit_status"), \
             patch("src.services.credit_note._change_inventory_quantity") as mock_change_inventory:
            cancel_credit_note(1, db)

        mock_change_inventory.assert_called_once_with(db, 22, -3, context=ANY)
