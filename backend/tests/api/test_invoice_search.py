"""Tests for the Invoice Feed search box.

Covers the two things an operator types into it that used to return nothing:
a document number, and a serial / IMEI off a handset.  The last test pins the
tenancy rule — a serial belonging to one company must never surface another
company's invoice — and the export test pins that the CSV keeps returning the
same set as the screen, since both endpoints share ``_apply_invoice_filters``.
"""

import csv
import io

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.api.routes.invoices import _apply_invoice_filters
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.global_settings import GlobalSettings
from src.models.invoice import Invoice
from src.models.product import Product
from src.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _headers(company_id: int | None) -> dict[str, str]:
    return {} if company_id is None else {"X-Company-Id": str(company_id)}


def _persistent_current_user(db: Session = Depends(get_db)) -> User:
    """A DB-backed user, needed because creating a company writes back to it."""
    user = db.query(User).filter(User.email == "test@example.com").first()
    if user is None:
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


@pytest.fixture
def multi_company_user(db_session):
    """Persistent user plus enough headroom in the global cap for two companies."""
    settings_row = db_session.query(GlobalSettings).filter(GlobalSettings.id == 1).first()
    if settings_row is None:
        settings_row = GlobalSettings(id=1, max_companies=10)
        db_session.add(settings_row)
    else:
        settings_row.max_companies = 10
    db_session.commit()

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _persistent_current_user
    yield
    if previous is None:
        app.dependency_overrides.pop(get_current_user, None)
    else:
        app.dependency_overrides[get_current_user] = previous


