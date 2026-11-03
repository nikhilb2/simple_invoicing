"""Tests for /api/invoice-series/ routes (issue #484).

Covers list, the financial_year_id filter, update, unknown-id 404,
company isolation, admin-only role checks, and unauthenticated access,
using the shared TestClient + db_session fixtures from tests/conftest.py.
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


def _seed_series(
    db_session,
    series_id,
    company_id,
    voucher_type="sales",
    financial_year_id=None,
    prefix="INV",
):
    series = InvoiceSeries(
        id=series_id,
        company_id=company_id,
        voucher_type=voucher_type,
        financial_year_id=financial_year_id,
        prefix=prefix,
        suffix="",
        include_year=True,
        year_format="YYYY",
        separator="-",
        next_sequence=1,
        pad_digits=3,
    )
    db_session.add(series)
    db_session.commit()
    return series


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


def _update_payload():
    return {
        "prefix": " inv ",
        "suffix": " -x ",
        "include_year": False,
        "year_format": "FY",
        "separator": "/",
        "pad_digits": 4,
        "next_sequence": 42,
    }


def test_list_returns_only_the_active_company_in_id_order(
    client, db_session
):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")
    _seed_series(db_session, 2, 1, voucher_type="purchase", prefix="PINV")
    _seed_series(db_session, 1, 1, voucher_type="sales", prefix="INV")
    _seed_series(db_session, 3, 2, voucher_type="sales", prefix="INV")

    response = client.get("/api/invoice-series/")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["id"] for item in payload] == [1, 2]
    assert [item["prefix"] for item in payload] == ["INV", "PINV"]


def test_list_financial_year_filter_narrows_results(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_series(db_session, 1, 1, voucher_type="sales", financial_year_id=10)
    _seed_series(
        db_session, 2, 1, voucher_type="purchase", financial_year_id=20
    )

    response = client.get("/api/invoice-series/", params={"financial_year_id": 20})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [2]


def test_update_applies_fields_with_prefix_suffix_normalization(
    client, db_session
):
    _seed_company(db_session, 1, "Company A")
    _seed_series(db_session, 1, 1)

    response = client.put("/api/invoice-series/1", json=_update_payload())
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["prefix"] == "INV"
    assert updated["suffix"] == "-X"
    assert updated["include_year"] is False
    assert updated["year_format"] == "FY"
    assert updated["separator"] == "/"
    assert updated["pad_digits"] == 4
    assert updated["next_sequence"] == 42


def test_update_unknown_id_returns_404(client, db_session):
    _seed_company(db_session, 1, "Company A")

    response = client.put("/api/invoice-series/999", json=_update_payload())
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Invoice series 999 not found"


def test_update_other_company_series_returns_404(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")
    _seed_series(db_session, 5, 2)

    response = client.put("/api/invoice-series/5", json=_update_payload())
    assert response.status_code == 404, response.text


def test_non_admin_user_gets_403_on_list_and_update(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_series(db_session, 1, 1)

    with as_role(UserRole.staff):
        listed = client.get("/api/invoice-series/")
        assert listed.status_code == 403, listed.text
        assert listed.json()["detail"] == "Insufficient permissions"
        updated = client.put("/api/invoice-series/1", json=_update_payload())
        assert updated.status_code == 403, updated.text


def test_unauthenticated_request_gets_401(db_session):
    _seed_company(db_session, 1, "Company A")
    saved_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = TestClient(app).get("/api/invoice-series/")
        assert response.status_code == 401
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_current_user] = saved_override


@pytest.mark.parametrize(
    ("voucher_type", "overrides"),
    [
        ("sales", {"prefix": "VERY-LONG-PREFIX", "include_year": True}),
        ("sales", {"separator": "_"}),
        ("credit_note", {"prefix": "CREDIT.NOTE"}),
    ],
)
def test_update_refuses_a_format_gstr1_rejects(client, db_session, voucher_type, overrides):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    prefix_before = _seed_series(db_session, 1, 1, voucher_type=voucher_type).prefix

    response = client.put("/api/invoice-series/1", json={**_update_payload(), **overrides})

    assert response.status_code == 400
    assert "GSTR-1" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.get(InvoiceSeries, 1).prefix == prefix_before


def test_update_leaves_series_outside_gstr1_alone(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    _seed_series(db_session, 1, 1, voucher_type="payment")

    response = client.put("/api/invoice-series/1", json={**_update_payload(), "prefix": "VERY-LONG-PAYMENT-PREFIX"})

    assert response.status_code == 200


def test_update_guard_needs_a_company_with_a_gstin(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_series(db_session, 1, 1)

    response = client.put("/api/invoice-series/1", json={**_update_payload(), "prefix": "ACME-WHOLESALE-TRADING"})

    assert response.status_code == 200


def test_update_can_move_the_counter_of_a_series_already_off_the_rule(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    series = _seed_series(db_session, 1, 1)
    series.prefix, series.suffix, series.include_year, series.year_format, series.separator, series.pad_digits = (
        "VERY-LONG-PREFIX", "", False, "FY", "/", 4,
    )
    db_session.commit()

    response = client.put(
        "/api/invoice-series/1",
        json={**_update_payload(), "prefix": "VERY-LONG-PREFIX", "suffix": "", "next_sequence": 60},
    )

    assert response.status_code == 200
    assert response.json()["next_sequence"] == 60


def test_update_leaves_room_for_the_counter_to_grow(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    _seed_series(db_session, 1, 1)

    response = client.put(
        "/api/invoice-series/1",
        json={
            "prefix": "ABCDEFG", "suffix": "", "include_year": True, "year_format": "YYYY",
            "separator": "-", "pad_digits": 3, "next_sequence": 999,
        },
    )

    assert response.status_code == 400


def _year(db_session, year_id, label, *, active=False):
    db_session.add(FinancialYear(
        id=year_id, company_id=1, label=label, start_date=date(2000 + year_id, 4, 1),
        end_date=date(2001 + year_id, 3, 31), is_active=active,
    ))
    db_session.commit()


def _fy_format(db_session, series_id, prefix):
    series = db_session.get(InvoiceSeries, series_id)
    series.prefix, series.year_format = prefix, "FY"
    db_session.commit()


def test_warning_on_a_past_year_judges_the_format_its_numbers_take(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    _year(db_session, 25, "2025-26", active=True)
    _year(db_session, 24, "A LONGER 2024-25")
    _seed_series(db_session, 1, 1, financial_year_id=25)
    _seed_series(db_session, 2, 1, financial_year_id=24, prefix="OLD")
    _fy_format(db_session, 1, "INVOICE")
    # The past year's own row is short, but its documents borrow the active format.
    db_session.get(InvoiceSeries, 2).include_year = False
    db_session.commit()

    rows = {row["id"]: row for row in client.get("/api/invoice-series/").json()}

    assert "GSTR-1" in (rows[2]["gstr1_warning"] or "")


def test_active_format_is_refused_when_a_past_years_label_breaks_it(client, db_session):
    _seed_company(db_session, 1, "Company A").gst = "29AAAAA0000A1Z5"
    _year(db_session, 25, "2025-26", active=True)
    _year(db_session, 24, "OLD YEAR 2024-25")
    _seed_series(db_session, 1, 1, financial_year_id=25)
    _seed_series(db_session, 2, 1, financial_year_id=24)

    response = client.put(
        "/api/invoice-series/1",
        json={"prefix": "INV", "suffix": "", "include_year": True, "year_format": "FY", "separator": "-", "pad_digits": 3},
    )

    assert response.status_code == 400
    assert "OLD YEAR 2024-25" in response.json()["detail"]
