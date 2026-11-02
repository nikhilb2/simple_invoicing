"""Tests for GET /api/email-logs/ (issue #483).

Covers pagination, newest-first ordering, the email_type / status / date
filters, company isolation, and unauthenticated access, using the shared
TestClient + db_session fixtures from tests/conftest.py.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app_main import app
from src.api.deps import get_current_user
from src.models.company import CompanyProfile
from src.models.email_log import EmailLog


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


def _seed_log(
    db_session,
    *,
    company_id,
    subject,
    email_type="invoice",
    status="sent",
    sent_at,
):
    log = EmailLog(
        company_id=company_id,
        to_email="customer@example.com",
        cc=None,
        subject=subject,
        email_type=email_type,
        reference_id=None,
        status=status,
        error_message=None,
        sent_by_user_id=None,
        sent_at=sent_at,
    )
    db_session.add(log)
    db_session.commit()
    return log


def _list_logs(client, **params):
    response = client.get("/api/email-logs/", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _subjects(payload):
    return [item["subject"] for item in payload["items"]]


def test_pagination_reports_total_pages_and_last_page_contents(client, db_session):
    _seed_company(db_session, 1, "Company A")
    for day in range(1, 6):
        _seed_log(
            db_session,
            company_id=1,
            subject=f"log-day-{day}",
            sent_at=datetime(2026, 10, day, 9, 0, tzinfo=timezone.utc),
        )

    first = _list_logs(client, page=1, page_size=2)
    assert first["total"] == 5
    assert first["page"] == 1
    assert first["page_size"] == 2
    assert first["total_pages"] == 3
    assert len(first["items"]) == 2

    second = _list_logs(client, page=2, page_size=2)
    assert second["page"] == 2
    assert len(second["items"]) == 2

    last = _list_logs(client, page=3, page_size=2)
    assert last["page"] == 3
    assert len(last["items"]) == 1
    assert _subjects(last) == ["log-day-1"]
    assert _subjects(first) + _subjects(second) + _subjects(last) == [
        "log-day-5",
        "log-day-4",
        "log-day-3",
        "log-day-2",
        "log-day-1",
    ]


def test_logs_are_newest_first(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_log(
        db_session,
        company_id=1,
        subject="oldest",
        sent_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    _seed_log(
        db_session,
        company_id=1,
        subject="newest",
        sent_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc),
    )
    _seed_log(
        db_session,
        company_id=1,
        subject="middle",
        sent_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
    )

    payload = _list_logs(client)
    assert payload["total"] == 3
    assert _subjects(payload) == ["newest", "middle", "oldest"]


def test_email_type_filter_narrows_results(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_log(
        db_session,
        company_id=1,
        subject="invoice-mail",
        email_type="invoice",
        sent_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    _seed_log(
        db_session,
        company_id=1,
        subject="reminder-mail",
        email_type="reminder",
        sent_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
    )
    _seed_log(
        db_session,
        company_id=1,
        subject="second-invoice-mail",
        email_type="invoice",
        sent_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc),
    )

    payload = _list_logs(client, email_type="reminder")
    assert payload["total"] == 1
    assert _subjects(payload) == ["reminder-mail"]


def test_status_filter_narrows_results(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_log(
        db_session,
        company_id=1,
        subject="sent-mail",
        status="sent",
        sent_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    _seed_log(
        db_session,
        company_id=1,
        subject="failed-mail",
        status="failed",
        sent_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
    )

    payload = _list_logs(client, status="failed")
    assert payload["total"] == 1
    assert _subjects(payload) == ["failed-mail"]


def test_date_filters_narrow_results(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_log(
        db_session,
        company_id=1,
        subject="oct-1",
        sent_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    _seed_log(
        db_session,
        company_id=1,
        subject="oct-5",
        sent_at=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
    )
    _seed_log(
        db_session,
        company_id=1,
        subject="oct-10",
        sent_at=datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc),
    )

    from_only = _list_logs(client, from_date="2026-10-05")
    assert _subjects(from_only) == ["oct-10", "oct-5"]

    to_only = _list_logs(client, to_date="2026-10-05")
    assert _subjects(to_only) == ["oct-5", "oct-1"]

    ranged = _list_logs(client, from_date="2026-10-02", to_date="2026-10-06")
    assert ranged["total"] == 1
    assert _subjects(ranged) == ["oct-5"]


def test_logs_from_another_company_are_not_returned(client, db_session):
    _seed_company(db_session, 1, "Company A")
    _seed_company(db_session, 2, "Company B")
    _seed_log(
        db_session,
        company_id=1,
        subject="own-mail",
        sent_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
    )
    _seed_log(
        db_session,
        company_id=2,
        subject="other-company-mail",
        sent_at=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc),
    )

    payload = _list_logs(client)
    assert payload["total"] == 1
    assert _subjects(payload) == ["own-mail"]


def test_unauthenticated_request_gets_401():
    saved_override = app.dependency_overrides.pop(get_current_user, None)
    try:
        response = TestClient(app).get("/api/email-logs/")
        assert response.status_code == 401
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_current_user] = saved_override
