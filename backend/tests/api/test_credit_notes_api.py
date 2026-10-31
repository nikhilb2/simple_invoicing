"""The credit note registry, once it holds both directions.

A supplier's note is found by their number, not the one we assigned it — that
is what the user has in front of them when reconciling against GSTR-2B.
"""
from contextlib import contextmanager
from datetime import date, datetime

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user, get_db
from src.models.buyer import Buyer
from src.models.credit_note import CreditNote
from src.models.user import User, UserRole


@pytest.fixture
def seeded(db_session):
    user = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="secret",
        role=UserRole.admin,
    )
    ledger = Buyer(
        name="Northwind Traders",
        address="1 Dock Road",
        gst="29ABCDE1234F1ZW",
        phone_number="9999999999",
    )
    db_session.add_all([user, ledger])
    db_session.commit()

    outward = CreditNote(
        credit_note_number="CN-2026-001",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction="outward",
        status="active",
        taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0,
        total_amount=118,
        created_at=datetime(2026, 6, 1),
    )
    inward = CreditNote(
        credit_note_number="DN-2026-001",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction="inward",
        supplier_credit_note_number="SUP/CN/12",
        supplier_credit_note_date=date(2026, 6, 2),
        status="active",
        taxable_amount=50, cgst_amount=4.5, sgst_amount=4.5, igst_amount=0,
        total_amount=59,
        created_at=datetime(2026, 6, 2),
    )
    # A row from before the column existed.
    legacy = CreditNote(
        credit_note_number="CN-2025-099",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction=None,
        status="active",
        taxable_amount=10, cgst_amount=0, sgst_amount=0, igst_amount=0,
        total_amount=10,
        created_at=datetime(2026, 6, 3),
    )
    db_session.add_all([outward, inward, legacy])
    db_session.commit()
    return user, ledger


