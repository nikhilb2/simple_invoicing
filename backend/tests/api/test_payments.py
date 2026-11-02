from contextlib import contextmanager
from datetime import date, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app_main import app
from src.api.deps import get_current_user
from src.api.routes.payments import _build_receipt_html, create_payment, update_payment
from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.models.user import User, UserRole
from src.schemas.payment import PaymentCreate, PaymentUpdate


def _build_db(ledger):
    db = MagicMock()
    db.query().filter().first.return_value = ledger
    return db


def test_create_payment_uses_payment_series_and_target_fy_for_backdated_entries():
    ledger = Ledger()
    ledger.id = 7
    payload = PaymentCreate(
        ledger_id=7,
        voucher_type="receipt",
        amount=1250,
        date=datetime(2031, 10, 15, 9, 30),
        mode="bank",
    )
    db = _build_db(ledger)
    active_fy = SimpleNamespace(id=20, start_date=date(2032, 4, 1), end_date=date(2033, 3, 31))
    dated_fy = SimpleNamespace(id=19)
    current_user = SimpleNamespace(id=5)

    with patch("src.api.routes.payments.get_active_fy", return_value=active_fy), patch(
        "src.api.routes.payments.get_fy_for_date", return_value=dated_fy
    ), patch(
        "src.api.routes.payments.generate_next_number", return_value="PAY-2031-001/S"
    ) as generate_mock, patch(
        "src.api.routes.payments.PaymentOut.model_validate",
        return_value=SimpleNamespace(warnings=[]),
    ):
        result = create_payment(payload, db=db, current_user=current_user)

    generate_mock.assert_called_once_with(
        db,
        "payment",
        19,
        date(2031, 10, 15),
        20,
    )
    payment = db.add.call_args.args[0]
    assert payment.financial_year_id == 19
    assert payment.payment_number == "PAY-2031-001/S"
    assert result.warnings == ["invoice_date_outside_fy"]


def test_create_payment_uses_active_fy_when_payment_date_is_within_active_year():
    ledger = Ledger()
    ledger.id = 8
    payload = PaymentCreate(
        ledger_id=8,
        voucher_type="payment",
        amount=500,
        date=datetime(2032, 10, 15, 12, 0),
    )
    db = _build_db(ledger)
    active_fy = SimpleNamespace(id=20, start_date=date(2032, 4, 1), end_date=date(2033, 3, 31))
    current_user = SimpleNamespace(id=6)

    with patch("src.api.routes.payments.get_active_fy", return_value=active_fy), patch(
        "src.api.routes.payments.get_fy_for_date", return_value=active_fy
    ), patch(
        "src.api.routes.payments.generate_next_number", return_value="PAY-2032-001"
    ) as generate_mock, patch(
        "src.api.routes.payments.PaymentOut.model_validate",
        return_value=SimpleNamespace(warnings=[]),
    ):
        result = create_payment(payload, db=db, current_user=current_user)

    generate_mock.assert_called_once_with(
        db,
        "payment",
        20,
        date(2032, 10, 15),
        20,
    )
    assert result.warnings == []


def test_create_payment_rejects_duplicate_opening_balance_for_same_ledger():
    ledger = Ledger()
    ledger.id = 9
    payload = PaymentCreate(
        ledger_id=9,
        voucher_type="opening_balance",
        amount=1000,
        date=datetime(2032, 4, 1, 0, 0),
    )
    db = _build_db(ledger)
    current_user = SimpleNamespace(id=7)

    with patch(
        "src.api.routes.payments._find_existing_opening_balance",
        return_value=SimpleNamespace(id=99),
    ):
        try:
            create_payment(payload, db=db, current_user=current_user)
            assert False, "Expected HTTPException for duplicate opening balance"
        except HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail == "Opening balance already exists for this ledger"


def test_update_payment_rejects_duplicate_opening_balance_for_same_ledger():
    existing_payment = SimpleNamespace(
        id=12,
        ledger_id=11,
        voucher_type="receipt",
        amount=250,
        date=datetime(2032, 4, 2, 10, 0),
        mode=None,
        reference=None,
        notes=None,
    )
    payload = PaymentUpdate(
        voucher_type="opening_balance",
        amount=500,
        date=datetime(2032, 4, 3, 11, 0),
        mode="cash",
        reference="ref",
        notes="note",
    )

    db = MagicMock()
    db.query().filter().first.return_value = existing_payment

    with patch(
        "src.api.routes.payments._find_existing_opening_balance",
        return_value=SimpleNamespace(id=77),
    ):
        try:
            update_payment(12, payload, db=db, _=SimpleNamespace(id=1))
            assert False, "Expected HTTPException for duplicate opening balance"
        except HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail == "Opening balance already exists for this ledger"


