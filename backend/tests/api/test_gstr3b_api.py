"""The worksheet routes, on documents created through the real invoice and note APIs.

The figures in these tests come from the same write paths production uses, so a
change in how a tax-inclusive line or a discount is stored fails here rather than
quietly changing what the worksheet reports.
"""

import csv
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app_main import app
from src.api.deps import get_current_user
from src.core import analytics
from src.core.config import settings
from src.core.validation import GSTIN_ALPHABET, is_valid_gstin_checksum
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice, InvoiceItem
from src.models.user import User, UserRole

PERIOD = {"from_date": "2026-06-01", "to_date": "2026-06-30"}
WORKSHEET = "/api/ledgers/tax-ledger/gstr3b/worksheet"
EXPORT_CSV = "/api/ledgers/tax-ledger/gstr3b/export-csv"
EXPORT_PDF = "/api/ledgers/tax-ledger/gstr3b/export-pdf"
IN_JUNE = "2026-06-15"


def _gstin(body: str) -> str:
    """Finish a 14-character GSTIN with the check digit that makes it valid."""
    return next(body + c for c in GSTIN_ALPHABET if is_valid_gstin_checksum(body + c))


COMPANY_GSTIN = _gstin("29AAPFU0939F1Z")
INTRA_GSTIN = _gstin("29AABCA1234D1Z")
INTER_GSTIN = _gstin("27AABNV5432F1Z")


@pytest.fixture
def shared_hosting(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "shared_hosting")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr(settings, "MAX_COMPANIES_PER_USER", 3)


@pytest.fixture
def act_as():
    holder = {"email": None}

    def _current_user(db: Session = Depends(get_db)) -> User:
        return db.query(User).filter(User.email == holder["email"]).one()

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _current_user

    def switch(user: User) -> None:
        holder["email"] = user.email

    try:
        yield switch
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous


