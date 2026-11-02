"""The rule the whole feature stands on: a quotation changes nothing but itself.

Snapshot every report, list, export, return and stock figure. Create, edit and move
quotations of both types. Every figure must be byte for byte what it was. Then
convert one, and each must change by exactly that one invoice.

Separate tables make the first half true by construction, which is the point of
having them. These tests are what notices if a later change stops it being true,
including the import scan at the bottom.
"""

import ast
import csv
import io
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from quotation_helpers import (
    convert,
    create_ledger,
    create_product,
    create_quotation,
    ok,
    seed_company,
    series_counters,
)

from src.models.credit_note import CreditNote
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.ledger_address import LedgerAddress
from src.models.payment import Payment
from src.models.product_serial import ProductSerial
from src.models.share_link import ShareLink

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _period() -> dict:
    today = date.today()
    return {"from_date": (today - timedelta(days=30)).isoformat(), "to_date": (today + timedelta(days=1)).isoformat()}


def _report_urls(world: dict) -> dict[str, tuple[str, dict]]:
    """Every surface that reads invoices, by name."""
    period = _period()
    ledger, product = world["ledger"]["id"], world["product"]["id"]
    return {
        "dashboard": ("/api/dashboard/metrics", {}),
        "sales_by_month": ("/api/analytics/sales-by-month", period),
        "sales_by_month_csv": ("/api/analytics/sales-by-month/csv", period),
        "sales_by_product": ("/api/analytics/sales-by-product", period),
        "sales_by_product_csv": ("/api/analytics/sales-by-product/csv", period),
        "profit_loss": ("/api/analytics/profit-loss", period),
        "profit_loss_csv": ("/api/analytics/profit-loss/csv", period),
        "product_performance": ("/api/analytics/product-performance", period),
        "product_performance_detail": (f"/api/analytics/product-performance/{product}", period),
        "invoices": ("/api/invoices/", {"page_size": 100}),
        "invoices_cancelled_too": ("/api/invoices/", {"page_size": 100, "show_cancelled": True}),
        "invoices_csv": ("/api/invoices/export", {}),
        "dues": ("/api/invoices/dues", {}),
        "dues_ageing": ("/api/invoices/dues/ageing", {}),
        "day_book": ("/api/ledgers/day-book", period),
        "day_book_csv": ("/api/ledgers/day-book/csv", period),
        "day_book_pdf": ("/api/ledgers/day-book/pdf", period),
        "ledgers": ("/api/ledgers/", {}),
        "statement": (f"/api/ledgers/{ledger}/statement", period),
        "statement_csv": (f"/api/ledgers/{ledger}/statement/csv", period),
        "statement_pdf": (f"/api/ledgers/{ledger}/statement/pdf", period),
        "unpaid": (f"/api/ledgers/{ledger}/unpaid-invoices", {}),
        "tax_ledger": ("/api/ledgers/tax-ledger/", period),
        "tax_ledger_csv": ("/api/ledgers/tax-ledger/csv", period),
        "tax_ledger_pdf": ("/api/ledgers/tax-ledger/pdf", period),
        "gstr1_validate": ("/api/ledgers/tax-ledger/gstr1/validate", period),
        "gstr1_summary": ("/api/ledgers/tax-ledger/gstr1/summary", period),
        "gstr1_json": ("/api/ledgers/tax-ledger/gstr1/export-json", period),
        "gstr1_csv": ("/api/ledgers/tax-ledger/gstr1/export-csv", period),
        "gstr1_pdf": ("/api/ledgers/tax-ledger/gstr1/export-pdf", period),
        "inventory": ("/api/inventory/", {"page_size": 100}),
        "products_with_inventory": ("/api/products/with-inventory", {}),
        "serials": ("/api/serials/", {}),
        "payments": ("/api/payments/", {}),
        "credit_notes": ("/api/credit-notes/", {}),
    }


def _normalise(response) -> object:
    """Comparable form of a response. A PDF's bytes vary by its embedded timestamps."""
    content_type = response.headers.get("content-type", "")
    if "pdf" in content_type:
        return re.sub(rb"/(CreationDate|ModDate) \(.*?\)|/ID \[.*?\]", b"", response.content, flags=re.S)
    if "json" in content_type:
        return response.json()
    return response.text