def _list(client, **params):
    response = client.get("/api/credit-notes/", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _numbers(payload):
    return sorted(item["credit_note_number"] for item in payload["items"])


def test_direction_filter_separates_the_two_registries(client, seeded):
    inward = _list(client, direction="inward")
    assert _numbers(inward) == ["DN-2026-001"]

    outward = _list(client, direction="outward")
    # The legacy NULL row counts as outward — nothing before the column was inward.
    assert _numbers(outward) == ["CN-2025-099", "CN-2026-001"]


def test_unfiltered_listing_returns_both(client, seeded):
    result = _list(client)
    assert _numbers(result) == ["CN-2025-099", "CN-2026-001", "DN-2026-001"]


def test_date_to_includes_the_whole_selected_day(client, db_session, seeded):
    """date_to=2026-06-02 must cover notes created any time that day, not just
    at midnight — created_at is a timestamp and the To day used to be cut off.
    A note stamped 15:30 on the To day is the regression: with the old
    `<= midnight` cut-off it disappears from the listing."""
    user, ledger = seeded
    afternoon = CreditNote(
        credit_note_number="CN-2026-002",
        ledger_id=ledger.id,
        created_by=user.id,
        credit_note_type="return",
        direction="outward",
        status="active",
        taxable_amount=20, cgst_amount=1.8, sgst_amount=1.8, igst_amount=0,
        total_amount=23.6,
        created_at=datetime(2026, 6, 2, 15, 30),
    )
    db_session.add(afternoon)
    db_session.commit()

    result = _list(client, date_from="2026-06-02", date_to="2026-06-02")
    assert _numbers(result) == ["CN-2026-002", "DN-2026-001"]


def test_date_range_covers_each_side_of_the_boundary(client, seeded):
    result = _list(client, date_from="2026-06-02", date_to="2026-06-03")
    assert _numbers(result) == ["CN-2025-099", "DN-2026-001"]


def test_malformed_date_value_returns_422(client, seeded):
    response = client.get("/api/credit-notes/", params={"date_to": "garbage"})
    assert response.status_code == 422


def test_date_from_after_date_to_returns_400(client, seeded):
    response = client.get(
        "/api/credit-notes/",
        params={"date_from": "2026-06-03", "date_to": "2026-06-02"},
    )
    assert response.status_code == 400
    assert "date_from must be before or equal to date_to" in response.text


def test_search_matches_the_suppliers_own_number(client, seeded):
    result = _list(client, search="SUP/CN")
    assert _numbers(result) == ["DN-2026-001"]
    assert result["items"][0]["supplier_credit_note_number"] == "SUP/CN/12"
    assert result["items"][0]["supplier_credit_note_date"] == "2026-06-02"


def test_search_still_matches_our_own_number(client, seeded):
    result = _list(client, search="CN-2026")
    assert _numbers(result) == ["CN-2026-001"]


def test_a_legacy_row_reads_back_as_outward(client, seeded):
    """CreditNoteOut must not blow up on a NULL direction."""
    result = _list(client, search="CN-2025-099")
    assert result["items"][0]["direction"] == "outward"


def test_voucher_type_cannot_be_flipped_under_a_credit_note(client, db_session, seeded):
    """Direction is settled at creation; flipping the invoice would strand it.

    It drives numbering, the stock effect and whether the note is filed in
    GSTR-1 — all three would silently go wrong.
    """
    from src.models.credit_note import CreditNoteItem
    from src.models.invoice import Invoice, InvoiceItem
    from src.services.invoice_processor import InvoiceProcessor
    from src.schemas.invoice import InvoiceCreate, InvoiceItemCreate
    from src.models.product import Product
    from fastapi import HTTPException

    user, ledger = seeded
    product = Product(sku="P-FLIP", name="Widget", price=100, gst_rate=18)
    db_session.add(product)
    db_session.flush()

    invoice = Invoice(
        invoice_number="INV-FLIP-001",
        ledger_id=ledger.id,
        voucher_type="sales",
        status="active",
        created_by=user.id,
        taxable_amount=100, cgst_amount=9, sgst_amount=9, igst_amount=0,
        total_amount=118,
        created_at=datetime(2026, 6, 1),
    )
    db_session.add(invoice)
    db_session.flush()
    item = InvoiceItem(
        invoice_id=invoice.id, product_id=product.id, quantity=1, unit_price=100,
        gst_rate=18, taxable_amount=100, tax_amount=18, line_total=118,
    )
    db_session.add(item)
    db_session.flush()

    note = db_session.query(CreditNote).filter(CreditNote.credit_note_number == "CN-2026-001").one()
    db_session.add(CreditNoteItem(
        credit_note_id=note.id, invoice_id=invoice.id, invoice_item_id=item.id,
        product_id=product.id, quantity=1, unit_price=100, gst_rate=18,
        taxable_amount=100, tax_amount=18, line_total=118,
    ))
    db_session.commit()

    payload = InvoiceCreate(
        ledger_id=ledger.id,
        voucher_type="purchase",
        items=[InvoiceItemCreate(product_id=product.id, quantity=1, unit_price=100)],
    )

    with pytest.raises(HTTPException) as exc_info:
        InvoiceProcessor(db_session).apply_payload(invoice, payload, regenerate_number=False)
    assert exc_info.value.status_code == 400
    assert "credit notes against it" in exc_info.value.detail


# ─────────────────────────────────────────────────────────────────────────────
# Numbering: a taken credit_note_number must be skipped, not 500 (issue regression)
# ─────────────────────────────────────────────────────────────────────────────
# credit_note_number is unique database-wide while each company (and each new
# financial year) starts its CN series at 1. generate_next_number used to check
# the invoices table only, so the second company's note died with an
# IntegrityError-500 — and stayed dead, because the rollback reverts the
# counter too.

def _this_year() -> int:
    from datetime import datetime

    return datetime.now().year


@contextmanager
def as_persistent_admin(db_session):
    """Swap the conftest detached-admin override for a real User row.

    Creating a company persists the active company on the signed-in user and
    refreshes it, so a transient instance would fail; the user is fetched from
    the request's own session so it stays persistent through the request.
    """
    user = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="secret",
        role=UserRole.admin,
    )
    db_session.add(user)
    db_session.commit()

    def override(db: Session = Depends(get_db)) -> User:
        found = db.query(User).filter(User.email == user.email).first()
        if found is None:
            found = user
        return found

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = override
    try:
        yield user
    finally:
        app.dependency_overrides[get_current_user] = previous


def _bootstrap_company(client, name: str) -> tuple[int, dict]:
    """Create a company through the API and give it an issuable invoice.

    Returns (company_id, headers). Each company seeds its own financial year,
    so both CN series start at number 1 in the same year — the collision state.
    """
    response = client.post(
        "/api/company/companies",
        json={"name": name, "address": "1 MG Road"},
    )
    assert response.status_code < 400, f"company create failed: {response.text}"
    company_id = response.json()["id"]
    headers = {"X-Company-Id": str(company_id)}

    year = _this_year()
    response = client.post(
        "/api/financial-years/",
        headers=headers,
        json={"label": str(year), "start_date": f"{year}-01-01", "end_date": f"{year}-12-31"},
    )
    assert response.status_code < 400, f"FY create failed: {response.text}"

    response = client.post(
        "/api/ledgers/",
        headers=headers,
        json={
            "name": f"Buyer of {name}",
            "address": "1 Dock Road",
            "gst": "29ABCDE1234F1ZW",
            "phone_number": "9999999999",
        },
    )
    assert response.status_code < 400, f"ledger create failed: {response.text}"
    buyer_id = response.json()["id"]

    response = client.post(
        "/api/products/",
        headers=headers,
        json={"sku": f"SKU-{company_id}", "name": "Widget", "price": 100, "initial_quantity": 100},
    )
    assert response.status_code < 400, f"product create failed: {response.text}"
    product_id = response.json()["id"]

    response = client.post(
        "/api/invoices/",
        headers=headers,
        json={
            "ledger_id": buyer_id,
            "voucher_type": "sales",
            "items": [{"product_id": product_id, "quantity": 5, "unit_price": 100}],
        },
    )
    assert response.status_code < 400, f"invoice create failed: {response.text}"
    inventory = response.json()
    return company_id, headers, buyer_id, inventory