def _user(db, email: str) -> User:
    user = User(
        email=email,
        full_name=email.split("@")[0].title(),
        hashed_password="not-a-real-hash",
        role=UserRole.admin,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json()


def _company(client, name: str, gst: str = COMPANY_GSTIN) -> int:
    return _ok(client.post("/api/company/companies", json={
        "name": name, "address": "1 Market Road", "gst": gst, "phone_number": "",
        "currency_code": "INR", "email": "", "website": "", "bank_name": "",
        "branch_name": "", "account_name": "", "account_number": "", "ifsc_code": "",
    }))["id"]


def _ledger(client, name: str, gst: str = "", headers=None) -> int:
    return _ok(client.post("/api/ledgers/", headers=headers, json={
        "name": name, "address": "1 Market Road", "gst": gst, "opening_balance": None,
        "phone_number": "9876543210", "email": "", "website": "", "bank_name": "",
        "branch_name": "", "account_name": "", "account_number": "", "ifsc_code": "",
    }))["id"]


def _product(client, sku: str, gst_rate: float = 18, price: float = 100, headers=None) -> int:
    return _ok(client.post("/api/products/", headers=headers, json={
        "sku": sku, "name": f"Widget {sku}", "price": price, "gst_rate": gst_rate,
        "hsn_sac": "8471", "maintain_inventory": True, "initial_quantity": 1000,
    }))["id"]


def _invoice(client, ledger: int, lines, *, voucher="sales", when=IN_JUNE, headers=None, **fields) -> dict:
    return _ok(client.post("/api/invoices/", headers=headers, json={
        "ledger_id": ledger,
        "voucher_type": voucher,
        "invoice_date": when,
        "supplier_invoice_number": f"SUP-{ledger}-{len(lines)}-{fields.get('discount_value', 0)}-{when}" if voucher == "purchase" else None,
        "items": [
            {"product_id": product, "quantity": quantity, "unit_price": price, **extra}
            for product, quantity, price, extra in lines
        ],
        **fields,
    }))


def _line(product: int, quantity: float, price: float, **extra):
    return (product, quantity, price, extra)


def _note(client, db, ledger: int, invoice: dict, *, quantity=1, direction="outward", when=datetime(2026, 6, 20, 10), note_type="return", discount=None, number_tag="1", headers=None) -> dict:
    item = {"invoice_id": invoice["id"], "invoice_item_id": invoice["items"][0]["id"]}
    if note_type == "discount":
        item["discount_amount_inclusive"] = discount
    else:
        item["quantity"] = quantity
    payload = {
        "ledger_id": ledger,
        "invoice_ids": [invoice["id"]],
        "credit_note_type": note_type,
        "direction": direction,
        "items": [item],
    }
    if direction == "inward":
        payload["supplier_credit_note_number"] = f"SUP-CN-{invoice['id']}-{number_tag}"
        payload["supplier_credit_note_date"] = when.date().isoformat()
    note = _ok(client.post("/api/credit-notes/", headers=headers, json=payload), 201)
    # A note is dated today unless told otherwise; set it so the test is about
    # the rule and not about which month it runs in.
    db.query(CreditNote).filter(CreditNote.id == note["id"]).update({"created_at": when, "credit_note_date": when})
    db.commit()
    return note


def _sheet(client, headers=None, **period) -> dict:
    return _ok(client.get(WORKSHEET, params=period or PERIOD, headers=headers))


def _row(sheet: dict, key: str) -> dict:
    return next(row for section in sheet["sections"] for row in section["rows"] if row["key"] == key)


def _warning(sheet: dict, code: str) -> dict | None:
    return next((warning for warning in sheet["warnings"] if warning["code"] == code), None)


def _head(sheet: dict, head: str) -> dict:
    return next(line for line in sheet["setoff"]["lines"] if line["head"] == head)


@pytest.fixture
def books(client, db_session, act_as):
    """One company in single-tenant mode, with parties and products to sell."""
    user = _user(db_session, "owner@example.com")
    act_as(user)
    company = _company(client, "Respawn Traders")
    return SimpleNamespace(
        user=user,
        company=company,
        intra=_ledger(client, "Karnataka Customer", INTRA_GSTIN),
        inter=_ledger(client, "Maharashtra Customer", INTER_GSTIN),
        walk_in=_ledger(client, "Walk-in Customer"),
        at18=_product(client, "AT18", 18),
        at5=_product(client, "AT5", 5),
        at0=_product(client, "AT0", 0),
    )


# --- route order ------------------------------------------------------------

def test_routes_do_not_fall_into_the_ledger_id_route(client, books):
    # /{ledger_id} would answer 422 for a non-integer id if it matched first.
    assert client.get(WORKSHEET, params=PERIOD).status_code == 200
    assert client.get(EXPORT_CSV, params=PERIOD).status_code == 200
    assert client.get(EXPORT_PDF, params=PERIOD).status_code == 200


def test_the_ledger_routes_still_answer_for_a_ledger(client, books):
    assert _ok(client.get(f"/api/ledgers/{books.intra}"))["name"] == "Karnataka Customer"
    assert client.get("/api/ledgers/999999").status_code == 404
    assert _ok(client.get("/api/ledgers/tax-ledger/", params=PERIOD))["from_date"] == "2026-06-01"


def test_there_is_no_json_export(client, books):
    assert client.get("/api/ledgers/tax-ledger/gstr3b/export-json", params=PERIOD).status_code == 404


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_it_is_read_only(client, books, method):
    assert getattr(client, method)(WORKSHEET).status_code == 405


# --- period rules -----------------------------------------------------------

@pytest.mark.parametrize("path", [WORKSHEET, EXPORT_CSV, EXPORT_PDF])
@pytest.mark.parametrize(
    "period",
    [
        {"from_date": "2026-06-01", "to_date": "2026-06-29"},
        {"from_date": "2026-05-01", "to_date": "2026-07-31"},
        {"from_date": "2026-04-01", "to_date": "2027-03-31"},
        {"from_date": "2026-06-30", "to_date": "2026-06-01"},
    ],
)
def test_other_periods_are_refused_on_every_route(client, books, path, period):
    response = client.get(path, params=period)
    assert response.status_code == 400
    assert "one calendar month or one quarter" in response.json()["detail"]


@pytest.mark.parametrize("path", [WORKSHEET, EXPORT_CSV, EXPORT_PDF])
def test_dates_are_required(client, books, path):
    assert client.get(path).status_code == 422


def test_quarter_covers_all_three_months_and_month_covers_one(client, books):
    _invoice(client, books.intra, [_line(books.at18, 1, 100)], when="2026-04-10")
    _invoice(client, books.intra, [_line(books.at18, 1, 100)], when="2026-06-30")
    _invoice(client, books.intra, [_line(books.at18, 1, 100)], when="2026-07-01")

    quarter = _sheet(client, from_date="2026-04-01", to_date="2026-06-30")
    assert quarter["period_type"] == "quarter"
    assert _row(quarter, "3.1a")["taxable_value"] == 200.0

    june = _sheet(client)
    assert june["period_type"] == "month"
    assert _row(june, "3.1a")["taxable_value"] == 100.0


# --- accuracy on real documents ---------------------------------------------

def test_sales_and_purchases_land_on_their_own_sides(client, books):
    _invoice(client, books.intra, [_line(books.at18, 2, 100)])
    _invoice(client, books.inter, [_line(books.at18, 1, 1000)], voucher="purchase")

    sheet = _sheet(client)
    row = _row(sheet, "3.1a")
    assert (row["taxable_value"], row["cgst"], row["sgst"], row["igst"]) == (200.0, 18.0, 18.0, 0.0)
    itc = _row(sheet, "4a5")
    assert (itc["taxable_value"], itc["igst"], itc["cgst"], itc["sgst"]) == (None, 180.0, 0.0, 0.0)


def test_inter_state_sale_is_igst(client, books):
    _invoice(client, books.inter, [_line(books.at18, 1, 100)])
    row = _row(_sheet(client), "3.1a")
    assert (row["igst"], row["cgst"], row["sgst"]) == (18.0, 0.0, 0.0)


def test_inward_note_reduces_credit_and_leaves_3_1_alone(client, db_session, books):
    _invoice(client, books.intra, [_line(books.at18, 1, 500)])
    purchase = _invoice(client, books.intra, [_line(books.at18, 4, 100)], voucher="purchase")
    _note(client, db_session, books.intra, purchase, direction="inward")

    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 500.0
    assert (_row(sheet, "4a5")["cgst"], _row(sheet, "4a5")["sgst"]) == (27.0, 27.0)
    assert _row(sheet, "4b2")["source"] == "not_tracked"
    assert _head(sheet, "cgst")["payable"] == pytest.approx(18.0)


def test_outward_note_reduces_3_1a(client, db_session, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 4, 100)])
    _note(client, db_session, books.intra, sale)
    row = _row(_sheet(client), "3.1a")
    assert (row["taxable_value"], row["cgst"], row["sgst"]) == (300.0, 27.0, 27.0)


def test_note_in_another_period_does_not_count_here(client, db_session, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 4, 100)])
    _note(client, db_session, books.intra, sale, when=datetime(2026, 7, 1, 0, 0))
    assert _row(_sheet(client), "3.1a")["taxable_value"] == 400.0


def test_tax_inclusive_invoice_reports_the_ex_gst_value(client, books):
    invoice = _invoice(client, books.intra, [_line(books.at18, 2, 118)], tax_inclusive=True)
    assert float(invoice["total_amount"]) == 236.0

    row = _row(_sheet(client), "3.1a")
    # Not 236, and not 236 plus tax on top.
    assert (row["taxable_value"], row["cgst"], row["sgst"]) == (200.0, 18.0, 18.0)


def test_return_on_a_tax_inclusive_invoice_is_not_flagged(client, db_session, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 2, 118)], tax_inclusive=True)
    _note(client, db_session, books.intra, sale)

    sheet = _sheet(client)
    assert _warning(sheet, "note_exceeds_source") is None
    assert _row(sheet, "3.1a")["taxable_value"] == pytest.approx(200 - 100)


