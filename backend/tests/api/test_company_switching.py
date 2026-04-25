from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.db.session import get_db
from src.models.user import User, UserRole


def _company_payload(name: str, gst: str = ""):
    return {
        "name": name,
        "address": "",
        "gst": gst,
        "phone_number": "",
        "currency_code": "USD",
        "email": "",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def _ledger_payload(name: str, gst: str):
    return {
        "name": name,
        "address": "123 Scope Street",
        "gst": gst,
        "opening_balance": None,
        "phone_number": "+91 9999999999",
        "email": "ledger@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    }


def _ensure_admin_user(db: Session) -> User:
    user = db.query(User).filter(User.email == "test@example.com").first()
    if user:
        user.role = UserRole.admin
        db.commit()
        db.refresh(user)
        return user

    user = User(
        email="test@example.com",
        full_name="Test Admin",
        hashed_password="test-hash",
        role=UserRole.admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _override_persistent_current_user(db: Session = Depends(get_db)) -> User:
    return _ensure_admin_user(db)


def _headers(company_id: int) -> dict[str, str]:
    return {"X-Company-Id": str(company_id)}


def _create_company(client, name: str, gst: str = "") -> int:
    response = client.post("/api/company/companies", json=_company_payload(name, gst))
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _with_persistent_user_override():
    old_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _override_persistent_current_user
    return old_override


def _restore_user_override(old_override):
    if old_override is None:
        app.dependency_overrides.pop(get_current_user, None)
        return
    app.dependency_overrides[get_current_user] = old_override


def test_company_create_list_and_select(client):
    old_override = _with_persistent_user_override()
    try:
        company_a_id = _create_company(client, "Company A")
        company_b_id = _create_company(client, "Company B")

        listed = client.get("/api/company/companies")
        assert listed.status_code == 200, listed.text
        items = listed.json()
        active_before = [item for item in items if item["is_active"]]
        assert len(active_before) == 1
        assert active_before[0]["id"] == company_a_id

        selected = client.post(f"/api/company/select/{company_b_id}")
        assert selected.status_code == 200, selected.text
        assert selected.json()["active_company_id"] == company_b_id

        listed_after = client.get("/api/company/companies")
        assert listed_after.status_code == 200, listed_after.text
        active_after = [item for item in listed_after.json() if item["is_active"]]
        assert len(active_after) == 1
        assert active_after[0]["id"] == company_b_id
    finally:
        _restore_user_override(old_override)


def test_company_header_scopes_ledger_queries(client):
    old_override = _with_persistent_user_override()
    try:
        company_a_id = _create_company(client, "Company Header A")
        company_b_id = _create_company(client, "Company Header B")

        create_a = client.post(
            "/api/ledgers/",
            json=_ledger_payload("Header Scoped Ledger", "29AAAAA1111A1Z1"),
            headers=_headers(company_a_id),
        )
        assert create_a.status_code == 200, create_a.text

        list_a = client.get("/api/ledgers/", headers=_headers(company_a_id))
        assert list_a.status_code == 200, list_a.text
        assert len(list_a.json()["items"]) == 1

        list_b = client.get("/api/ledgers/", headers=_headers(company_b_id))
        assert list_b.status_code == 200, list_b.text
        assert len(list_b.json()["items"]) == 0

        invalid_header = client.get("/api/ledgers/", headers={"X-Company-Id": "not-a-number"})
        assert invalid_header.status_code == 400
    finally:
        _restore_user_override(old_override)


def test_ledgers_are_scoped_by_company_header(client):
    old_override = _with_persistent_user_override()
    try:
        company_a_id = _create_company(client, "Ledger Scope A")
        company_b_id = _create_company(client, "Ledger Scope B")

        create_a = client.post(
            "/api/ledgers/",
            json=_ledger_payload("Ledger A", "27ABCDE1234F1Z5"),
            headers=_headers(company_a_id),
        )
        assert create_a.status_code == 200, create_a.text

        list_a = client.get("/api/ledgers/", headers=_headers(company_a_id))
        assert list_a.status_code == 200, list_a.text
        assert len(list_a.json()["items"]) == 1

        list_b = client.get("/api/ledgers/", headers=_headers(company_b_id))
        assert list_b.status_code == 200, list_b.text
        assert len(list_b.json()["items"]) == 0
    finally:
        _restore_user_override(old_override)


def test_ledger_same_gst_allowed_across_companies_and_blocked_within_company(client):
    old_override = _with_persistent_user_override()
    try:
        company_a_id = _create_company(client, "GST Scope A")
        company_b_id = _create_company(client, "GST Scope B")

        create_a = client.post(
            "/api/ledgers/",
            json=_ledger_payload("Ledger GST A", "27ABCDE1234F1Z5"),
            headers=_headers(company_a_id),
        )
        assert create_a.status_code == 200, create_a.text

        create_b = client.post(
            "/api/ledgers/",
            json=_ledger_payload("Ledger GST B", "27ABCDE1234F1Z5"),
            headers=_headers(company_b_id),
        )
        assert create_b.status_code == 200, create_b.text

        duplicate_same_company = client.post(
            "/api/ledgers/",
            json=_ledger_payload("Ledger GST Duplicate", "27ABCDE1234F1Z5"),
            headers=_headers(company_b_id),
        )
        assert duplicate_same_company.status_code == 400
    finally:
        _restore_user_override(old_override)