def _create_company(client, name: str) -> int:
    response = client.post("/api/company/companies", json={
        "name": name,
        "address": "",
        "gst": "",
        "phone_number": "",
        "currency_code": "INR",
        "email": "",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_ledger(client, name: str, company_id: int | None = None) -> int:
    response = client.post("/api/ledgers/", headers=_headers(company_id), json={
        "name": name,
        "address": "Mumbai",
        "gst": "27ABCDE1234F1Z5",
        "phone_number": "9999999999",
        "email": "ledger@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_product(client, db_session, sku: str, name: str = "iPhone 15 128GB",
                    track_serials: bool = False, company_id: int | None = None) -> int:
    # Serial-tracked units may only enter stock through a purchase, so those
    # products start empty; untracked ones are stocked up front so a plain
    # sales invoice has something to sell.
    response = client.post("/api/products/", headers=_headers(company_id), json={
        "sku": sku,
        "name": name,
        "description": "",
        "hsn_sac": "8517",
        "price": 100,
        "gst_rate": 18,
        "unit": "Pieces",
        "allow_decimal": False,
        "maintain_inventory": True,
        "initial_quantity": 0 if track_serials else 500,
    })
    assert response.status_code == 200, response.text
    product_id = response.json()["id"]
    if track_serials:
        # track_serials is not on ProductCreate yet — same trick as test_serials.
        db_session.query(Product).filter(Product.id == product_id).update({"track_serials": True})
        db_session.commit()
    return product_id


def _create_invoice(client, ledger_id: int, product_id: int, voucher_type: str,
                    quantity: int = 1, serials: list[str] | None = None,
                    company_id: int | None = None, **extra) -> dict:
    item = {"product_id": product_id, "quantity": quantity, "unit_price": 100}
    if serials is not None:
        item["serial_numbers"] = serials
    payload = {
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "tax_inclusive": False,
        "apply_round_off": False,
        "items": [item],
        **extra,
    }
    response = client.post("/api/invoices/", headers=_headers(company_id), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _search(client, term: str, company_id: int | None = None, **params) -> list[dict]:
    response = client.get(
        "/api/invoices/",
        headers=_headers(company_id),
        params={"search": term, "page_size": 100, **params},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _export_numbers(client, term: str, company_id: int | None = None) -> list[str]:
    response = client.get(
        "/api/invoices/export",
        headers=_headers(company_id),
        params={"search": term},
    )
    assert response.status_code == 200, response.text
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    return [row[0] for row in rows[1:]]


# ---------------------------------------------------------------------------
# Document numbers
# ---------------------------------------------------------------------------

def test_search_by_invoice_number(client, db_session):
    ledger_id = _create_ledger(client, "Number Customer")
    product_id = _create_product(client, db_session, sku="NUM-1", name="Widget")
    wanted = _create_invoice(client, ledger_id, product_id, "sales")
    _create_invoice(client, ledger_id, product_id, "sales")

    number = wanted["invoice_number"]
    assert number, "invoice creation should assign a document number"

    items = _search(client, number)
    assert [item["id"] for item in items] == [wanted["id"]]


def test_search_by_invoice_number_tolerates_padding_and_case(client, db_session):
    ledger_id = _create_ledger(client, "Sloppy Typist")
    product_id = _create_product(client, db_session, sku="NUM-2", name="Widget")
    wanted = _create_invoice(client, ledger_id, product_id, "sales")

    number = wanted["invoice_number"]
    for typed in (f"  {number}  ", number.lower(), number.upper()):
        items = _search(client, typed)
        assert [item["id"] for item in items] == [wanted["id"]], typed


def test_search_by_supplier_invoice_number(client, db_session):
    ledger_id = _create_ledger(client, "Bill Supplier")
    product_id = _create_product(client, db_session, sku="NUM-3", name="Widget")
    wanted = _create_invoice(
        client, ledger_id, product_id, "purchase",
        supplier_invoice_number="SUP/2026/0099",
    )
    _create_invoice(client, ledger_id, product_id, "purchase")

    items = _search(client, "SUP/2026/0099")
    assert [item["id"] for item in items] == [wanted["id"]]


# ---------------------------------------------------------------------------
# Serials / IMEIs
# ---------------------------------------------------------------------------

def test_search_by_full_serial_finds_purchase_and_sale(client, db_session):
    ledger_id = _create_ledger(client, "Serial Trader")
    product_id = _create_product(client, db_session, sku="SER-1", track_serials=True)

    imei = "356938035643809"
    purchase = _create_invoice(
        client, ledger_id, product_id, "purchase", quantity=2,
        serials=[imei, "356938035643817"],
    )
    sale = _create_invoice(
        client, ledger_id, product_id, "sales", quantity=1, serials=[imei],
    )
    unrelated = _create_invoice(
        client, ledger_id, product_id, "sales", quantity=1,
        serials=["356938035643817"],
    )

    found = {item["id"] for item in _search(client, imei)}
    assert found == {purchase["id"], sale["id"]}
    assert unrelated["id"] not in found


def test_search_by_partial_serial_tail(client, db_session):
    ledger_id = _create_ledger(client, "Tail Typist")
    product_id = _create_product(client, db_session, sku="SER-2", track_serials=True)

    purchase = _create_invoice(
        client, ledger_id, product_id, "purchase", quantity=1,
        serials=["356938035643809"],
    )

    # The last five digits are what an operator reads off the unit's sticker.
    assert [item["id"] for item in _search(client, "43809")] == [purchase["id"]]


def test_search_by_serial_is_case_insensitive(client, db_session):
    ledger_id = _create_ledger(client, "Mixed Case")
    product_id = _create_product(client, db_session, sku="SER-3", track_serials=True)

    purchase = _create_invoice(
        client, ledger_id, product_id, "purchase", quantity=1, serials=["abc-99xz"],
    )

    assert [item["id"] for item in _search(client, "ABC-99XZ")] == [purchase["id"]]
    assert [item["id"] for item in _search(client, " abc-99xz ")] == [purchase["id"]]


def test_export_matches_screen_for_serial_search(client, db_session):
    ledger_id = _create_ledger(client, "Export Trader")
    product_id = _create_product(client, db_session, sku="SER-4", track_serials=True)

    imei = "356938035643809"
    purchase = _create_invoice(
        client, ledger_id, product_id, "purchase", quantity=1, serials=[imei],
    )
    sale = _create_invoice(
        client, ledger_id, product_id, "sales", quantity=1, serials=[imei],
    )
    _create_invoice(client, ledger_id, product_id, "purchase", quantity=1,
                    serials=["356938035643817"])

    screen = {item["invoice_number"] for item in _search(client, imei)}
    assert screen == {purchase["invoice_number"], sale["invoice_number"]}
    assert set(_export_numbers(client, imei)) == screen


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

def test_serial_search_does_not_cross_companies(client, db_session, multi_company_user):
    """Company A's IMEI must not surface company B's invoice, and vice versa."""
    company_a = _create_company(client, "Company A")
    company_b = _create_company(client, "Company B")

    imei = "356938035643809"

    ledger_a = _create_ledger(client, "A Supplier", company_id=company_a)
    product_a = _create_product(client, db_session, sku="X-A", track_serials=True,
                                company_id=company_a)
    invoice_a = _create_invoice(client, ledger_a, product_a, "purchase", quantity=1,
                                serials=[imei], company_id=company_a)

    ledger_b = _create_ledger(client, "B Supplier", company_id=company_b)
    product_b = _create_product(client, db_session, sku="X-B", track_serials=True,
                                company_id=company_b)
    invoice_b = _create_invoice(client, ledger_b, product_b, "purchase", quantity=1,
                                serials=[imei], company_id=company_b)

    from_a = [item["id"] for item in _search(client, imei, company_id=company_a)]
    from_b = [item["id"] for item in _search(client, imei, company_id=company_b)]

    assert from_a == [invoice_a["id"]]
    assert from_b == [invoice_b["id"]]


def test_serial_subquery_is_scoped_even_without_the_company_filter(
    client, db_session, multi_company_user
):
    """The filter itself is tenant-safe, not just the callers.

    Both endpoints hand ``_apply_invoice_filters`` a query already narrowed to
    the active company, which would hide a leak here.  This calls the filter
    with an unscoped base query so a serial subquery that forgot its
    ``company_id`` predicate shows up as company B's invoice in company A's
    results.
    """
    company_a = _create_company(client, "Company A")
    company_b = _create_company(client, "Company B")

    imei = "356938035643809"
    ledger_b = _create_ledger(client, "B Supplier", company_id=company_b)
    product_b = _create_product(client, db_session, sku="X-B", track_serials=True,
                                company_id=company_b)
    invoice_b = _create_invoice(client, ledger_b, product_b, "purchase", quantity=1,
                                serials=[imei], company_id=company_b)

    company_a_row = db_session.query(CompanyProfile).filter(
        CompanyProfile.id == company_a
    ).one()
    matched = _apply_invoice_filters(
        db_session.query(Invoice),
        db_session,
        company_a_row,
        search=imei,
    ).all()

    assert invoice_b["id"] not in [invoice.id for invoice in matched]