def test_older_return_on_a_tax_inclusive_invoice_is_flagged(client, db_session, books):
    # Issue #572: notes from before the fix stored the inclusive price as if it were taxable.
    sale = _invoice(client, books.intra, [_line(books.at18, 2, 118)], tax_inclusive=True)
    note = _note(client, db_session, books.intra, sale)
    db_session.query(CreditNoteItem).filter(CreditNoteItem.credit_note_id == note["id"]).update({"taxable_amount": 118})
    db_session.commit()

    sheet = _sheet(client)
    warning = _warning(sheet, "note_exceeds_source")
    assert warning["documents"][0]["number"] == note["credit_note_number"]
    assert warning["documents"][0]["kind"] == "credit_note"
    # Stored value, as GSTR-1 reports it, with the warning saying why that is off.
    assert _row(sheet, "3.1a")["taxable_value"] == pytest.approx(200 - 118)


def test_line_discount_is_already_in_the_taxable_value(client, books):
    _invoice(client, books.intra, [_line(books.at18, 1, 100, discount_type="percentage", discount_value=10)])
    row = _row(_sheet(client), "3.1a")
    assert (row["taxable_value"], row["cgst"], row["sgst"]) == (90.0, 8.1, 8.1)


def test_invoice_level_discount_leaves_the_figures_and_is_named(client, books):
    invoice = _invoice(
        client, books.intra, [_line(books.at18, 10, 100)],
        discount_type="net", discount_value=118,
    )
    assert float(invoice["total_amount"]) == pytest.approx(1062.0)

    sheet = _sheet(client)
    row = _row(sheet, "3.1a")
    # The stored tax is what the invoice printed and what GSTR-1 files.
    assert (row["taxable_value"], row["cgst"], row["sgst"]) == (1000.0, 90.0, 90.0)
    warning = _warning(sheet, "invoice_level_discount")
    assert warning["documents"][0]["number"] == invoice["invoice_number"]
    assert warning["documents"][0]["detail"] == "Discount ₹118.00"


def test_round_off_does_not_touch_the_figures(client, books):
    _invoice(client, books.intra, [_line(books.at18, 1, 100.5)], apply_round_off=True)
    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 100.5
    assert _warning(sheet, "invoice_level_discount") is None


def test_cancelled_invoice_counts_for_nothing(client, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 1, 100)])
    purchase = _invoice(client, books.inter, [_line(books.at18, 1, 100)], voucher="purchase")
    _ok(client.delete(f"/api/invoices/{sale['id']}"))
    _ok(client.delete(f"/api/invoices/{purchase['id']}"))

    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 0.0
    assert _row(sheet, "4a5")["igst"] == 0.0


def test_restored_invoice_counts_again(client, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 1, 100)])
    _ok(client.delete(f"/api/invoices/{sale['id']}"))
    _ok(client.post(f"/api/invoices/{sale['id']}/restore"))
    assert _row(_sheet(client), "3.1a")["taxable_value"] == 100.0


def test_cancelled_note_counts_for_nothing(client, db_session, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 4, 100)])
    note = _note(client, db_session, books.intra, sale)
    _ok(client.post(f"/api/credit-notes/{note['id']}/cancel"))
    assert _row(_sheet(client), "3.1a")["taxable_value"] == 400.0


def test_zero_rate_sale_is_on_the_unclassified_row(client, books):
    _invoice(client, books.intra, [_line(books.at0, 1, 100), _line(books.at18, 1, 200)])
    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 200.0
    assert _row(sheet, "3.1-unclassified")["taxable_value"] == 100.0
    assert _row(sheet, "3.1-unclassified")["source"] == "from_books"
    assert _warning(sheet, "zero_rate_sales") is not None


def test_warnings_identify_the_documents_to_open(client, db_session, books):
    walk_in = _invoice(client, books.walk_in, [_line(books.at18, 1, 100)])
    unregistered = _invoice(client, books.walk_in, [_line(books.at18, 1, 100)], voucher="purchase")
    # A legacy party whose stored GSTIN predates validation.
    legacy = _invoice(client, books.intra, [_line(books.at18, 1, 100)])
    db_session.query(Invoice).filter(Invoice.id == legacy["id"]).update({"ledger_gst": "29BADGSTIN"})
    db_session.commit()

    sheet = _sheet(client)
    assert _warning(sheet, "unregistered_buyer") is None
    # A sale from before place of supply was recorded.
    db_session.query(Invoice).filter(Invoice.id == walk_in["id"]).update({"place_of_supply": None})
    db_session.commit()

    sheet = _sheet(client)
    buyer = _warning(sheet, "unregistered_buyer")
    assert buyer["documents"][0]["id"] == walk_in["id"]
    assert buyer["documents"][0]["number"] == walk_in["invoice_number"]
    supplier = _warning(sheet, "unregistered_supplier_gst")
    assert supplier["documents"][0]["id"] == unregistered["id"]
    assert supplier["documents"][0]["detail"] == "GST ₹18.00"
    invalid = _warning(sheet, "invalid_gstin")
    assert invalid["documents"][0]["id"] == legacy["id"]


def test_setoff_on_real_documents(client, books):
    _invoice(client, books.intra, [_line(books.at18, 10, 100)])  # CGST 90, SGST 90
    _invoice(client, books.inter, [_line(books.at18, 5, 100)], voucher="purchase")  # IGST 90
    sheet = _sheet(client)
    # IGST credit 90 clears CGST first; SGST 90 is what is left for cash.
    assert _head(sheet, "cgst")["payable"] == 0.0
    assert _head(sheet, "sgst")["payable"] == 90.0
    assert sheet["setoff"]["total_payable"] == 90.0


# --- reconciling to the GSTR-1 export ---------------------------------------

def _gstr1_totals(export: dict) -> dict[str, dict[str, Decimal]]:
    """Sum the GSTR-1 export directly, by rate class, invoices less notes."""
    totals = {
        "taxed": dict.fromkeys(("txval", "iamt", "camt", "samt"), Decimal("0")),
        "zero": dict.fromkeys(("txval", "iamt", "camt", "samt"), Decimal("0")),
    }

    def add(det: dict, sign: int) -> None:
        bucket = totals["zero" if float(det["rt"]) == 0 else "taxed"]
        for field in bucket:
            bucket[field] += sign * Decimal(str(det[field]))

    for party in export.get("b2b", []):
        for invoice in party["inv"]:
            for item in invoice["itms"]:
                add(item["itm_det"], 1)
    for place in export.get("b2cl", []):
        for invoice in place["inv"]:
            for item in invoice["itms"]:
                add(item["itm_det"], 1)
    for row in export.get("b2cs", []):
        add(row, 1)
    for party in export.get("cdnr", []):
        for note in party["nt"]:
            for item in note["itms"]:
                add(item["itm_det"], -1)
    for note in export.get("cdnur", []):
        for item in note["itms"]:
            add(item["itm_det"], -1)
    return totals