def _snapshot(client, world: dict) -> dict[str, object]:
    snapshot = {}
    for name, (path, params) in _report_urls(world).items():
        response = client.get(path, params=params)
        assert response.status_code == 200, f"{name}: {response.status_code} {response.text[:200]}"
        snapshot[name] = _normalise(response)
    # Not the quotation counters: those are the one thing that should move.
    series = series_counters(client)
    snapshot["books_series"] = {key: value for key, value in series.items() if key not in ("quotation", "proforma")}
    return snapshot


def _rows(db_session, world: dict) -> dict[str, object]:
    """The same again from the tables, independent of any route's filtering."""
    db_session.expire_all()
    return {
        "stock": sorted((row.product_id, float(row.quantity)) for row in db_session.query(Inventory)),
        "serials": sorted(
            (row.serial_number, row.status, row.sales_invoice_id, row.purchase_invoice_id)
            for row in db_session.query(ProductSerial)
        ),
        "invoices": db_session.query(Invoice).count(),
        "invoice_items": db_session.query(InvoiceItem).count(),
        "payments": db_session.query(Payment).count(),
        "credit_notes": db_session.query(CreditNote).count(),
    }


def _assert_same(before: dict, after: dict) -> None:
    changed = [name for name in before if before[name] != after[name]]
    assert changed == [], f"A quotation changed: {changed}"


@pytest.fixture
def world(client):
    """A company with books already: a purchase, a sale, a receipt and a credit note."""
    seed_company(client)
    ledger = create_ledger(client)
    product = create_product(client, "WID-1", purchase_price=60)
    tracked = create_product(client, "PHONE-1", track_serials=True, initial_quantity=0, price=500, purchase_price=300)

    # A separate supplier: dues leave out a ledger whose payables offset its receivable.
    supplier = create_ledger(client, "Supplier One", gst="")
    ok(client.post("/api/invoices/", json={
        "ledger_id": supplier["id"],
        "voucher_type": "purchase",
        "invoice_date": date.today().isoformat(),
        "items": [{"product_id": tracked["id"], "quantity": 3, "unit_price": 300, "serial_numbers": ["IMEI-1", "IMEI-2", "IMEI-3"]}],
    }))
    sale = ok(client.post("/api/invoices/", json={
        "ledger_id": ledger["id"],
        "voucher_type": "sales",
        "invoice_date": date.today().isoformat(),
        "due_date": date.today().isoformat(),
        "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 100}],
    }))
    ok(client.post("/api/payments/", json={
        "ledger_id": ledger["id"],
        "voucher_type": "receipt",
        "amount": 50,
        "mode": "cash",
        "invoice_allocations": [{"invoice_id": sale["id"], "allocated_amount": 50}],
    }))
    ok(client.post("/api/credit-notes/", json={
        "ledger_id": ledger["id"],
        "invoice_ids": [sale["id"]],
        "credit_note_type": "return",
        "direction": "outward",
        "items": [{"invoice_id": sale["id"], "invoice_item_id": sale["items"][0]["id"], "quantity": 1}],
    }), 201)
    return {"ledger": ledger, "product": product, "tracked": tracked, "sale": sale}


def _exercise_quotations(client, world: dict) -> dict:
    """One of everything a quotation can be and do, dated inside the report period."""
    ledger, product, tracked = world["ledger"]["id"], world["product"]["id"], world["tracked"]["id"]
    today = date.today()
    lines = [
        {"product_id": product, "quantity": 2, "unit_price": 100},
        {"product_id": tracked, "quantity": 1, "unit_price": 500},
    ]
    body = {"ledger_id": ledger, "quotation_date": today.isoformat(), "items": lines}

    open_quote = ok(client.post("/api/quotations/", json=body))
    proforma = ok(client.post("/api/quotations/", json={**body, "document_type": "proforma"}))
    accepted = ok(client.post("/api/quotations/", json=body))
    ok(client.post(f"/api/quotations/{accepted['id']}/status", json={"status": "accepted", "note": "PO 7"}))
    declined = ok(client.post("/api/quotations/", json={**body, "document_type": "proforma"}))
    ok(client.post(f"/api/quotations/{declined['id']}/status", json={"status": "declined"}))
    cancelled = ok(client.post("/api/quotations/", json=body))
    ok(client.post(f"/api/quotations/{cancelled['id']}/cancel"))
    expired = ok(client.post("/api/quotations/", json={
        **body,
        "quotation_date": (today - timedelta(days=20)).isoformat(),
        "valid_until": (today - timedelta(days=10)).isoformat(),
    }))

    # Edit one, so an edit is proven as harmless as a create.
    ok(client.put(f"/api/quotations/{open_quote['id']}", json={
        "ledger_id": ledger,
        "quotation_date": today.isoformat(),
        "items": [{"product_id": product, "quantity": 5, "unit_price": 90}, lines[1]],
    }))
    ok(client.post(f"/api/quotations/{open_quote['id']}/duplicate"))

    # Reading it, printing it and sharing it must be harmless too.
    for quote in (open_quote, proforma):
        ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
        assert client.get(f"/api/quotations/{quote['id']}/pdf").status_code == 200
        ok(client.post("/api/share/", json={"resource_type": "quotation", "resource_id": quote["id"]}))
    return {"open": open_quote, "proforma": proforma, "accepted": accepted, "expired": expired}