def _issue_credit_note(client, headers, buyer_id, invoice) -> tuple[int, str | None]:
    response = client.post(
        "/api/credit-notes/",
        headers=headers,
        json={
            "ledger_id": buyer_id,
            "invoice_ids": [invoice["id"]],
            "credit_note_type": "return",
            "direction": "outward",
            "items": [{
                "invoice_id": invoice["id"],
                "invoice_item_id": invoice["items"][0]["id"],
                "quantity": 1,
            }],
        },
    )
    number = response.json().get("credit_note_number") if response.status_code == 200 or response.status_code == 201 else None
    return response.status_code, number


def test_a_second_company_skips_the_number_the_first_used(client, db_session):
    """Company B's first note takes the next free number, not a 500."""
    from src.models.global_settings import GlobalSettings

    db_session.add(GlobalSettings(id=1, max_companies=10))
    db_session.commit()

    with as_persistent_admin(db_session):
        _, alpha_headers, alpha_buyer, alpha_invoice = _bootstrap_company(client, "Alpha Corp")
        _, beta_headers, beta_buyer, beta_invoice = _bootstrap_company(client, "Beta Corp")

        alpha_status, alpha_number = _issue_credit_note(client, alpha_headers, alpha_buyer, alpha_invoice)
        assert alpha_status == 201, alpha_number
        assert alpha_number == f"CN-{_this_year()}-001"

        beta_status, beta_number = _issue_credit_note(client, beta_headers, beta_buyer, beta_invoice)
        assert beta_status == 201, beta_number
        assert beta_number == f"CN-{_this_year()}-002"


def test_a_number_already_in_the_registry_is_skipped(client, db_session):
    """The note is created 201 even when the next series number is used."""
    year = _this_year()

    response = client.post(
        "/api/ledgers/",
        json={
            "name": "Registry Buyer",
            "address": "1 Dock Road",
            "gst": "29ABCDE1234F1ZW",
            "phone_number": "9999999999",
        },
    )
    assert response.status_code < 400, response.text
    buyer_id = response.json()["id"]

    # Two notes already hold the numbers the CN-YYYY series is about to try.
    db_session.add_all([
        CreditNote(
            credit_note_number=f"CN-{year}-001",
            ledger_id=buyer_id,
            created_by=1,
            credit_note_type="return",
            direction="outward",
            status="active",
            taxable_amount=10, cgst_amount=0, sgst_amount=0, igst_amount=0,
            total_amount=10,
            created_at=datetime(year, 1, 2),
        ),
        CreditNote(
            credit_note_number=f"CN-{year}-002",
            ledger_id=buyer_id,
            created_by=1,
            credit_note_type="return",
            direction="outward",
            status="active",
            taxable_amount=10, cgst_amount=0, sgst_amount=0, igst_amount=0,
            total_amount=10,
            created_at=datetime(year, 1, 3),
        ),
    ])
    db_session.commit()

    # A financial year seeds the CN-YYYY series (starting at 1), so the create
    # takes the series path rather than the no-series fallback and must walk
    # past both taken numbers.
    response = client.post(
        "/api/financial-years/",
        json={"label": str(year), "start_date": f"{year}-01-01", "end_date": f"{year}-12-31"},
    )
    assert response.status_code < 400, response.text

    response = client.post(
        "/api/products/",
        json={"sku": "SKU-CNREG", "name": "Widget", "price": 100, "initial_quantity": 100},
    )
    assert response.status_code < 400, response.text
    product_id = response.json()["id"]

    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": buyer_id,
            "voucher_type": "sales",
            "items": [{"product_id": product_id, "quantity": 5, "unit_price": 100}],
        },
    )
    assert response.status_code < 400, response.text
    invoice = response.json()

    status, number = _issue_credit_note(client, {}, buyer_id, invoice)
    assert status == 201, number
    # CN-2026-001 and CN-2026-002 were taken; the counter walks past both.
    assert number == f"CN-{year}-003"