def _assert_matches(row: dict, totals: dict[str, Decimal]) -> None:
    assert Decimal(str(row["taxable_value"])) == totals["txval"]
    assert Decimal(str(row["igst"])) == totals["iamt"]
    assert Decimal(str(row["cgst"])) == totals["camt"]
    assert Decimal(str(row["sgst"])) == totals["samt"]


@pytest.fixture
def reconciling_books(client, db_session, books):
    """Every kind of document the export and the worksheet both have to place."""
    b2b = _invoice(client, books.intra, [_line(books.at18, 10, 100), _line(books.at5, 3, 33.33)])
    inter = _invoice(client, books.inter, [_line(books.at18, 7, 77.77)])
    _invoice(client, books.walk_in, [_line(books.at18, 1, 250)])
    _invoice(client, books.walk_in, [_line(books.at5, 2, 199.99)], tax_inclusive=True)
    _invoice(client, books.intra, [_line(books.at0, 5, 40), _line(books.at18, 1, 10)])
    # Line discount, invoice discount and round-off: none may open a difference.
    _invoice(client, books.intra, [_line(books.at18, 1, 100, discount_type="percentage", discount_value=10)])
    _invoice(client, books.inter, [_line(books.at18, 3, 100)], discount_type="net", discount_value=50)
    _invoice(client, books.intra, [_line(books.at18, 1, 99.5)], apply_round_off=True)
    # A return on a tax-inclusive invoice.
    inclusive = _invoice(client, books.intra, [_line(books.at18, 2, 118)], tax_inclusive=True)
    _note(client, db_session, books.intra, inclusive)
    # Notes in every shape the export has a section for.
    _note(client, db_session, books.intra, b2b)
    _note(client, db_session, books.inter, inter)
    walk_in = _invoice(client, books.walk_in, [_line(books.at18, 2, 500)])
    _note(client, db_session, books.walk_in, walk_in, note_type="discount", discount=118)
    # Everything GSTR-1 must ignore, as the worksheet must on the output side.
    purchase = _invoice(client, books.intra, [_line(books.at18, 2, 300)], voucher="purchase")
    _note(client, db_session, books.intra, purchase, direction="inward")
    cancelled = _invoice(client, books.intra, [_line(books.at18, 9, 900)])
    _ok(client.delete(f"/api/invoices/{cancelled['id']}"))
    # And outside the period.
    _invoice(client, books.intra, [_line(books.at18, 9, 900)], when="2026-07-01")
    return books


def test_3_1_reconciles_to_the_gstr1_export(client, reconciling_books):
    export = _ok(client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=PERIOD))
    totals = _gstr1_totals(export)
    sheet = _sheet(client)
    assert totals["taxed"]["txval"] > 0 and totals["zero"]["txval"] > 0
    assert totals["taxed"]["iamt"] > 0 and totals["taxed"]["camt"] > 0

    # The one labelled difference the two can legitimately show without any
    # warning: the export files 0% lines inside B2B and B2CS, and the worksheet
    # pulls them onto their own row. Together they are the same supplies.
    _assert_matches(_row(sheet, "3.1a"), totals["taxed"])
    _assert_matches(_row(sheet, "3.1-unclassified"), totals["zero"])
    assert _warning(sheet, "note_on_cancelled_invoice") is None


def test_a_note_on_a_cancelled_invoice_is_the_labelled_difference(client, db_session, reconciling_books):
    books = reconciling_books
    sale = _invoice(client, books.intra, [_line(books.at18, 4, 100)])
    note = _note(client, db_session, books.intra, sale)
    _ok(client.delete(f"/api/invoices/{sale['id']}"))

    export = _ok(client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=PERIOD))
    totals = _gstr1_totals(export)["taxed"]
    sheet = _sheet(client)
    row = _row(sheet, "3.1a")

    # The export still subtracts this note although its sale is gone (#602). The
    # worksheet does not, so it is higher by exactly the note, and says so.
    assert Decimal(str(row["taxable_value"])) - totals["txval"] == Decimal("100")
    assert Decimal(str(row["cgst"])) - totals["camt"] == Decimal("9")
    assert Decimal(str(row["sgst"])) - totals["samt"] == Decimal("9")
    warning = _warning(sheet, "note_on_cancelled_invoice")
    assert warning["documents"][0]["number"] == note["credit_note_number"]
    assert "₹100.00 taxable, ₹18.00 GST" in warning["documents"][0]["detail"]


def test_output_tax_in_6_1_matches_the_tax_ledger(client, reconciling_books):
    ledger = _ok(client.get("/api/ledgers/tax-ledger/", params=PERIOD))["liability"]
    sheet = _sheet(client)
    for head in ("igst", "cgst", "sgst"):
        line = _head(sheet, head)
        assert line["output_tax"] == pytest.approx(ledger[head]["output_tax"], abs=0.01)
        assert line["input_credit"] == pytest.approx(ledger[head]["input_credit"], abs=0.01)
        assert line["payable"] == pytest.approx(ledger[head]["payable"], abs=0.01)


# --- which period a note belongs to -------------------------------------------

def test_a_backdated_note_counts_in_the_month_of_its_credit_note_date(client, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 10, 100)])
    item = {"invoice_id": sale["id"], "invoice_item_id": sale["items"][0]["id"], "quantity": 5}
    # Entered today through the API, dated in June.
    _ok(client.post("/api/credit-notes/", json={
        "ledger_id": books.intra,
        "invoice_ids": [sale["id"]],
        "credit_note_type": "return",
        "direction": "outward",
        "credit_note_date": "2026-06-20",
        "items": [item],
    }), 201)

    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 500.0
    assert _head(sheet, "cgst")["output_tax"] == 45.0
    assert _head(sheet, "cgst")["output_tax"] == _ledger_head(client, "cgst")["output_tax"]
    export = _ok(client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=PERIOD))
    assert Decimal(str(_row(sheet, "3.1a")["taxable_value"])) == _gstr1_totals(export)["taxed"]["txval"]


