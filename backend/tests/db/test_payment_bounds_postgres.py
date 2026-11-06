"""Real PostgreSQL coverage for payment amount limits.

SQLite ignores NUMERIC precision and scale, so the rounding overflow reported in
#758 only happens against the real columns. These tests hit the API with Postgres
behind it and assert that oversized amounts are refused with 422 before any row is
written, while the largest values that fit still save.

Skipped when DATABASE_URL is not Postgres.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app_main import app
from src.core.config import settings
# Fixtures, imported by name so pytest finds them here too.
from test_quotation_convert_postgres import (  # noqa: F401
    _seed_company,
    app_db,
    deployment,
    signed_in,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import test_tenant_isolation as iso  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="column limits need Postgres",
)


@pytest.fixture
def tenant(app_db, signed_in):  # noqa: F811
    client = TestClient(app)
    seeded = _seed_company(
        client, signed_in, app_db, "payments@alpha.example", "Payment Traders", "PAY-1"
    )
    seeded["client"] = client
    return seeded


def _payments_count(db) -> int:
    with db.owner_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM payments")).scalar_one()


def _stored_amounts(db) -> list[str]:
    with db.owner_engine.connect() as conn:
        return [
            row[0]
            for row in conn.execute(text("SELECT amount::text FROM payments ORDER BY id"))
        ]


def _receipt(tenant: dict, amount: float, **extra) -> dict:
    return {
        "ledger_id": tenant["ledger"],
        "voucher_type": "receipt",
        "amount": amount,
        "mode": "cash",
        **extra,
    }


ROUNDS_PAST_THE_COLUMN = [
    pytest.param(99_999_999.995, id="rounds_up_at_half_cent"),
    pytest.param(99_999_999.996, id="issue_reproduction"),
]


@pytest.mark.parametrize("amount", ROUNDS_PAST_THE_COLUMN)
def test_create_payment_refuses_amount_that_rounds_past_the_column(tenant, app_db, amount):
    response = tenant["client"].post("/api/payments/", json=_receipt(tenant, amount))
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"][0]["loc"] == ["body", "amount"]
    assert _payments_count(app_db) == 0


@pytest.mark.parametrize("amount", ROUNDS_PAST_THE_COLUMN)
def test_update_payment_refuses_amount_that_rounds_past_the_column(tenant, app_db, amount):
    created = iso._ok(tenant["client"].post("/api/payments/", json=_receipt(tenant, 100)))
    response = tenant["client"].put(
        f"/api/payments/{created['id']}",
        json={"voucher_type": "receipt", "amount": amount, "mode": "cash"},
    )
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"][0]["loc"] == ["body", "amount"]
    assert _stored_amounts(app_db) == ["100.00"]


@pytest.mark.parametrize("amount", [-99_999_999.995, -99_999_999.996])
def test_opening_balance_refuses_negative_amount_that_rounds_past_the_column(
    tenant, app_db, amount
):
    response = tenant["client"].post(
        "/api/payments/",
        json={
            "ledger_id": tenant["ledger"],
            "voucher_type": "opening_balance",
            "amount": amount,
            "mode": "cash",
        },
    )
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"][0]["loc"] == ["body", "amount"]
    assert _payments_count(app_db) == 0


def test_invoice_allocation_refuses_amount_that_rounds_past_the_column(tenant, app_db):
    invoice = iso._create_invoice(tenant["client"], tenant["ledger"], tenant["product"])
    response = tenant["client"].post(
        "/api/payments/",
        json=_receipt(
            tenant,
            50,
            invoice_allocations=[
                {"invoice_id": invoice["id"], "allocated_amount": 99_999_999.996}
            ],
        ),
    )
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"][0]["loc"] == [
        "body",
        "invoice_allocations",
        0,
        "allocated_amount",
    ]
    assert _payments_count(app_db) == 0


def test_largest_storable_amounts_are_saved(tenant, app_db):
    top_receipt = iso._ok(
        tenant["client"].post("/api/payments/", json=_receipt(tenant, 99_999_999.99))
    )
    assert top_receipt["amount"] == 99_999_999.99

    opening = iso._ok(
        tenant["client"].post(
            "/api/payments/",
            json={
                "ledger_id": tenant["ledger"],
                "voucher_type": "opening_balance",
                "amount": -99_999_999.99,
                "mode": "cash",
            },
        )
    )
    assert opening["amount"] == -99_999_999.99
    assert _stored_amounts(app_db) == ["99999999.99", "-99999999.99"]