def test_quotations_change_nothing(client, world, db_session):
    reports_before = _snapshot(client, world)
    rows_before = _rows(db_session, world)

    _exercise_quotations(client, world)

    _assert_same(reports_before, _snapshot(client, world))
    _assert_same(rows_before, _rows(db_session, world))
    # The fixture's own surfaces really are populated, so these comparisons bite.
    assert reports_before["invoices"]["total"] == 2
    assert reports_before["day_book"]["entries"]
    assert reports_before["tax_ledger"]["entries"]
    assert reports_before["gstr1_summary"]["b2b"]["invoice_count"] == 1


def test_a_quotation_series_never_moves_an_invoice_counter_and_vice_versa(client, world):
    before = series_counters(client)
    create_quotation(client, world["ledger"]["id"], world["product"]["id"])
    create_quotation(client, world["ledger"]["id"], world["product"]["id"], document_type="proforma")
    after = series_counters(client)
    assert after["quotation"] == before["quotation"] + 1
    assert after["proforma"] == before["proforma"] + 1
    assert {k: v for k, v in after.items() if k not in ("quotation", "proforma")} == {
        k: v for k, v in before.items() if k not in ("quotation", "proforma")
    }

    ok(client.post("/api/invoices/", json={
        "ledger_id": world["ledger"]["id"],
        "voucher_type": "sales",
        "items": [{"product_id": world["product"]["id"], "quantity": 1}],
    }))
    final = series_counters(client)
    assert final["sales"] == after["sales"] + 1
    assert final["quotation"] == after["quotation"] and final["proforma"] == after["proforma"]


def test_a_quotation_has_no_due_payment_or_reminder(client, world, db_session):
    quote = create_quotation(client, world["ledger"]["id"], world["product"]["id"])
    unpaid = ok(client.get(f"/api/ledgers/{world['ledger']['id']}/unpaid-invoices"))
    assert quote["quotation_number"] not in json.dumps(unpaid)
    # The id does not cross over: this quotation is not an invoice to pay against.
    response = client.post("/api/payments/", json={
        "ledger_id": world["ledger"]["id"],
        "voucher_type": "receipt",
        "amount": 10,
        "mode": "cash",
        "invoice_allocations": [{"invoice_id": 987654, "allocated_amount": 10}],
    })
    assert response.status_code in (400, 404)
    assert db_session.query(Invoice).filter(Invoice.invoice_number == quote["quotation_number"]).count() == 0


def _csv_rows(text: str) -> int:
    return len(list(csv.reader(io.StringIO(text))))