def test_a_note_written_just_after_midnight_ist_counts_in_the_new_month(client, db_session, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 10, 100)])
    note = _note(client, db_session, books.intra, sale)
    # 00:30 IST on 1 July is still 30 June in the UTC created_at.
    db_session.query(CreditNote).filter(CreditNote.id == note["id"]).update(
        {"created_at": datetime(2026, 6, 30, 19, 0), "credit_note_date": datetime(2026, 7, 1)}
    )
    db_session.commit()

    june = _sheet(client)
    assert _row(june, "3.1a")["taxable_value"] == 1000.0
    assert _warning(june, "utc_period_edge") is None
    july = _sheet(client, from_date="2026-07-01", to_date="2026-07-31")
    assert _row(july, "3.1a")["taxable_value"] == -100.0


# --- notes on the other side from their direction -----------------------------

def _redirect(db, note: dict, direction: str) -> None:
    """What migration 20260904000001 did: stamp a direction the write path would refuse."""
    db.query(CreditNote).filter(CreditNote.id == note["id"]).update({"direction": direction})
    db.commit()


def _ledger_head(client, head: str) -> dict:
    return _ok(client.get("/api/ledgers/tax-ledger/", params=PERIOD))["liability"][head]


def test_older_outward_note_against_a_purchase_agrees_with_the_tax_ledger(client, db_session, books):
    _invoice(client, books.intra, [_line(books.at18, 10, 100)])
    purchase = _invoice(client, books.intra, [_line(books.at18, 10, 100)], voucher="purchase")
    note = _note(client, db_session, books.intra, purchase, quantity=5, direction="inward")
    _redirect(db_session, note, "outward")

    sheet = _sheet(client)
    assert (_row(sheet, "4a5")["cgst"], _row(sheet, "4a5")["sgst"]) == (45.0, 45.0)
    assert _row(sheet, "3.1a")["cgst"] == 90.0
    for head in ("igst", "cgst", "sgst"):
        ledger = _ledger_head(client, head)
        assert _head(sheet, head)["input_credit"] == pytest.approx(ledger["input_credit"], abs=0.01)
        assert _head(sheet, head)["output_tax"] == pytest.approx(ledger["output_tax"], abs=0.01)
        assert _head(sheet, head)["payable"] == pytest.approx(ledger["payable"], abs=0.01)
    assert sum(_head(sheet, h)["payable"] for h in ("igst", "cgst", "sgst")) == pytest.approx(90.0)

    warning = _warning(sheet, "note_direction_overridden")
    assert warning["documents"][0]["id"] == note["id"]
    assert "GSTR-1" in warning["message"]


def test_older_inward_note_against_a_sale_agrees_with_the_tax_ledger(client, db_session, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 10, 100)])
    _invoice(client, books.intra, [_line(books.at18, 10, 100)], voucher="purchase")
    note = _note(client, db_session, books.intra, sale, quantity=5)
    _redirect(db_session, note, "inward")

    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 500.0
    assert _row(sheet, "4a5")["cgst"] == 90.0
    for head in ("igst", "cgst", "sgst"):
        ledger = _ledger_head(client, head)
        assert _head(sheet, head)["output_tax"] == pytest.approx(ledger["output_tax"], abs=0.01)
        assert _head(sheet, head)["input_credit"] == pytest.approx(ledger["input_credit"], abs=0.01)
    assert _warning(sheet, "note_direction_overridden") is not None


def test_a_note_on_a_different_head_from_its_invoice_is_named(client, db_session, books):
    sale = _invoice(client, books.intra, [_line(books.at18, 10, 100)])
    note = _note(client, db_session, books.intra, sale, quantity=5)
    # A corrected GSTIN: the note header now says IGST, the invoice line was CGST/SGST.
    db_session.query(CreditNote).filter(CreditNote.id == note["id"]).update({"igst_amount": 90})
    db_session.commit()

    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["igst"] == -90.0
    warning = _warning(sheet, "note_head_mismatch")
    assert warning["documents"][0]["id"] == note["id"]
    assert "Tax Ledger" in warning["message"]


def test_a_note_on_the_same_head_as_its_invoice_is_not_named(client, db_session, books):
    _note(client, db_session, books.intra, _invoice(client, books.intra, [_line(books.at18, 10, 100)]), quantity=5)
    assert _warning(_sheet(client), "note_head_mismatch") is None


# --- the edges of a period ----------------------------------------------------

def _stamp(db, invoice: dict, when: datetime) -> None:
    db.query(Invoice).filter(Invoice.id == invoice["id"]).update({"invoice_date": when})
    db.commit()


EDGES = [
    (datetime(2026, 5, 31, 23, 59, 59, 999999), False),
    (datetime(2026, 6, 1, 0, 0, 0), True),
    (datetime(2026, 6, 30, 23, 59, 59, 999999), True),
    (datetime(2026, 7, 1, 0, 0, 0), False),
]


@pytest.mark.parametrize("when,counted", EDGES)
def test_an_invoice_on_the_first_or_last_moment_of_the_period(client, db_session, books, when, counted):
    _stamp(db_session, _invoice(client, books.intra, [_line(books.at18, 1, 100)]), when)
    row = _row(_sheet(client), "3.1a")
    assert row["taxable_value"] == (100.0 if counted else 0.0)


@pytest.mark.parametrize("when,counted", EDGES)
def test_a_purchase_on_the_first_or_last_moment_of_the_period(client, db_session, books, when, counted):
    _stamp(db_session, _invoice(client, books.intra, [_line(books.at18, 1, 100)], voucher="purchase"), when)
    assert _row(_sheet(client), "4a5")["cgst"] == (9.0 if counted else 0.0)


