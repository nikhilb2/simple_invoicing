"""The credit note registry, once it holds both directions.

A supplier's note is found by their number, not the one we assigned it — that
is what the user has in front of them when reconciling against GSTR-2B.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user, get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote
from src.models.invoice import InvoiceItem
from src.models.user import User, UserRole
from src.services.gst_tax_service import india_today
from tests.api.test_product_performance import _create_ledger, _create_product


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


def test_a_second_company_numbers_its_notes_independently(client, db_session):
    """Company B's first note starts its own sequence: no 500 and no gap."""
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
        assert beta_number == f"CN-{_this_year()}-001"


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


# ── What a note credits (#572, #603) ───────────────────────────────────────────


@pytest.fixture
def gst_seller(client, db_session):
    """A Karnataka seller, set directly because the check digit is not under test."""
    assert client.get("/api/company/").status_code == 200
    company = db_session.query(CompanyProfile).first()
    company.gst = "29AAAAA0000A1Z5"
    db_session.commit()
    return company


def _sale(client, line, *, place_of_supply=None, **extra):
    """A sale of one line to an unregistered buyer, dated a few days ago."""
    product = _create_product(client, f"SKU-{uuid4().hex[:8]}", "Widget", hsn_sac="8471")
    payload = {
        "voucher_type": "sales",
        "ledger_id": _create_ledger(client, f"Walk-in {uuid4().hex[:8]}"),
        "invoice_date": (india_today() - timedelta(days=3)).isoformat(),
        "items": [{"product_id": product, **line}],
        **extra,
    }
    if place_of_supply:
        payload["place_of_supply"] = place_of_supply
    response = client.post("/api/invoices/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _note(client, invoice, *, note_type="return", items=None, **line):
    return client.post("/api/credit-notes/", json={
        "ledger_id": invoice["ledger_id"],
        "invoice_ids": [invoice["id"]],
        "credit_note_type": note_type,
        "direction": "outward",
        "items": items or [{"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"], **line}],
    })


def _stored(db_session, note):
    db_session.expire_all()
    return db_session.get(CreditNote, note["id"])


def test_return_on_a_tax_inclusive_invoice_credits_what_was_paid(client, gst_seller, db_session):
    invoice = _sale(client, {"quantity": 1, "unit_price": 118, "gst_rate": 18}, tax_inclusive=True)

    response = _note(client, invoice, quantity=1)

    assert response.status_code == 201, response.text
    note = response.json()
    assert (note["taxable_amount"], note["cgst_amount"], note["sgst_amount"], note["total_amount"]) == (100, 9, 9, 118)
    assert (note["items"][0]["unit_price"], note["items"][0]["taxable_amount"]) == (100, 100)
    stored = _stored(db_session, note)
    assert (float(stored.taxable_amount), float(stored.total_amount)) == (100, 118)


def test_interstate_return_on_a_tax_inclusive_invoice_keeps_the_igst_head(client, gst_seller):
    invoice = _sale(client, {"quantity": 1, "unit_price": 1180, "gst_rate": 18}, tax_inclusive=True, place_of_supply="10")

    note = _note(client, invoice, quantity=1).json()

    assert (note["taxable_amount"], note["igst_amount"], note["cgst_amount"], note["total_amount"]) == (1000, 180, 0, 1180)


@pytest.mark.parametrize("tax_inclusive", [False, True])
@pytest.mark.parametrize("discount", [10, 50])
def test_return_of_a_discounted_line_credits_its_line_total(client, gst_seller, db_session, discount, tax_inclusive):
    invoice = _sale(client, {
        "quantity": 4, "unit_price": 118, "gst_rate": 18, "discount_type": "percentage", "discount_value": discount,
    }, tax_inclusive=tax_inclusive)
    line = invoice["items"][0]

    note = _note(client, invoice, quantity=4).json()

    assert note["total_amount"] == line["line_total"]
    assert note["taxable_amount"] == line["taxable_amount"]
    assert note["items"][0]["unit_price"] * 4 == pytest.approx(line["taxable_amount"])
    assert float(_stored(db_session, note).total_amount) == line["line_total"]


def test_partial_return_credits_its_share_of_the_line(client, gst_seller):
    invoice = _sale(client, {"quantity": 10, "unit_price": 99.99, "gst_rate": 18})
    line = invoice["items"][0]

    note = _note(client, invoice, quantity=3).json()

    assert note["taxable_amount"] == pytest.approx(line["taxable_amount"] * 3 / 10, abs=0.01)
    assert note["total_amount"] == pytest.approx(line["line_total"] * 3 / 10, abs=0.02)


