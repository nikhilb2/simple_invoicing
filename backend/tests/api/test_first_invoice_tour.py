"""PUT /auth/me/first-invoice-tour: what the walkthrough remembers, per user."""

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import API_KEY_COMPANY_ATTR, get_current_user
from src.core.config import settings
from src.db.session import get_db
from src.models.user import User, UserRole


@pytest.fixture
def user(client, db_session):
    account = User(email="tour@example.com", full_name="Tour", role=UserRole.admin, hashed_password="x")
    db_session.add(account)
    db_session.commit()
    account_id = account.id

    # Through the request's own session, as the real dependency does.
    def signed_in(db: Session = Depends(get_db)) -> User:
        return db.get(User, account_id)

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = signed_in
    yield account
    app.dependency_overrides[get_current_user] = previous


def _answer(client, status):
    return client.put("/api/auth/me/first-invoice-tour", json={"status": status})


def _stored(client):
    return client.get("/api/auth/me").json()["first_invoice_tour_status"]


def test_an_unanswered_user_reports_null(client, user):
    assert _stored(client) is None


@pytest.mark.parametrize("status", ["completed", "skipped", "not_needed"])
def test_an_answer_is_saved(client, db_session, user, status):
    response = _answer(client, status)

    assert response.status_code == 200, response.text
    assert response.json()["first_invoice_tour_status"] == status
    assert _stored(client) == status
    db_session.refresh(user)
    assert user.first_invoice_tour_status == status
    assert user.first_invoice_tour_finished_at is not None


def test_finishing_after_skipping_counts_as_completed(client, user):
    _answer(client, "skipped")

    assert _answer(client, "completed").json()["first_invoice_tour_status"] == "completed"


@pytest.mark.parametrize("later", ["skipped", "not_needed"])
def test_a_completed_tour_stays_completed(client, user, later):
    _answer(client, "completed")

    assert _answer(client, later).json()["first_invoice_tour_status"] == "completed"
    assert _stored(client) == "completed"


def test_skipping_is_not_overwritten_by_not_needed(client, user):
    _answer(client, "skipped")

    assert _answer(client, "not_needed").json()["first_invoice_tour_status"] == "skipped"


def test_an_unknown_status_is_refused(client, user):
    assert _answer(client, "whatever").status_code == 422
    assert _stored(client) is None


def test_only_finished_answers_are_counted_as_events(client, user, monkeypatch):
    events = []
    monkeypatch.setattr(
        "src.api.routes.auth.track",
        lambda event, distinct_id, properties=None: events.append((event, properties)),
    )

    _answer(client, "not_needed")
    assert events == []

    _answer(client, "completed")
    assert events == [("first_invoice_tour_finished", {"status": "completed"})]

    _answer(client, "completed")
    assert len(events) == 1


def test_an_api_key_cannot_answer_for_the_user(client, user, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    keyed = User(id=999, email="key@example.com", full_name="Key", role=UserRole.admin)
    setattr(keyed, API_KEY_COMPANY_ATTR, 1)
    app.dependency_overrides[get_current_user] = lambda: keyed

    assert _answer(client, "skipped").status_code == 403