@pytest.mark.parametrize("when,counted", EDGES)
def test_a_note_on_the_first_or_last_moment_of_the_period(client, db_session, books, when, counted):
    sale = _invoice(client, books.intra, [_line(books.at18, 10, 100)])
    _note(client, db_session, books.intra, sale, quantity=1, when=when)
    assert _row(_sheet(client), "3.1a")["taxable_value"] == (900.0 if counted else 1000.0)


@pytest.mark.parametrize("when,counted", EDGES)
def test_an_inward_note_on_the_first_or_last_moment_of_the_period(client, db_session, books, when, counted):
    purchase = _invoice(client, books.intra, [_line(books.at18, 10, 100)], voucher="purchase")
    _note(client, db_session, books.intra, purchase, quantity=1, direction="inward", when=when)
    assert _row(_sheet(client), "4a5")["cgst"] == (81.0 if counted else 90.0)


def test_invoices_stored_late_on_the_last_day_are_named_but_still_counted(client, db_session, books):
    late = _invoice(client, books.intra, [_line(books.at18, 1, 100)])
    _stamp(db_session, late, datetime(2026, 6, 30, 19, 0))
    early = _invoice(client, books.intra, [_line(books.at18, 1, 100)])
    _stamp(db_session, early, datetime(2026, 6, 30, 18, 0))
    sale = _invoice(client, books.intra, [_line(books.at18, 10, 100)])
    _note(client, db_session, books.intra, sale, when=datetime(2026, 6, 30, 23, 0))

    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 100.0 + 100.0 + 1000.0 - 100.0
    warning = _warning(sheet, "utc_period_edge")
    assert [(d["kind"], d["id"]) for d in warning["documents"]] == [("invoice", late["id"])]
    assert "UTC" in warning["documents"][0]["detail"]


# --- warnings, links and the CSV -----------------------------------------------

def test_csv_carries_the_section_notes(client, books):
    text = client.get(EXPORT_CSV, params=PERIOD).content.decode("utf-8-sig")
    rows = list(csv.reader(StringIO(text)))
    notes = [row[9] for row in rows if len(row) == 10 and row[2] == "Section note"]
    sheet = _sheet(client)
    expected = [section["note"] for section in sheet["sections"] if section["note"]]
    assert expected and notes == expected


@pytest.mark.parametrize("lead", ["=", "+", "-", "@"])
def test_csv_neutralises_every_formula_lead_in_free_text(client, db_session, books, lead):
    invoice = _invoice(client, books.intra, [_line(books.at18, 1, 100)])
    db_session.query(Invoice).filter(Invoice.id == invoice["id"]).update(
        {"invoice_number": f"{lead}NUM", "ledger_gst": f"{lead}BADGSTIN"}
    )
    db_session.query(CompanyProfile).update({"name": f"{lead}Company"})
    db_session.commit()

    rows = list(csv.reader(StringIO(client.get(EXPORT_CSV, params=PERIOD).content.decode("utf-8-sig"))))
    cells = {cell for row in rows for cell in row}
    # The number, the detail built from the stored GSTIN, and the company name.
    assert f"'{lead}NUM" in cells
    assert f"'{lead}BADGSTIN: not a valid 15-character GSTIN" in cells
    assert f"'{lead}Company" in cells
    assert not {f"{lead}NUM", f"{lead}BADGSTIN: not a valid 15-character GSTIN", f"{lead}Company"} & cells


def test_csv_neutralises_the_company_gstin(client, db_session, books):
    db_session.query(CompanyProfile).update({"gst": "=1+1"})
    db_session.commit()
    rows = list(csv.reader(StringIO(client.get(EXPORT_CSV, params=PERIOD).content.decode("utf-8-sig"))))
    company_row = next(row for row in rows if row and row[0] == "Company")
    assert company_row[3] == "'=1+1"


def test_pdf_template_shows_amounts_next_to_documents_and_points_to_the_csv(client, books):
    from src.schemas.gstr3b import Gstr3bWorksheetOut
    from src.services.pdf_templates.gstr3b_template import build_gstr3b_worksheet_html

    sheet = _sheet(client)
    sheet["warnings"] = [{
        "code": "invalid_gstin", "severity": "warning", "title": "Bad GSTIN", "message": "Fix them.",
        "documents": [
            {"kind": "invoice", "id": i, "number": f"INV-{i}", "detail": "<b>GST</b> \u20b9%d.00" % i}
            for i in range(1, 21)
        ],
    }]
    html = build_gstr3b_worksheet_html(
        Gstr3bWorksheetOut.model_validate(sheet), company_name="Co", company_gstin=None, generated_at=datetime(2026, 7, 1),
    )
    assert "INV-1: &lt;b&gt;GST&lt;/b&gt;" in html
    assert "<b>GST</b>" not in html
    assert "INV-15:" in html and "INV-16" not in html
    assert "and 5 more, listed in the CSV export" in html


def test_pdf_label_is_repeated_on_every_page(client, books):
    from src.schemas.gstr3b import Gstr3bWorksheetOut
    from src.services.pdf_templates.gstr3b_template import build_gstr3b_worksheet_html

    html = build_gstr3b_worksheet_html(
        Gstr3bWorksheetOut.model_validate(_sheet(client)), company_name="Co", company_gstin=None, generated_at=datetime(2026, 7, 1),
    )
    margin_box = html[html.index("@top-center"):]
    margin_box = margin_box[: margin_box.index("}")]
    assert "Worksheet, not a return" in margin_box
    assert "not a filing" in margin_box


# --- exports and labelling --------------------------------------------------

def test_csv_says_what_it_is_and_has_one_row_per_line(client, books):
    _invoice(client, books.walk_in, [_line(books.at18, 1, 100)])
    response = client.get(EXPORT_CSV, params=PERIOD)
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="gstr3b_worksheet_2026-06-01_2026-06-30.csv"' in response.headers["content-disposition"]

    text = response.content.decode("utf-8-sig")
    rows = list(csv.reader(StringIO(text)))
    assert "not a return" in rows[0][0]
    assert all(phrase in rows[1][0] for phrase in ("estimate", "cross-checking", "not a filing", "take precedence"))

    by_table = {row[1]: row for row in rows if len(row) > 3 and row[3] in ("from_books", "not_tracked") and not row[2].startswith("  ")}
    assert by_table["3.1(a)"][3] == "from_books"
    assert by_table["3.1(a)"][4] == "100.00"
    assert by_table["3.1(b)"][3] == "not_tracked"
    # Blank, not zero.
    assert by_table["3.1(b)"][4:8] == ["", "", "", ""]
    assert any("portal" in cell for row in rows for cell in row if "5.1" in cell)
    assert any(row and row[0] == "Known limits" for row in rows)