def test_create_opening_balance_skips_payment_series_number_generation():
    ledger = Ledger()
    ledger.id = 10
    payload = PaymentCreate(
        ledger_id=10,
        voucher_type="opening_balance",
        amount=100,
        date=datetime(2032, 4, 1, 12, 0),
    )
    db = _build_db(ledger)
    active_fy = SimpleNamespace(id=20, start_date=date(2032, 4, 1), end_date=date(2033, 3, 31))
    current_user = SimpleNamespace(id=8)

    with patch("src.api.routes.payments.get_active_fy", return_value=active_fy), patch(
        "src.api.routes.payments.get_fy_for_date", return_value=active_fy
    ), patch(
        "src.api.routes.payments._find_existing_opening_balance",
        return_value=None,
    ), patch(
        "src.api.routes.payments.generate_next_number"
    ) as generate_mock, patch(
        "src.api.routes.payments.PaymentOut.model_validate",
        return_value=SimpleNamespace(warnings=[]),
    ):
        result = create_payment(payload, db=db, current_user=current_user)

    generate_mock.assert_not_called()
    payment = db.add.call_args.args[0]
    assert payment.payment_number is None
    assert result.warnings == []


def test_create_payment_allows_account_only_entry_without_ledger():
    payload = PaymentCreate(
        ledger_id=None,
        voucher_type="payment",
        amount=300,
        account_id=21,
        date=datetime(2032, 6, 1, 9, 0),
        mode="cash",
        notes="Cash withdrawal",
    )
    db = MagicMock()
    db.query().filter().first.return_value = SimpleNamespace(id=21)
    active_fy = SimpleNamespace(id=20, start_date=date(2032, 4, 1), end_date=date(2033, 3, 31))
    current_user = SimpleNamespace(id=9)

    with patch("src.api.routes.payments.get_active_fy", return_value=active_fy), patch(
        "src.api.routes.payments.get_fy_for_date", return_value=active_fy
    ), patch(
        "src.api.routes.payments.generate_next_number", return_value="PAY-2032-025"
    ) as generate_mock, patch(
        "src.api.routes.payments.PaymentOut.model_validate",
        return_value=SimpleNamespace(warnings=[]),
    ):
        result = create_payment(payload, db=db, current_user=current_user)

    generate_mock.assert_called_once_with(
        db,
        "payment",
        20,
        date(2032, 6, 1),
        20,
    )
    payment = db.add.call_args.args[0]
    assert payment.ledger_id is None
    assert payment.account_id == 21
    assert payment.notes == "Cash withdrawal"
    assert result.warnings == []


def test_receipt_html_includes_invoice_allocations_section_when_present():
    invoice = SimpleNamespace(
        id=41,
        invoice_number="INV-0041",
        invoice_date=datetime(2032, 6, 1, 0, 0),
        due_date=datetime(2032, 6, 15, 0, 0),
    )
    payment = SimpleNamespace(
        id=12,
        voucher_type="receipt",
        payment_number="PAY-0012",
        date=datetime(2032, 6, 10, 11, 30),
        amount=500,
        mode="bank",
        reference="TXN-123",
        notes="Part payment",
        ledger=SimpleNamespace(name="Acme Retail", address="Mumbai", phone_number="9999999999", gst="27ABCDE1234F1Z0"),
        account=SimpleNamespace(display_name="HDFC Current", account_type="bank", bank_name="HDFC"),
        invoice_allocations=[SimpleNamespace(invoice_id=41, allocated_amount=120, invoice=invoice)],
    )
    company = SimpleNamespace(
        name="Respawn Pvt Ltd",
        address="Bengaluru",
        gst="29ABCDE1234F1ZW",
        phone_number="8888888888",
        email="billing@example.com",
        currency_code="INR",
    )

    html = _build_receipt_html(payment, company, {41: "partial"})

    assert "Allocated Invoices" in html
    assert "INV-0041" in html
    assert "Partial" in html
    assert "Total Allocated" in html


def test_receipt_html_hides_invoice_allocations_section_when_absent():
    payment = SimpleNamespace(
        id=14,
        voucher_type="receipt",
        payment_number="PAY-0014",
        date=datetime(2032, 6, 12, 10, 0),
        amount=700,
        mode="cash",
        reference=None,
        notes=None,
        ledger=SimpleNamespace(name="Walk-in", address="", phone_number="", gst=""),
        account=None,
        invoice_allocations=[],
    )
    company = SimpleNamespace(
        name="Respawn Pvt Ltd",
        address="Bengaluru",
        gst="",
        phone_number="",
        email="",
        currency_code="INR",
    )

    html = _build_receipt_html(payment, company, {})

    assert "Allocated Invoices" not in html

