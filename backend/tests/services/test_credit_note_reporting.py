from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.services.credit_note_reporting import get_credit_note_ledger_summary


def _build_row(credit_note_id, invoice_id, voucher_type, amount, invoice_number=None):
    credit_note = SimpleNamespace(
        id=credit_note_id,
        credit_note_number=f"CN-{credit_note_id:03d}",
        credit_note_type="return",
        created_at=datetime(2026, 4, 12, 10, 30),
    )
    item = SimpleNamespace(id=invoice_id * 10, line_total=amount)
    invoice = SimpleNamespace(
        id=invoice_id,
        invoice_number=invoice_number,
        voucher_type=voucher_type,
        ledger_name="Northwind Traders",
    )
    return (credit_note, item, invoice)


def test_credit_note_ledger_summary_routes_sales_credits_to_credit_column_and_purchase_to_debit():
    rows = [
        _build_row(1, 101, "sales", 118.0, "S-101"),
        _build_row(1, 202, "purchase", 59.0, "P-202"),
    ]
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = rows

    summary = get_credit_note_ledger_summary(db, ledger_id=9)

    assert summary.sales_credit_total == 118.0
    assert summary.purchase_credit_total == 59.0
    assert summary.sales_credit_by_invoice == {101: 118.0}
    assert len(summary.entries) == 1
    assert summary.entries[0].credit == 118.0
    assert summary.entries[0].debit == 59.0
    assert summary.entries[0].voucher_type == "Credit Note"


def test_credit_note_ledger_summary_deduplicates_invoice_numbers_in_particulars():
    rows = [
        _build_row(2, 301, "sales", 10.0, "S-301"),
        _build_row(2, 301, "sales", 15.0, "S-301"),
        _build_row(2, 302, "sales", 20.0, "S-302"),
    ]
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = rows

    summary = get_credit_note_ledger_summary(db)

    assert len(summary.entries) == 1
    assert summary.entries[0].particulars == "CN-002 (Return) against S-301, S-302"
    assert summary.sales_credit_total == 45.0
    assert summary.sales_credit_by_invoice == {301: 25.0, 302: 20.0}

def _build_inward_row(credit_note_id, invoice_id, amount, supplier_number="SUP/CN/12"):
    credit_note = SimpleNamespace(
        id=credit_note_id,
        credit_note_number=f"DN-{credit_note_id:03d}",
        credit_note_type="return",
        direction="inward",
        supplier_credit_note_number=supplier_number,
        created_at=datetime(2026, 4, 12, 10, 30),
    )
    item = SimpleNamespace(id=invoice_id * 10, line_total=amount)
    invoice = SimpleNamespace(
        id=invoice_id,
        invoice_number="P-202",
        voucher_type="purchase",
        ledger_name="Northwind Traders",
    )
    return (credit_note, item, invoice)


def _summary_for(rows, ledger_id=9):
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = rows
    return get_credit_note_ledger_summary(db, ledger_id=ledger_id)


def test_supplier_note_is_labelled_a_debit_note_and_names_their_number():
    """Tally's name for the recipient side, plus the number that matches GSTR-2B."""
    summary = _summary_for([_build_inward_row(7, 202, 59.0)])

    entry = summary.entries[0]
    assert entry.voucher_type == "Debit Note"
    assert "Supplier CN SUP/CN/12" in entry.particulars
    # It still debits the supplier — the payable falls.
    assert entry.debit == 59.0
    assert entry.credit == 0.0
    assert summary.purchase_credit_total == 59.0


def test_rows_without_a_direction_are_still_credit_notes():
    """Notes written before the column existed were all outward."""
    summary = _summary_for([_build_row(1, 101, "sales", 118.0, "S-101")])
    assert summary.entries[0].voucher_type == "Credit Note"
    assert "Supplier CN" not in summary.entries[0].particulars
