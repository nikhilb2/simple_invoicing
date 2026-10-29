"""Tests for /api/financial-years/ routes (issue #484).

Covers create (201), duplicate label (409), list, activate/deactivate,
unknown-id 404, company isolation, role behavior, and unauthenticated
access, using the shared TestClient + db_session fixtures from
tests/conftest.py.

Roles (issue #493): creating and activating a financial year is admin-only,
like the invoice-series routes, while any logged-in user can list them.
"""

from contextlib import contextmanager
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app_main import app
from src.api.deps import get_current_user
from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries
from src.models.user import User, UserRole


def _seed_company(db_session, company_id, name):
    company = CompanyProfile(
        id=company_id,
        name=name,
        address="",
        gst="",
        phone_number="",
        currency_code="USD",
        email="",
        website="",
        bank_name="",
        branch_name="",
        account_name="",
        account_number="",
        ifsc_code="",
    )
    db_session.add(company)
    db_session.commit()
    return company


def _seed_fy(db_session, fy_id, company_id, label, start, end, is_active=False):
    fy = FinancialYear(
        id=fy_id,
        company_id=company_id,
        label=label,
        start_date=start,
        end_date=end,
        is_active=is_active,
    )
    db_session.add(fy)
    db_session.commit()
    return fy


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


def _create_payload(label="FY 2026-27"):
    return {
        "label": label,
        "start_date": "2026-04-01",
        "end_date": "2027-03-31",
    }


def test_create_returns_201_and_seeds_series_for_the_new_year(
    client, db_session
):
    _seed_company(db_session, 1, "Company A")

    response = client.post("/api/financial-years/", json=_create_payload())
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["label"] == "FY 2026-27"
    assert created["start_date"] == "2026-04-01"
    assert created["end_date"] == "2027-03-31"
    assert created["is_active"] is False

    seeded = (
        db_session.query(InvoiceSeries)
        .filter(InvoiceSeries.financial_year_id == created["id"])
        .all()
    )
    assert {row.voucher_type for row in seeded} == {
        "sales",
        "purchase",
        "payment",
        "credit_note",
        "debit_note",
    }
    assert all(row.next_sequence == 1 for row in seeded)
    assert all(row.company_id == 1 for row in seeded)


def test_duplicate_label_in_the_same_company_returns_409(client, db_session):
    _seed_company(db_session, 1, "Company A")

    first = client.post("/api/financial-years/", json=_create_payload())
    assert first.status_code == 201, first.text

    second = client.post("/api/financial-years/", json=_create_payload())
    assert second.status_code == 409, second.text
    assert "already exists" in second.json()["detail"]


def test_same_label_in_another_company_succeeds(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")

    first = client.post("/api/financial-years/", json=_create_payload())
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/financial-years/",
        json=_create_payload(),
        headers={"X-Company-Id": "2"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first.json()["id"]


def test_list_returns_only_the_active_company_in_start_date_order(
    client, db_session
):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")
    _seed_fy(
        db_session, 1, 1, "FY 2026-27", date(2026, 4, 1), date(2027, 3, 31)
    )
    _seed_fy(
        db_session, 2, 1, "FY 2025-26", date(2025, 4, 1), date(2026, 3, 31)
    )
    _seed_fy(
        db_session, 3, 2, "FY 2026-27", date(2026, 4, 1), date(2027, 3, 31)
    )

    response = client.get("/api/financial-years/")
    assert response.status_code == 200, response.text
    assert [item["label"] for item in response.json()] == [
        "FY 2025-26",
        "FY 2026-27",
    ]


def test_activate_flips_exactly_one_year_active(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_fy(
        db_session,
        1,
        1,
        "FY 2025-26",
        date(2025, 4, 1),
        date(2026, 3, 31),
        is_active=True,
    )
    _seed_fy(
        db_session, 2, 1, "FY 2026-27", date(2026, 4, 1), date(2027, 3, 31)
    )

    response = client.put("/api/financial-years/2/activate")
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True

    states = {
        fy.id: fy.is_active
        for fy in db_session.query(FinancialYear).order_by(FinancialYear.id).all()
    }
    assert states == {1: False, 2: True}


def test_activate_unknown_id_returns_404(client, db_session):
    _seed_company(db_session, 1, "Company A")

    response = client.put("/api/financial-years/999/activate")
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Financial year 999 not found"


def test_activate_other_company_year_returns_404(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")
    _seed_fy(
        db_session, 3, 2, "FY 2026-27", date(2026, 4, 1), date(2027, 3, 31)
    )

    response = client.put("/api/financial-years/3/activate")
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("role", [UserRole.manager, UserRole.staff])
def test_non_admin_cannot_create_a_financial_year(client, db_session, role):
    _seed_company(db_session, 1, "Company A")

    with as_role(role):
        response = client.post("/api/financial-years/", json=_create_payload())

    assert response.status_code == 403, response.text
    assert db_session.query(FinancialYear).count() == 0
    assert db_session.query(InvoiceSeries).count() == 0


@pytest.mark.parametrize("role", [UserRole.manager, UserRole.staff])
def test_non_admin_cannot_activate_a_financial_year(client, db_session, role):
    _seed_company(db_session, 1, "Company A")
    _seed_fy(
        db_session,
        1,
        1,
        "FY 2025-26",
        date(2025, 4, 1),
        date(2026, 3, 31),
        is_active=True,
    )
    _seed_fy(
        db_session, 2, 1, "FY 2026-27", date(2026, 4, 1), date(2027, 3, 31)
    )

    with as_role(role):
        response = client.put("/api/financial-years/2/activate")

    assert response.status_code == 403, response.text
    db_session.expire_all()
    states = {
        fy.id: fy.is_active
        for fy in db_session.query(FinancialYear).order_by(FinancialYear.id).all()
    }
    assert states == {1: True, 2: False}


@pytest.mark.parametrize("role", [UserRole.manager, UserRole.staff])
def test_non_admin_can_still_list_financial_years(client, db_session, role):
    _seed_company(db_session, 1, "Company A")
    _seed_fy(
        db_session, 1, 1, "FY 2025-26", date(2025, 4, 1), date(2026, 3, 31)
    )

    with as_role(role):
        response = client.get("/api/financial-years/")

    assert response.status_code == 200, response.text
    assert [item["label"] for item in response.json()] == ["FY 2025-26"]


def test_admin_can_create_and_activate(client, db_session):
    _seed_company(db_session, 1, "Company A")

    with as_role(UserRole.admin):
        created = client.post("/api/financial-years/", json=_create_payload())
        assert created.status_code == 201, created.text
        activated = client.put(
            f"/api/financial-years/{created.json()['id']}/activate"
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["is_active"] is True


def test_unauthenticated_request_gets_401(db_session):
    _seed_company(db_session, 1, "Company A")
    saved_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = TestClient(app).get("/api/financial-years/")
        assert response.status_code == 401
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_current_user] = saved_override