def _update_payment_db(existing_payment):
    db = MagicMock()
    db.query.return_value.options.return_value.filter.return_value.first.return_value = existing_payment
    return db


def _allocated_payment(amount=200):
    return SimpleNamespace(
        id=12,
        ledger_id=11,
        voucher_type="receipt",
        amount=amount,
        account_id=None,
        date=datetime(2032, 4, 2, 10, 0),
        mode="upi",
        reference="REF-42",
        notes=None,
        status="active",
        invoice_allocations=[
            SimpleNamespace(invoice_id=21, allocated_amount=60),
            SimpleNamespace(invoice_id=22, allocated_amount=40),
        ],
    )


def _run_update(existing_payment, payload):
    db = _update_payment_db(existing_payment)
    with patch("src.api.routes.payments.sync_payment_allocations") as sync_mock, patch(
        "src.api.routes.payments._to_payment_out", return_value=SimpleNamespace(ok=True)
    ):
        result = update_payment(12, payload, db=db, _=SimpleNamespace(id=1))
    return db, sync_mock, result


def test_update_payment_without_allocations_keeps_existing_allocations():
    existing_payment = _allocated_payment()
    payload = PaymentUpdate(
        voucher_type="receipt",
        amount=200,
        date=datetime(2032, 4, 3, 11, 0),
    )
    assert payload.invoice_allocations is None

    _, sync_mock, _ = _run_update(existing_payment, payload)

    sync_mock.assert_not_called()
    assert existing_payment.invoice_allocations[0].allocated_amount == 60
    assert existing_payment.invoice_allocations[1].allocated_amount == 40
    assert existing_payment.amount == 200


def test_update_payment_without_allocations_keeps_allocations_when_amount_still_covers_them():
    existing_payment = _allocated_payment()
    payload = PaymentUpdate(voucher_type="receipt", amount=150)

    _, sync_mock, _ = _run_update(existing_payment, payload)

    sync_mock.assert_not_called()
    assert existing_payment.amount == 150


def test_update_payment_with_empty_allocations_still_clears_them():
    existing_payment = _allocated_payment()
    payload = PaymentUpdate(voucher_type="receipt", amount=200, invoice_allocations=[])

    _, sync_mock, _ = _run_update(existing_payment, payload)

    sync_mock.assert_called_once()
    assert sync_mock.call_args.kwargs["invoice_allocations"] == []


def test_update_payment_without_allocations_rejects_amount_below_allocated_total():
    existing_payment = _allocated_payment()
    payload = PaymentUpdate(voucher_type="receipt", amount=90)

    db = _update_payment_db(existing_payment)
    with patch("src.api.routes.payments.sync_payment_allocations") as sync_mock:
        try:
            update_payment(12, payload, db=db, _=SimpleNamespace(id=1))
            assert False, "Expected HTTPException for amount below allocated total"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "Allocated total" in exc.detail

    sync_mock.assert_not_called()
    assert existing_payment.amount == 200


def test_update_payment_without_allocations_rejects_voucher_type_change():
    existing_payment = _allocated_payment()
    payload = PaymentUpdate(voucher_type="payment", amount=200)

    db = _update_payment_db(existing_payment)
    with patch("src.api.routes.payments.sync_payment_allocations") as sync_mock:
        try:
            update_payment(12, payload, db=db, _=SimpleNamespace(id=1))
            assert False, "Expected HTTPException for voucher type change with allocations"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "invoice allocations" in exc.detail

    sync_mock.assert_not_called()
    assert existing_payment.voucher_type == "receipt"


@contextmanager
def as_role(role):
    """Swap the conftest admin override for another role."""
    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="test@example.com", role=role
    )
    try:
        yield
    finally:
        app.dependency_overrides[get_current_user] = previous


@pytest.fixture
def payment_with_allocation(db_session):
    company = CompanyProfile(id=1, name="Test Company", address="", currency_code="USD")
    db_session.add(company)
    db_session.flush()
    user = User(
        id=1,
        email="test@example.com",
        full_name="Test User",
        hashed_password="unused",
        role=UserRole.admin,
    )
    ledger = Ledger(
        id=1, company_id=company.id, name="Test Ledger", address="", phone_number=""
    )
    db_session.add_all([user, ledger])
    db_session.flush()
    invoice = Invoice(
        id=1,
        company_id=company.id,
        ledger_id=ledger.id,
        invoice_number="INV-001",
        voucher_type="sales",
        total_amount=500,
        created_by=user.id,
    )
    payment = Payment(
        id=1,
        company_id=company.id,
        ledger_id=ledger.id,
        voucher_type="receipt",
        amount=200,
        date=datetime(2032, 4, 2, 10, 0),
        mode="upi",
        reference="REF-42",
        notes="Original notes",
        created_by=user.id,
        status="active",
        invoice_allocations=[
            PaymentInvoiceAllocation(invoice=invoice, allocated_amount=60)
        ],
    )
    db_session.add(payment)
    db_session.commit()
    return payment