def test_a_line_returned_in_parts_adds_back_to_exactly_what_it_charged(client, gst_seller):
    # 100.01 over 3 units rounds to 33.34 every time, which would come to 100.02.
    invoice = _sale(client, {"quantity": 3, "unit_price": 33.3366, "gst_rate": 18})
    line = invoice["items"][0]

    notes = [_note(client, invoice, quantity=1) for _ in range(3)]

    assert [n.status_code for n in notes] == [201, 201, 201]
    assert sum(n.json()["taxable_amount"] for n in notes) == pytest.approx(line["taxable_amount"])
    assert sum(n.json()["total_amount"] for n in notes) == pytest.approx(line["line_total"])


def test_tax_exclusive_return_is_unchanged(client, gst_seller):
    invoice = _sale(client, {"quantity": 5, "unit_price": 100, "gst_rate": 18})

    note = _note(client, invoice, quantity=2).json()

    assert (note["taxable_amount"], note["cgst_amount"], note["sgst_amount"], note["total_amount"]) == (200, 18, 18, 236)
    assert note["items"][0]["unit_price"] == 100


def test_return_on_a_line_with_only_a_total_still_credits_it(client, gst_seller, db_session):
    """Rows from before the tax columns have them at their default of 0."""
    invoice = _sale(client, {"quantity": 2, "unit_price": 100, "gst_rate": 0})
    item = db_session.get(InvoiceItem, invoice["items"][0]["id"])
    item.taxable_amount = 0
    item.tax_amount = 0
    db_session.commit()

    note = _note(client, invoice, quantity=1).json()

    assert note["total_amount"] == 100


def test_discount_note_larger_than_the_line_is_refused_and_creates_nothing(client, gst_seller, db_session):
    invoice = _sale(client, {"quantity": 1, "unit_price": 100, "gst_rate": 18})

    response = _note(client, invoice, note_type="discount", discount_amount_inclusive="5000")

    assert response.status_code == 400
    assert "118.00" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.query(CreditNote).count() == 0


def test_discount_note_equal_to_what_is_left_is_accepted(client, gst_seller):
    invoice = _sale(client, {"quantity": 1, "unit_price": 100, "gst_rate": 18})

    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="59").status_code == 201
    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="59").status_code == 201


def test_second_discount_note_past_the_line_total_is_refused(client, gst_seller):
    invoice = _sale(client, {"quantity": 1, "unit_price": 100, "gst_rate": 18})

    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="100").status_code == 201
    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="18.01").status_code == 400


def test_discount_after_a_partial_return_is_capped_at_what_is_left(client, gst_seller):
    invoice = _sale(client, {"quantity": 10, "unit_price": 100, "gst_rate": 18})
    assert _note(client, invoice, quantity=4).status_code == 201  # 472 of 1180

    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="708.01").status_code == 400
    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="708").status_code == 201


def test_return_after_a_discount_cannot_credit_more_than_the_line(client, gst_seller):
    invoice = _sale(client, {"quantity": 10, "unit_price": 100, "gst_rate": 18})
    assert _note(client, invoice, note_type="discount", discount_amount_inclusive="118").status_code == 201

    assert _note(client, invoice, quantity=10).status_code == 400
    # The discount's placeholder quantity of 1 did not use up a unit.
    assert _note(client, invoice, quantity=9).status_code == 201


def test_same_line_twice_in_one_note_is_held_to_the_limits(client, gst_seller):
    invoice = _sale(client, {"quantity": 2, "unit_price": 100, "gst_rate": 18})
    twice = {"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"]}

    returned = _note(client, invoice, items=[{**twice, "quantity": 2}, {**twice, "quantity": 2}])
    discounted = _note(client, invoice, note_type="discount", items=[
        {**twice, "discount_amount_inclusive": "200"}, {**twice, "discount_amount_inclusive": "200"},
    ])

    assert (returned.status_code, discounted.status_code) == (400, 400)


def test_note_without_a_date_can_follow_a_future_dated_invoice(client, gst_seller):
    invoice = _sale(
        client, {"quantity": 1, "unit_price": 100, "gst_rate": 18},
        invoice_date=(india_today() + timedelta(days=10)).isoformat(),
    )

    response = _note(client, invoice, quantity=1)

    assert response.status_code == 201, response.text
    assert response.json()["credit_note_date"].startswith(india_today().isoformat())