def test_converting_changes_everything_by_exactly_one_invoice(client, world, db_session):
    ledger, product, tracked = world["ledger"]["id"], world["product"]["id"], world["tracked"]["id"]
    quotes = _exercise_quotations(client, world)
    fresh = ok(client.post("/api/quotations/", json={
        "ledger_id": ledger,
        "items": [
            {"product_id": product, "quantity": 3, "unit_price": 100},
            {"product_id": tracked, "quantity": 1, "unit_price": 500},
        ],
    }))

    before = _snapshot(client, world)
    rows_before = _rows(db_session, world)
    series_before = series_counters(client)
    other_quotes_before = {
        key: ok(client.get(f"/api/quotations/{quote['id']}"))["status"] for key, quote in quotes.items()
    }

    draft = ok(client.get(f"/api/quotations/{fresh['id']}/conversion-draft"))["invoice"]
    draft["items"][1]["serial_numbers"] = ["IMEI-1"]
    draft["due_date"] = date.today().isoformat()
    invoice = ok(client.post(f"/api/quotations/{fresh['id']}/convert", json=draft))

    after = _snapshot(client, world)
    rows_after = _rows(db_session, world)
    total = invoice["total_amount"]
    taxable = invoice["taxable_amount"]
    tax = invoice["total_tax_amount"]
    assert total == fresh["total_amount"] == (300 + 500) * 1.18

    # Stock and serials: each line moved once.
    stock_before = dict(rows_before["stock"])
    stock_after = dict(rows_after["stock"])
    assert stock_after[product] == stock_before[product] - 3
    assert stock_after[tracked] == stock_before[tracked] - 1
    sold = [row for row in rows_after["serials"] if row[1] == "sold"]
    assert [(row[0], row[2]) for row in sold] == [("IMEI-1", invoice["id"])]

    # Tables.
    assert rows_after["invoices"] == rows_before["invoices"] + 1
    assert rows_after["invoice_items"] == rows_before["invoice_items"] + 2
    assert rows_after["payments"] == rows_before["payments"]
    assert rows_after["credit_notes"] == rows_before["credit_notes"]

    # Invoice list, exports, dues.
    assert after["invoices"]["total"] == before["invoices"]["total"] + 1
    assert _csv_rows(after["invoices_csv"]) == _csv_rows(before["invoices_csv"]) + 1
    assert after["dues"]["total"] == before["dues"]["total"] + 1
    assert after["dues_ageing"]["total_invoice_count"] == before["dues_ageing"]["total_invoice_count"] + 1
    assert after["dues_ageing"]["total_remaining"] == pytest.approx(before["dues_ageing"]["total_remaining"] + total)
    assert len(after["unpaid"]) == len(before["unpaid"]) + 1

    # Ledger and Day Book.
    assert len(after["day_book"]["entries"]) == len(before["day_book"]["entries"]) + 1
    assert after["day_book"]["total_debit"] == pytest.approx(before["day_book"]["total_debit"] + total)
    assert _csv_rows(after["day_book_csv"]) == _csv_rows(before["day_book_csv"]) + 1
    assert len(after["statement"]["entries"]) == len(before["statement"]["entries"]) + 1
    assert after["statement"]["period_debit"] == pytest.approx(before["statement"]["period_debit"] + total)
    assert after["statement"]["closing_balance"] == pytest.approx(before["statement"]["closing_balance"] + total)

    # Tax ledger and GSTR-1.
    assert len(after["tax_ledger"]["entries"]) > len(before["tax_ledger"]["entries"])
    new_tax_entries = after["tax_ledger"]["entries"][:]
    for entry in before["tax_ledger"]["entries"]:
        new_tax_entries.remove(entry)
    assert {entry["reference_number"] for entry in new_tax_entries} == {invoice["invoice_number"]}
    summary_before, summary_after = before["gstr1_summary"], after["gstr1_summary"]
    assert summary_after["b2b"]["invoice_count"] == summary_before["b2b"]["invoice_count"] + 1
    assert summary_after["b2b"]["taxable_value"] == pytest.approx(summary_before["b2b"]["taxable_value"] + taxable)
    assert invoice["invoice_number"] in json.dumps(after["gstr1_json"])
    assert invoice["invoice_number"] not in json.dumps(before["gstr1_json"])

    # Dashboard and analytics.
    sales_before, sales_after = before["dashboard"]["sales"], after["dashboard"]["sales"]
    assert sales_after["sales_invoice_count"] == sales_before["sales_invoice_count"] + 1
    assert sales_after["total_sales"] == pytest.approx(sales_before["total_sales"] + total)
    assert after["dashboard"]["receivables"]["outstanding_amount"] == pytest.approx(
        before["dashboard"]["receivables"]["outstanding_amount"] + total
    )
    assert after["sales_by_month"]["totals"]["invoice_count"] == before["sales_by_month"]["totals"]["invoice_count"] + 1
    assert after["sales_by_month"]["totals"]["gst_collected"] == pytest.approx(before["sales_by_month"]["totals"]["gst_collected"] + tax)
    product_row = lambda report: next(row for row in report["rows"] if row["product_id"] == product)  # noqa: E731
    assert product_row(after["sales_by_product"])["quantity_sold"] == product_row(before["sales_by_product"])["quantity_sold"] + 3
    assert after["profit_loss"]["totals"]["revenue"] == pytest.approx(before["profit_loss"]["totals"]["revenue"] + taxable)

    # Numbers: one from the sales series, none from anything else.
    series_after = series_counters(client)
    assert series_after["sales"] == series_before["sales"] + 1
    for key in series_before:
        if key != "sales":
            assert series_after[key] == series_before[key], key

    # Money: the invoice arrives with nothing paid and nothing copied.
    assert invoice["paid_amount"] == 0 and invoice["payment_status"] == "unpaid"
    assert after["payments"] == before["payments"]
    assert after["credit_notes"] == before["credit_notes"]

    # Only this quotation closed.
    for key, quote in quotes.items():
        assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == other_quotes_before[key]