@pytest.mark.parametrize("method", ["put", "delete"])
def test_staff_cannot_change_payment(client, db_session, payment_with_allocation, method):
    payment_id = payment_with_allocation.id
    before_payment = db_session.query(Payment.__table__).filter(Payment.id == payment_id).one()
    before_allocations = (
        db_session.query(PaymentInvoiceAllocation.__table__)
        .filter(PaymentInvoiceAllocation.payment_id == payment_id)
        .order_by(PaymentInvoiceAllocation.id)
        .all()
    )
    payload = {
        "voucher_type": "receipt",
        "amount": 300,
        "date": "2032-04-03T11:00:00",
        "mode": "bank",
        "reference": "CHANGED",
        "notes": "Changed notes",
        "invoice_allocations": [],
    }

    with as_role(UserRole.staff):
        if method == "put":
            response = client.put(f"/api/payments/{payment_id}", json=payload)
        else:
            response = client.delete(f"/api/payments/{payment_id}")

    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Insufficient permissions"}
    db_session.expire_all()
    assert db_session.query(Payment.__table__).filter(Payment.id == payment_id).one() == before_payment
    allocations = (
        db_session.query(PaymentInvoiceAllocation.__table__)
        .filter(PaymentInvoiceAllocation.payment_id == payment_id)
        .order_by(PaymentInvoiceAllocation.id)
        .all()
    )
    assert allocations == before_allocations


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.manager])
@pytest.mark.parametrize("clear_allocations", [False, True])
def test_admin_and_manager_can_update_payment(
    client, db_session, payment_with_allocation, role, clear_allocations
):
    payment_id = payment_with_allocation.id
    allocation_id = payment_with_allocation.invoice_allocations[0].id
    payload = {"voucher_type": "receipt", "amount": 300, "notes": "Updated notes"}
    if clear_allocations:
        payload["invoice_allocations"] = []

    with as_role(role):
        response = client.put(f"/api/payments/{payment_id}", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["amount"] == 300
    db_session.expire_all()
    payment = db_session.get(Payment, payment_id)
    assert payment.amount == 300
    assert payment.notes == "Updated notes"
    assert payment.status == "active"
    allocations = (
        db_session.query(PaymentInvoiceAllocation)
        .filter(PaymentInvoiceAllocation.payment_id == payment_id)
        .all()
    )
    if clear_allocations:
        assert allocations == []
        assert response.json()["invoice_allocations"] == []
    else:
        assert [(row.id, row.invoice_id, row.allocated_amount) for row in allocations] == [
            (allocation_id, 1, 60)
        ]
        assert response.json()["invoice_allocations"][0]["allocated_amount"] == 60


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.manager])
def test_admin_and_manager_can_cancel_payment(client, db_session, payment_with_allocation, role):
    payment_id = payment_with_allocation.id
    allocation_id = payment_with_allocation.invoice_allocations[0].id

    with as_role(role):
        response = client.delete(f"/api/payments/{payment_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {"message": "Payment cancelled"}
    db_session.expire_all()
    payment = db_session.get(Payment, payment_id)
    assert payment is not None
    assert payment.status == "cancelled"
    assert payment.amount == 200
    assert [row.id for row in payment.invoice_allocations] == [allocation_id]


@pytest.mark.parametrize("role", [UserRole.staff, UserRole.manager, UserRole.admin])
@pytest.mark.parametrize("suffix", ["", "/", "/{payment_id}", "/{payment_id}/pdf"])
def test_all_roles_can_read_payments(client, payment_with_allocation, role, suffix):
    payment_id = payment_with_allocation.id
    path = "/api/payments" + suffix.format(payment_id=payment_id)
    with as_role(role), patch(
        "src.api.routes.payments.render_receipt_pdf", return_value=BytesIO(b"%PDF-test")
    ):
        response = client.get(path)

    assert response.status_code == 200, response.text
    if suffix.endswith("/pdf"):
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == b"%PDF-test"
    elif suffix in ("", "/"):
        assert [row["id"] for row in response.json()] == [payment_id]
    else:
        assert response.json()["id"] == payment_id