def test_csv_neutralises_formulas_in_free_text(client, db_session, books):
    invoice = _invoice(client, books.walk_in, [_line(books.at18, 1, 100)])
    db_session.query(Invoice).filter(Invoice.id == invoice["id"]).update({"invoice_number": "=HYPERLINK(1)", "place_of_supply": None})
    db_session.commit()
    text = client.get(EXPORT_CSV, params=PERIOD).content.decode("utf-8-sig")
    assert ",'=HYPERLINK(1)" in text


def test_pdf_renders(client, books):
    _invoice(client, books.walk_in, [_line(books.at18, 1, 100)])
    response = client.get(EXPORT_PDF, params=PERIOD)
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert 'filename="gstr3b_worksheet_2026-06-01_2026-06-30.pdf"' in response.headers["content-disposition"]


def test_pdf_template_is_labelled_and_escapes_tenant_text(client, db_session, books):
    from src.schemas.gstr3b import Gstr3bWorksheetOut
    from src.services.pdf_templates.gstr3b_template import build_gstr3b_worksheet_html

    invoice = _invoice(client, books.walk_in, [_line(books.at18, 1, 100)])
    db_session.query(Invoice).filter(Invoice.id == invoice["id"]).update({"invoice_number": "<img src=x>"})
    db_session.commit()

    sheet = Gstr3bWorksheetOut.model_validate(_sheet(client))
    html = build_gstr3b_worksheet_html(
        sheet, company_name="<b>Respawn</b>", company_gstin=COMPANY_GSTIN, generated_at=datetime(2026, 7, 1),
    )
    assert "<h1>Worksheet, not a return</h1>" in html
    assert "cross-checking" in html and "not a filing" in html and "take precedence" in html
    assert "Not tracked" in html
    assert "<b>Respawn</b>" not in html and "&lt;b&gt;Respawn" in html
    assert "<img src=x>" not in html


def test_the_worksheet_response_says_what_it_is(client, books):
    sheet = _sheet(client)
    assert sheet["headline"] == "Worksheet, not a return"
    for phrase in ("estimate", "cross-checking", "not a filing", "take precedence"):
        assert phrase in sheet["disclaimer"]
    assert "portal" in sheet["table_5_1_note"]


# --- analytics --------------------------------------------------------------

class _RecordingClient:
    def __init__(self):
        self.captured = []

    def capture(self, event, distinct_id=None, properties=None, disable_geoip=None):
        self.captured.append((event, distinct_id, properties or {}))

    def set(self, distinct_id=None, properties=None):
        pass

    def capture_exception(self, exc, distinct_id=None, properties=None, disable_geoip=None):
        pass

    def shutdown(self):
        pass


@pytest.fixture
def events(monkeypatch):
    recorder = _RecordingClient()
    monkeypatch.setattr(analytics, "_client", recorder)
    monkeypatch.setattr(analytics, "_init_attempted", True)
    yield recorder
    analytics.bind_request(None, "api")


def _named(events, name: str):
    return [captured for captured in events.captured if captured[0] == name]


def test_viewing_captures_no_amounts_or_names(client, books, events):
    _invoice(client, books.walk_in, [_line(books.at18, 1, 123.45)])
    _sheet(client)

    [(_, distinct_id, properties)] = _named(events, "gstr3b_worksheet_viewed")
    assert distinct_id == "owner@example.com"
    assert properties["period_type"] == "month"
    assert properties["warning_count"] == 0
    assert properties["has_net_payable"] is True

    flat = repr(properties)
    for secret in ("123.45", "22.22", "Walk-in", "Respawn", "INV-", COMPANY_GSTIN):
        assert secret not in flat


@pytest.mark.parametrize("path,fmt", [(EXPORT_CSV, "csv"), (EXPORT_PDF, "pdf")])
def test_exporting_captures_only_the_format_and_period_type(client, books, events, path, fmt):
    _invoice(client, books.walk_in, [_line(books.at18, 1, 123.45)])
    assert client.get(path, params=PERIOD).status_code == 200

    [(_, _, properties)] = _named(events, "gstr3b_exported")
    assert properties["format"] == fmt
    assert properties["period_type"] == "month"
    assert "123.45" not in repr(properties)


def test_a_refused_period_captures_nothing(client, books, events):
    assert client.get(WORKSHEET, params={"from_date": "2026-06-01", "to_date": "2026-06-02"}).status_code == 400
    assert _named(events, "gstr3b_worksheet_viewed") == []


# --- tenant isolation, shared hosting ---------------------------------------

@pytest.fixture
def tenants(client, db_session, shared_hosting, act_as):
    user_b = _user(db_session, "bob@beta.example")
    act_as(user_b)
    company_b = _company(client, "Beta Stores")

    user_a = _user(db_session, "alice@alpha.example")
    act_as(user_a)
    company_a = _company(client, "Alpha Traders")
    ledger = _ledger(client, "Alpha Customer")
    product = _product(client, "ALPHA-1")
    sale = _invoice(client, ledger, [_line(product, 5, 100)])
    _invoice(client, ledger, [_line(product, 2, 100)], voucher="purchase")
    _note(client, db_session, ledger, sale)
    return SimpleNamespace(user_a=user_a, user_b=user_b, company_a=company_a, company_b=company_b, sale=sale)


def test_shared_hosting_owner_sees_their_figures(client, tenants, act_as):
    act_as(tenants.user_a)
    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 400.0
    assert _row(sheet, "4a5")["cgst"] == 18.0