def test_a_failed_conversion_changes_nothing_at_all(client, world, db_session):
    quote = ok(client.post("/api/quotations/", json={
        "ledger_id": world["ledger"]["id"],
        "items": [
            {"product_id": world["product"]["id"], "quantity": 2, "unit_price": 100},
            {"product_id": world["tracked"]["id"], "quantity": 1, "unit_price": 500},
        ],
    }))
    addresses = db_session.query(LedgerAddress).count()
    links = db_session.query(ShareLink).count()
    before = _snapshot(client, world)
    series_before = series_counters(client)
    rows_before = _rows(db_session, world)

    # The tracked line has no serial, so the invoice path refuses it after the number
    # and the first line's stock have been dealt with.
    assert convert(client, quote["id"]).status_code == 400

    _assert_same(before, _snapshot(client, world))
    _assert_same(rows_before, _rows(db_session, world))
    assert series_counters(client) == series_before
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "open"
    assert db_session.query(LedgerAddress).count() == addresses
    assert db_session.query(ShareLink).count() == links


def test_cancelling_the_invoice_puts_every_figure_back(client, world, db_session):
    quote = ok(client.post("/api/quotations/", json={
        "ledger_id": world["ledger"]["id"],
        "items": [{"product_id": world["product"]["id"], "quantity": 2, "unit_price": 100}],
    }))
    stock_before = _rows(db_session, world)["stock"]
    tax_before = ok(client.get("/api/ledgers/tax-ledger/", params=_period()))
    invoice = ok(convert(client, quote["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))

    assert _rows(db_session, world)["stock"] == stock_before
    assert ok(client.get("/api/ledgers/tax-ledger/", params=_period()))["entries"] == tax_before["entries"]
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "open"


# ---------------------------------------------------------------------------
# Structural guards
# ---------------------------------------------------------------------------

def test_invoice_list_reads_quotation_numbers_in_one_query(client, world, db_session):
    """Reading source_quotation_number off each row must not query once per invoice."""
    from sqlalchemy import event

    engine = db_session.get_bind()

    for _ in range(3):
        quote = ok(client.post("/api/quotations/", json={
            "ledger_id": world["ledger"]["id"],
            "items": [{"product_id": world["product"]["id"], "quantity": 1, "unit_price": 100}],
        }))
        invoice = ok(convert(client, quote["id"]))
        assert invoice["source_quotation_number"] == quote["quotation_number"]

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        listed = ok(client.get("/api/invoices/", params={"page_size": 100}))
    finally:
        event.remove(engine, "before_cursor_execute", record)

    numbers = [row["source_quotation_number"] for row in listed["items"] if row["source_quotation_number"]]
    assert len(numbers) == 3
    quotation_selects = [s for s in statements if "FROM quotations" in s]
    assert len(quotation_selects) == 1, quotation_selects
    assert "company_logo_data" not in quotation_selects[0]


def test_invoice_voucher_type_still_only_allows_sales_and_purchase():
    from typing import get_args

    from src.schemas.invoice import InvoiceCreate

    assert set(get_args(InvoiceCreate.model_fields["voucher_type"].annotation)) == {"sales", "purchase"}


# Deliberately short. A report or a posting path importing the quotation model has to
# add itself here, in a diff somebody reviews: nothing that computes money should.
ALLOWED_QUOTATION_IMPORTERS = {
    "src/models/__init__.py",
    "src/models/quotation.py",
    "src/schemas/quotation.py",
    "src/api/routes/quotations.py",
    "src/api/routes/products.py",  # delete guard
    "src/api/routes/ledgers.py",  # delete guard
    "src/api/routes/share.py",
    "src/api/routes/invoices.py",  # cancel and restore hooks
    "src/services/quotation.py",
    "src/services/series.py",  # _number_taken
    "src/services/share_documents.py",
    "src/services/pdf_templates/quotation_template.py",
}


def test_only_the_expected_modules_know_about_quotations():
    importers = set()
    for path in (BACKEND_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in ("src.models.quotation", "src.services.quotation", "src.schemas.quotation"):
                importers.add(str(path.relative_to(BACKEND_ROOT)))
    assert importers <= ALLOWED_QUOTATION_IMPORTERS, importers - ALLOWED_QUOTATION_IMPORTERS
