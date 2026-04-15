from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from src.api.routes.payments import create_payment, update_payment
from src.models.buyer import Buyer as Ledger
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