def test_shared_hosting_stranger_sees_nothing_of_theirs(client, tenants, act_as):
    act_as(tenants.user_b)
    sheet = _sheet(client)
    assert _row(sheet, "3.1a")["taxable_value"] == 0.0
    assert _row(sheet, "4a5")["cgst"] == 0.0
    # Only the stranger's own company GSTIN state is in play: nothing of A's.
    assert sheet["warnings"] == []
    assert "Alpha" not in repr(sheet)


@pytest.mark.parametrize("path", [WORKSHEET, EXPORT_CSV, EXPORT_PDF])
def test_shared_hosting_stranger_cannot_ask_for_their_company(client, tenants, act_as, path):
    act_as(tenants.user_b)
    response = client.get(path, params=PERIOD, headers={"X-Company-Id": str(tenants.company_a)})
    assert response.status_code == 403


def test_shared_hosting_csv_does_not_leak(client, tenants, act_as):
    act_as(tenants.user_b)
    text = client.get(EXPORT_CSV, params=PERIOD).content.decode("utf-8-sig")
    assert "Alpha" not in text
    assert "Beta Stores" in text


def test_shared_hosting_null_company_rows_belong_to_nobody(client, db_session, tenants, act_as):
    _legacy_row(db_session, tenants.user_a.id)
    act_as(tenants.user_b)
    assert _row(_sheet(client), "3.1a")["taxable_value"] == 0.0
    act_as(tenants.user_a)
    assert _row(_sheet(client), "3.1a")["taxable_value"] == 400.0


def test_shared_hosting_note_cannot_read_another_tenants_invoice(client, db_session, tenants, act_as):
    # A note whose item ids point at A's invoice, sitting in B's company. The
    # source lookups are scoped, so they read as unknown and leak nothing.
    #
    # A's invoice is cancelled, so a leaked invoice lookup would print its number
    # under "note on a cancelled invoice". The note's value is far above the
    # invoice line's share, so a leaked line lookup would raise "note exceeds
    # source", which names the note. Either one fails the empty-warnings check.
    db_session.query(Invoice).filter(Invoice.id == tenants.sale["id"]).update({"status": "cancelled"})
    db_session.commit()
    note = CreditNote(
        credit_note_number="CN-B-1", company_id=tenants.company_b, ledger_id=1, created_by=tenants.user_b.id,
        credit_note_type="return", direction="outward", status="active",
        taxable_amount=1, cgst_amount=0, sgst_amount=0, igst_amount=0, total_amount=1,
        created_at=datetime(2026, 6, 20),
    )
    db_session.add(note)
    db_session.flush()
    from src.models.credit_note import CreditNoteItem

    db_session.add(CreditNoteItem(
        credit_note_id=note.id, company_id=tenants.company_b, invoice_id=tenants.sale["id"],
        invoice_item_id=tenants.sale["items"][0]["id"], product_id=None, quantity=1, unit_price=1,
        gst_rate=18, taxable_amount=100000, tax_amount=0, line_total=1,
    ))
    db_session.commit()

    act_as(tenants.user_b)
    response = client.get(WORKSHEET, params=PERIOD)
    assert tenants.sale["invoice_number"] not in response.text
    assert _sheet(client)["warnings"] == []


def _legacy_row(db, user_id: int) -> None:
    invoice = Invoice(
        invoice_number="LEGACY-1", company_id=None, voucher_type="sales", status="active", created_by=user_id,
        ledger_name="Legacy Customer", taxable_amount=1000, total_tax_amount=180, cgst_amount=90, sgst_amount=90,
        igst_amount=0, total_amount=1180, invoice_date=datetime(2026, 6, 10),
    )
    db.add(invoice)
    db.flush()
    db.add(InvoiceItem(
        invoice_id=invoice.id, product_id=1, quantity=1, unit_price=1000, gst_rate=18, taxable_amount=1000,
        tax_amount=180, cgst_amount=90, sgst_amount=90, igst_amount=0, line_total=1180,
    ))
    db.commit()


# --- tenant isolation, single tenant ----------------------------------------

def test_single_tenant_scopes_to_the_selected_company(client, db_session, act_as):
    assert settings.DEPLOYMENT_MODE == "single_tenant"
    owner = _user(db_session, "owner@example.com")
    act_as(owner)

    # Directly, because single tenant caps creation through the API at one.
    first = CompanyProfile(name="First Co", address="", gst=COMPANY_GSTIN, phone_number="", currency_code="INR")
    second = CompanyProfile(name="Second Co", address="", gst=COMPANY_GSTIN, phone_number="", currency_code="INR")
    db_session.add_all([first, second])
    db_session.commit()

    first_headers = {"X-Company-Id": str(first.id)}
    second_headers = {"X-Company-Id": str(second.id)}
    ledger = _ledger(client, "First Customer", headers=first_headers)
    product = _product(client, "F-1", headers=first_headers)
    _invoice(client, ledger, [_line(product, 1, 100)], headers=first_headers)

    assert _row(_sheet(client, headers=first_headers, **PERIOD), "3.1a")["taxable_value"] == 100.0
    assert _row(_sheet(client, headers=second_headers, **PERIOD), "3.1a")["taxable_value"] == 0.0


def test_single_tenant_counts_rows_from_before_company_scoping(client, db_session, books):
    # Single tenant keeps the historical rule: NULL company_id is the owner's.
    _legacy_row(db_session, books.user.id)
    assert _row(_sheet(client), "3.1a")["taxable_value"] == 1000.0


# --- MCP --------------------------------------------------------------------

def test_mcp_descriptions_say_it_is_an_estimate():
    from src.mcp_server.overrides import CORE_TOOLS, DESCRIPTION_OVERRIDES, NAME_OVERRIDES

    assert "gstr3b_worksheet" in CORE_TOOLS
    for path, name in (
        (WORKSHEET, "gstr3b_worksheet"),
        (EXPORT_CSV, "gstr3b_export_csv"),
        (EXPORT_PDF, "gstr3b_export_pdf"),
    ):
        assert NAME_OVERRIDES[("GET", path)] == name
        description = DESCRIPTION_OVERRIDES[("GET", path)].lower()
        assert "estimate" in description and "not a filing" in description

