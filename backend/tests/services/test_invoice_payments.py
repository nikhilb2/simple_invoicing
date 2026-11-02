"""Regression tests for invoice payment allocation and validation."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.models.buyer import Buyer
from src.models.invoice import Invoice
from src.models.user import User, UserRole
from src.schemas.payment import PaymentInvoiceAllocationCreate
from src.services.invoice_payments import (
    auto_allocate_outstanding_invoices,
    is_offset_by_payables,
    validate_payment_allocations,
)


@pytest.fixture
def ledger(db_session):
    user = User(
        email="payments-test@example.com",
        full_name="Payment Tester",
        hashed_password="x",
        role=UserRole.admin,
    )
    buyer = Buyer(name="Payment Customer", address="Test address", phone_number="9999999999")
    db_session.add_all([user, buyer])
    db_session.flush()
    return buyer


def _invoice(db_session, ledger, amount=100, *, voucher_type="sales", status="active"):
    invoice = Invoice(
        ledger_id=ledger.id,
        created_by=1,
        total_amount=Decimal(str(amount)),
        invoice_date=datetime(2026, 1, 1),
        voucher_type=voucher_type,
        status=status,
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


def _allocation(invoice_id, amount):
    return PaymentInvoiceAllocationCreate(invoice_id=invoice_id, allocated_amount=amount)


def _validate(db_session, ledger, allocations, *, payment_amount=100, voucher_type="receipt", **kwargs):
    return validate_payment_allocations(
        db_session,
        ledger_id=ledger.id if ledger is not None else None,
        voucher_type=voucher_type,
        payment_amount=payment_amount,
        invoice_allocations=allocations,
        **kwargs,
    )


@pytest.mark.parametrize(
    "receivable,payable,expected",
    [
        (0, 0, False),
        (100, 0, False),
        (100, 99.99, False),
        (100, 100, True),
        (100, 125, True),
        (0, 15, True),
    ],
)
def test_is_offset_by_payables(receivable, payable, expected):
    assert is_offset_by_payables(receivable, payable) is expected


@pytest.mark.parametrize(
    "outstanding,amount,expected",
    [
        ([100], 40, {1: 40.0}),  # Partially settle the first invoice.
        ([100], 100, {1: 100.0}),  # Settle exactly.
        ([100], 150, {1: 100.0}),  # Never exceed outstanding.
        ([100, 60, 30], 125, {1: 100.0, 2: 25.0}),
        ([0, 50, 40], 60, {2: 50.0, 3: 10.0}),
        ([100], 0, {}),
        ([100], -5, {}),
        ([0, 0], 50, {}),
        ([0.10, 0.20], 0.30, {1: 0.10, 2: 0.20}),
    ],
)
def test_auto_allocate_outstanding_invoices(outstanding, amount, expected):
    # The function takes already-ordered (invoice, summary) rows; no database is needed.
    rows = [
        (SimpleNamespace(id=index), SimpleNamespace(remaining_amount=value))
        for index, value in enumerate(outstanding, start=1)
    ]
    assert auto_allocate_outstanding_invoices(rows, amount) == expected


@pytest.mark.parametrize("amount", [25, 100])
def test_validate_accepts_partial_or_exact_allocation(db_session, ledger, amount):
    invoice = _invoice(db_session, ledger)
    result = _validate(db_session, ledger, [_allocation(invoice.id, amount)])
    assert result == [(invoice, Decimal(str(amount)).quantize(Decimal("0.01")))]


def test_validate_rounds_allocations_to_cents(db_session, ledger):
    invoice = _invoice(db_session, ledger)
    result = _validate(db_session, ledger, [_allocation(invoice.id, 12.345)])
    assert result == [(invoice, Decimal("12.35"))]


def test_validate_allows_unallocated_payment_balance(db_session, ledger):
    invoice = _invoice(db_session, ledger)
    result = _validate(db_session, ledger, [_allocation(invoice.id, 40)], payment_amount=100)
    assert result == [(invoice, Decimal("40.00"))]


def test_validate_accepts_payment_for_purchase_invoice(db_session, ledger):
    invoice = _invoice(db_session, ledger, voucher_type="purchase")
    result = _validate(
        db_session, ledger, [_allocation(invoice.id, 30)],
        voucher_type="payment", payment_amount=30,
    )
    assert result == [(invoice, Decimal("30.00"))]


@pytest.mark.parametrize("amount", [0, -1])
def test_validate_rejects_nonpositive_allocations(db_session, ledger, amount):
    invoice = _invoice(db_session, ledger)
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, ledger, [_allocation(invoice.id, amount)])
    assert exc.value.status_code == 400
    assert exc.value.detail == "Allocated amounts must be greater than zero"


def test_validate_rejects_allocation_over_invoice_balance(db_session, ledger):
    invoice = _invoice(db_session, ledger, amount=50)
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, ledger, [_allocation(invoice.id, 60)], payment_amount=60)
    assert exc.value.status_code == 400
    assert "only has 50.00 remaining" in exc.value.detail


def test_validate_rejects_allocations_over_payment_amount(db_session, ledger):
    first = _invoice(db_session, ledger)
    second = _invoice(db_session, ledger)
    with pytest.raises(HTTPException) as exc:
        _validate(
            db_session, ledger,
            [_allocation(first.id, 50), _allocation(second.id, 50)],
            payment_amount=90,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "Allocated total cannot exceed the receipt/payment amount"


def test_validate_rejects_duplicate_invoice_ids(db_session, ledger):
    invoice = _invoice(db_session, ledger)
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, ledger, [_allocation(invoice.id, 10), _allocation(invoice.id, 20)])
    assert exc.value.status_code == 400
    assert "Each invoice may only appear once" in exc.value.detail


def test_validate_rejects_missing_invoice(db_session, ledger):
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, ledger, [_allocation(999999, 10)])
    assert exc.value.status_code == 404
    assert "999999" in exc.value.detail


def test_validate_rejects_wrong_ledger(db_session, ledger):
    invoice = _invoice(db_session, ledger)
    other_ledger = Buyer(name="Other Buyer", address="Other address", phone_number="8888888888")
    db_session.add(other_ledger)
    db_session.flush()
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, other_ledger, [_allocation(invoice.id, 10)])
    assert exc.value.status_code == 400
    assert "does not belong to ledger" in exc.value.detail


def test_validate_rejects_inactive_invoice(db_session, ledger):
    invoice = _invoice(db_session, ledger, status="cancelled")
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, ledger, [_allocation(invoice.id, 10)])
    assert exc.value.status_code == 400
    assert "is not active" in exc.value.detail


def test_validate_rejects_wrong_invoice_type(db_session, ledger):
    invoice = _invoice(db_session, ledger, voucher_type="purchase")
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, ledger, [_allocation(invoice.id, 10)], voucher_type="receipt")
    assert exc.value.status_code == 400
    assert "cannot be allocated to a receipt" in exc.value.detail


def test_validate_requires_ledger(db_session, ledger):
    invoice = _invoice(db_session, ledger)
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, None, [_allocation(invoice.id, 10)])
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invoice allocations require a ledger"


def test_validate_rejects_unsupported_voucher_type(db_session, ledger):
    invoice = _invoice(db_session, ledger)
    with pytest.raises(HTTPException) as exc:
        _validate(db_session, ledger, [_allocation(invoice.id, 10)], voucher_type="opening_balance")
    assert exc.value.status_code == 400
    assert "Only receipts and payments" in exc.value.detail


def test_validate_empty_allocations_are_a_noop(db_session, ledger):
    assert _validate(db_session, ledger, []) == []
