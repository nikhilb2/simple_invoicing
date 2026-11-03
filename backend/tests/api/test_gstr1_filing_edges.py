"""GSTR-1 export and validation at the edges of what a file can report."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.api.routes.ledgers import _note_section
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNoteItem
from src.models.financial_year import FinancialYear
from src.models.invoice import Invoice, InvoiceItem
from src.models.invoice_series import InvoiceSeries
from src.services.gst_tax_service import india_today
from tests.api.test_place_of_supply import MAHARASHTRA_BUYER, _ledger_with_gst, _note_payload
from tests.api.test_product_performance import _create_ledger, _create_product, _line

HOME = "29AAAAA0000A1Z5"


@pytest.fixture
def seller(client, db_session):
    assert client.get("/api/company/").status_code == 200
    company = db_session.query(CompanyProfile).first()
    company.gst = HOME
    db_session.commit()
    return company


def _last_month_end():
    return india_today().replace(day=1) - timedelta(days=1)


def _period():
    """Last month, so an invoice and its note can both sit inside a closed period."""
    last = _last_month_end()
    return {"from_date": last.replace(day=1).isoformat(), "to_date": last.isoformat()}


def _in_period():
    return _last_month_end().replace(day=5).isoformat()


def _sale(client, ledger, product, items=None, **extra):
    response = client.post("/api/invoices/", json={
        "voucher_type": "sales",
        "ledger_id": ledger,
        "invoice_date": _in_period(),
        "items": items or [_line(product, 1, 1000)],
        **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _note(client, invoices, **extra):
    response = client.post("/api/credit-notes/", json=_note_payload(invoices, credit_note_date=_in_period(), **extra))
    assert response.status_code == 201, response.text
    return response.json()


def _move_out_of_period(db_session, invoice):
    """The sale fell in the month before, so this period has only the note."""
    db_session.get(Invoice, invoice["id"]).invoice_date -= timedelta(days=40)
    db_session.commit()


def _export(client):
    response = client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=_period())
    assert response.status_code == 200, response.text
    return json.loads(response.content)


def _validate(client):
    return client.get("/api/ledgers/tax-ledger/gstr1/validate", params=_period()).json()


def _summary(client):
    return client.get("/api/ledgers/tax-ledger/gstr1/summary", params=_period()).json()


def _by_field(result, field):
    return [e for e in result["errors"] if e["field"] == field]


# ── 0% sales ───────────────────────────────────────────────────────────────────


def test_zero_rate_sales_warn_with_their_count_and_value_and_still_file_at_rate_0(client, seller):
    milk = _create_product(client, "S-0", "Milk", hsn_sac="0401")
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    walk_in = _create_ledger(client, "Walk-in")
    buyer = _ledger_with_gst(client, "Buyer", MAHARASHTRA_BUYER)
    _sale(client, walk_in, milk, items=[_line(milk, 1, 1000, gst_rate=0)])
    _sale(client, buyer, milk, items=[_line(milk, 1, 2500.5, gst_rate=0), _line(widget, 1, 100)])
    _sale(client, walk_in, widget)

    result = _validate(client)
    warnings = _by_field(result, "0% sales")

    assert result["status"] == "valid"
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "warning"
    assert "2 invoice(s)" in warnings[0]["message"]
    assert "3,500.50" in warnings[0]["message"]
    assert "Table 8" in warnings[0]["message"]

    data = _export(client)
    assert {row["rt"] for row in data["b2cs"]} == {0.0, 18.0}
    assert [itm["itm_det"]["rt"] for itm in data["b2b"][0]["inv"][0]["itms"]] == [0.0, 18.0]

    summary = _summary(client)
    assert (summary["zero_rate_invoices"], summary["zero_rate_value"]) == (2, 3500.5)


def test_no_zero_rate_warning_without_zero_rate_sales(client, seller):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    _sale(client, _create_ledger(client, "Walk-in"), widget)

    assert _by_field(_validate(client), "0% sales") == []
    assert _summary(client)["zero_rate_invoices"] == 0


# ── All-zero and negative rows ─────────────────────────────────────────────────


def test_a_sale_fully_returned_in_its_period_leaves_no_rows(client, seller):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    gadget = _create_product(client, "S-2", "Gadget", hsn_sac="8473")
    walk_in = _create_ledger(client, "Walk-in")
    sold = _sale(client, walk_in, widget)
    _sale(client, walk_in, gadget, items=[_line(gadget, 1, 500, gst_rate=5)])
    _note(client, [sold])

    data = _export(client)

    assert [row["rt"] for row in data["b2cs"]] == [5.0]
    assert [(row["hsn_sc"], row["num"]) for row in data["hsn"]["hsn_b2c"]] == [("8473", 1)]
    assert _by_field(_validate(client), "B2CS") == []


def test_a_period_with_only_cancelling_rows_drops_the_sections(client, seller):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    _note(client, [_sale(client, _create_ledger(client, "Walk-in"), widget)])

    data = _export(client)

    assert "b2cs" not in data
    assert "hsn" not in data
    assert data["doc_issue"]["doc_det"]


def test_negative_rows_warn_without_blocking(client, seller, db_session):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    sold = _sale(client, _create_ledger(client, "Walk-in"), widget)
    _note(client, [sold])
    _move_out_of_period(db_session, sold)

    result = _validate(client)

    assert result["status"] == "valid"
    b2cs = _by_field(result, "B2CS")
    hsn = _by_field(result, "HSN summary")
    assert len(b2cs) == 1 and b2cs[0]["severity"] == "warning" and "-1000.00" in b2cs[0]["message"]
    assert len(hsn) == 1 and hsn[0]["severity"] == "warning" and "8471" in hsn[0]["message"]

    data = _export(client)
    assert data["b2cs"][0]["txval"] == -1000.0
    assert data["hsn"]["hsn_b2c"][0]["qty"] == -1.0


# ── A note on an old invoice with bad data ─────────────────────────────────────


def test_a_note_on_a_line_with_no_hsn_says_how_to_fix_it(client, seller, db_session):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    sold = _sale(client, _create_ledger(client, "Walk-in"), widget)
    note = _note(client, [sold])
    db_session.get(InvoiceItem, sold["items"][0]["id"]).hsn_sac = None
    _move_out_of_period(db_session, sold)

    response = client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=_period())

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert f"Cancel credit note {note['credit_note_number']}" in detail
    assert f"edit {sold['invoice_number']} to correct the HSN" in detail
    assert "raise the note again" in detail
    errors = [e for e in _validate(client)["errors"] if e["invoice_number"] == note["credit_note_number"]]
    assert "Cancel credit note" in errors[0]["message"]


def test_a_note_on_a_line_with_a_bad_rate_says_how_to_fix_it(client, seller, db_session):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    sold = _sale(client, _create_ledger(client, "Walk-in"), widget)
    note = _note(client, [sold])
    db_session.get(CreditNoteItem, note["items"][0]["id"]).gst_rate = 17.99
    _move_out_of_period(db_session, sold)

    response = client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=_period())

    assert response.status_code == 400
    assert "17.99% is not a GST rate" in response.json()["detail"]
    assert "to correct the rate" in response.json()["detail"]


# ── A zero-value invoice ───────────────────────────────────────────────────────


def _free_line(product):
    return {**_line(product, 2, 500), "discount_type": "percentage", "discount_value": 100}


def test_a_100_percent_discount_invoice_warns_and_reaches_only_table_13(client, seller):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    buyer = _ledger_with_gst(client, "Buyer", MAHARASHTRA_BUYER)
    free = _sale(client, buyer, widget, items=[_free_line(widget)])
    paid = _sale(client, _create_ledger(client, "Walk-in"), widget)

    result = _validate(client)
    warning = [e for e in result["errors"] if e["invoice_number"] == free["invoice_number"]]

    assert result["status"] == "valid"
    assert [(e["field"], e["severity"]) for e in warning] == [("Taxable Value", "warning")]
    assert "Table 13" in warning[0]["message"]

    data = _export(client)
    assert "b2b" not in data
    assert data["b2cs"][0]["txval"] == 1000.0
    assert data["hsn"]["hsn_b2c"][0]["qty"] == 1.0
    assert "hsn_b2b" not in data["hsn"]
    docs = data["doc_issue"]["doc_det"][0]["docs"]
    assert sum(row["totnum"] for row in docs) == 2
    assert {free["invoice_number"], paid["invoice_number"]} == {docs[0]["from"], docs[0]["to"]}

    summary = _summary(client)
    assert summary["b2b"]["invoice_count"] == 0
    assert summary["doc_summary"]["total_invoices"] == 2
    assert [(row["hsn_code"], row["quantity"]) for row in summary["hsn_summary"]] == [("8471", 1)]


def test_a_zero_value_invoice_with_no_hsn_does_not_block_the_month(client, seller, db_session):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    free = _sale(client, _create_ledger(client, "Walk-in"), widget, items=[_free_line(widget)])
    db_session.get(InvoiceItem, free["items"][0]["id"]).hsn_sac = None
    db_session.commit()

    assert _validate(client)["status"] == "valid"
    assert "b2cs" not in _export(client)


def test_zero_taxable_with_a_total_is_still_an_error(client, seller, db_session):
    """Only an invoice that charges nothing at all is a real zero-value one."""
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    sold = _sale(client, _create_ledger(client, "Walk-in"), widget)
    db_session.get(Invoice, sold["id"]).taxable_amount = 0
    db_session.commit()

    assert _validate(client)["status"] == "invalid"
    response = client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=_period())
    assert response.status_code == 400
    assert "Missing or zero taxable value" in response.json()["detail"]


def test_a_return_against_a_zero_value_invoice_reaches_only_table_13(client, seller):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    buyer = _ledger_with_gst(client, "Buyer", MAHARASHTRA_BUYER)
    free = _sale(client, buyer, widget, items=[_free_line(widget)])

    note = _note(client, [free])

    assert note["total_amount"] == 0
    data = _export(client)
    assert "cdnr" not in data
    assert "hsn" not in data
    assert [row["doc_num"] for row in data["doc_issue"]["doc_det"]] == [1, 5]
    assert _by_field(_validate(client), "HSN summary") == []


def test_csv_labels_a_zero_value_invoice(client, seller):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    _sale(client, _create_ledger(client, "Walk-in"), widget, items=[_free_line(widget)])

    response = client.get("/api/ledgers/tax-ledger/gstr1/export-csv", params=_period())

    assert "Table 13 only" in response.content.decode("utf-8-sig")


# ── Which table a note goes in ─────────────────────────────────────────────────


def test_a_note_across_small_interstate_invoices_stays_in_b2cs(client, seller):
    machine = _create_product(client, "S-1", "Machine", price=60000, hsn_sac="8471")
    walk_in = _create_ledger(client, "Walk-in")
    invoices = [
        _sale(client, walk_in, machine, items=[_line(machine, 1, 50000)], place_of_supply="10")
        for _ in range(2)
    ]

    note = _note(client, invoices)

    assert note["total_amount"] > 100000
    data = _export(client)
    assert "cdnur" not in data
    assert "b2cs" not in data  # The sales and the note net to nothing.


def _invoice_of(total):
    return Invoice(id=1, ledger_gst=None, place_of_supply="10", total_amount=total, company_gst=HOME)


def test_note_section_follows_its_invoices_rather_than_its_own_total():
    note = SimpleNamespace(items=[SimpleNamespace(invoice_id=1)], total_amount=118000, credit_note_date=None)

    assert _note_section(note, {1: _invoice_of(59000)}, "29")[0] == "B2CS"
    assert _note_section(note, {1: _invoice_of(118000)}, "29")[0] == "CDNUR"


def test_note_section_uses_its_own_total_only_when_its_invoice_is_gone():
    # Nothing says which state it was for, so it takes the seller's and stays B2CS.
    note = SimpleNamespace(items=[SimpleNamespace(invoice_id=None)], total_amount=150000, credit_note_date=None)

    assert _note_section(note, {}, "29") == ("B2CS", "", "29")


# ── A company with no GSTIN ────────────────────────────────────────────────────


def _span_b2b_and_b2c(client, db_session):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    ledger = _create_ledger(client, "Walk-in")
    before = _sale(client, ledger, widget)
    db_session.get(Buyer, ledger).gst = MAHARASHTRA_BUYER
    db_session.commit()
    return before, _sale(client, ledger, widget)


def test_no_gstin_company_can_span_what_would_be_two_tables(client, db_session):
    assert client.get("/api/company/").status_code == 200
    db_session.query(CompanyProfile).first().gst = None
    db_session.commit()
    before, after = _span_b2b_and_b2c(client, db_session)

    response = client.post("/api/credit-notes/", json=_note_payload([before, after]))

    assert response.status_code == 201, response.text


def test_a_company_with_a_gstin_still_cannot_span_two_tables(client, seller, db_session):
    before, after = _span_b2b_and_b2c(client, db_session)
    db_session.get(Invoice, after["id"]).place_of_supply = before["place_of_supply"]
    db_session.commit()

    response = client.post("/api/credit-notes/", json=_note_payload([before, after]))

    assert response.status_code == 400
    assert "different GSTR-1 tables" in response.json()["detail"]


# ── Number series ──────────────────────────────────────────────────────────────


def _active_year_with_series(client, db_session, label="2026-27", **format_overrides):
    start = int(label[:4])
    created = client.post(
        "/api/financial-years/",
        json={"label": label, "start_date": f"{start}-04-01", "end_date": f"{start + 1}-03-31"},
    )
    assert created.status_code == 201, created.text
    fy_id = created.json()["id"]
    db_session.query(FinancialYear).update({FinancialYear.is_active: False})
    db_session.get(FinancialYear, fy_id).is_active = True
    sales = None
    for series in db_session.query(InvoiceSeries).filter(InvoiceSeries.financial_year_id == fy_id):
        if series.voucher_type == "sales":
            sales = series
            series.year_format = "FY"
            series.include_year = True
            for key, value in format_overrides.items():
                setattr(series, key, value)
    db_session.commit()
    return fy_id, sales


def _sales_warning(client, fy_id):
    rows = client.get("/api/invoice-series/", params={"financial_year_id": fy_id}).json()
    return next(s["gstr1_warning"] for s in rows if s["voucher_type"] == "sales")


def test_rollover_accepts_a_series_that_fits_today(client, seller, db_session):
    _active_year_with_series(client, db_session, prefix="ABCD", pad_digits=3)

    response = client.post(
        "/api/financial-years/",
        json={"label": "2027-28", "start_date": "2027-04-01", "end_date": "2028-03-31"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["warnings"] == []
    assert _sales_warning(client, response.json()["id"]) is None


def test_settings_still_refuses_a_format_with_no_room_to_grow(client, seller, db_session):
    _, sales = _active_year_with_series(client, db_session, prefix="ABC", pad_digits=3)

    response = client.put(f"/api/invoice-series/{sales.id}", json={
        "prefix": "ABCD", "suffix": "", "include_year": True, "year_format": "FY", "separator": "-", "pad_digits": 3,
    })

    assert response.status_code == 400
    assert "GSTR-1" in response.json()["detail"]


@pytest.mark.parametrize("next_sequence,expected", [
    (1, None),
    (899, None),
    (900, "100 numbers left"),
    (999, "1 number left"),
    (1000, "will refuse"),
])
def test_settings_flags_a_series_nearing_the_limit(client, seller, db_session, next_sequence, expected):
    fy_id, _ = _active_year_with_series(client, db_session, prefix="ABCD", pad_digits=3, next_sequence=next_sequence)

    warning = _sales_warning(client, fy_id)

    if expected is None:
        assert warning is None
    else:
        assert expected in warning
        assert "ABCD-2026-27-" in warning


def test_settings_does_not_flag_a_series_with_a_spare_character(client, seller, db_session):
    fy_id, _ = _active_year_with_series(client, db_session, prefix="ABC", pad_digits=3, next_sequence=999)

    assert _sales_warning(client, fy_id) is None


def test_saving_a_series_returns_its_warning(client, seller, db_session):
    _, sales = _active_year_with_series(client, db_session, prefix="ABCD", pad_digits=3)

    response = client.put(f"/api/invoice-series/{sales.id}", json={
        "prefix": "ABCD", "suffix": "", "include_year": True, "year_format": "FY", "separator": "-", "pad_digits": 3,
        "next_sequence": 950,
    })

    assert response.status_code == 200, response.text
    assert "50 numbers left" in response.json()["gstr1_warning"]


def test_series_outside_gstr1_and_companies_with_no_gstin_are_not_flagged(client, seller, db_session):
    fy_id, _ = _active_year_with_series(client, db_session, prefix="ABCD", pad_digits=3, next_sequence=999)
    purchase = (
        db_session.query(InvoiceSeries)
        .filter(InvoiceSeries.financial_year_id == fy_id, InvoiceSeries.voucher_type == "purchase")
        .one()
    )
    purchase.prefix, purchase.year_format, purchase.pad_digits, purchase.next_sequence = "ABCD", "FY", 3, 999
    db_session.commit()

    rows = client.get("/api/invoice-series/", params={"financial_year_id": fy_id}).json()
    assert next(s for s in rows if s["voucher_type"] == "purchase")["gstr1_warning"] is None

    seller.gst = None
    db_session.commit()
    assert _sales_warning(client, fy_id) is None


def _hsn_errors(result):
    return [e for e in result["errors"] if e["field"].startswith("HSN (item")]


def test_a_well_formed_hsn_gst_does_not_list_fails_validation(client, seller):
    bad = _create_product(client, "S-1", "CPU", hsn_sac="84733000")
    sold = _sale(client, _create_ledger(client, "Walk-in"), bad)

    result = _validate(client)

    assert result["status"] == "invalid"
    [error] = _hsn_errors(result)
    assert error["invoice_number"] == sold["invoice_number"]
    assert error["severity"] == "error"
    assert "84733000 is not on GST's HSN/SAC list" in error["message"]
    assert "save this invoice again" in error["message"]


def test_a_malformed_hsn_is_only_reported_once(client, seller, db_session):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    sold = _sale(client, _create_ledger(client, "Walk-in"), widget)
    db_session.get(InvoiceItem, sold["items"][0]["id"]).hsn_sac = "99842"
    db_session.commit()

    [error] = _hsn_errors(_validate(client))

    assert "has 5 digits" in error["message"]


def test_an_hsn_gst_does_not_list_does_not_stop_the_export(client, seller):
    """Our copy of the master can lag GSTN's, so skipping validation has to stay possible."""
    bad = _create_product(client, "S-1", "CPU", hsn_sac="84733000")
    _sale(client, _create_ledger(client, "Walk-in"), bad)

    data = _export(client)

    assert [row["hsn_sc"] for row in data["hsn"]["hsn_b2c"]] == ["84733000"]


def test_fixing_the_product_and_saving_the_invoice_clears_the_error(client, seller):
    bad = _create_product(client, "S-1", "CPU", hsn_sac="84733000")
    ledger = _create_ledger(client, "Walk-in")
    sold = _sale(client, ledger, bad)

    product = client.get(f"/api/products/{bad}").json()
    fixed = {key: product[key] for key in ("sku", "name", "price", "gst_rate", "unit")}
    assert client.put(f"/api/products/{bad}", json={**fixed, "hsn_sac": "84733020"}).status_code == 200
    assert _hsn_errors(_validate(client))

    saved = client.put(f"/api/invoices/{sold['id']}", json={
        "voucher_type": "sales",
        "ledger_id": ledger,
        "invoice_date": _in_period(),
        "items": [_line(bad, 1, 1000)],
    })

    assert saved.status_code == 200, saved.text
    assert _hsn_errors(_validate(client)) == []


def test_a_note_on_a_line_gst_does_not_list_says_how_to_fix_it(client, seller, db_session):
    widget = _create_product(client, "S-1", "Widget", hsn_sac="8471")
    sold = _sale(client, _create_ledger(client, "Walk-in"), widget)
    note = _note(client, [sold])
    db_session.get(InvoiceItem, sold["items"][0]["id"]).hsn_sac = "84733000"
    _move_out_of_period(db_session, sold)

    [error] = [e for e in _hsn_errors(_validate(client)) if e["invoice_number"] == note["credit_note_number"]]

    assert "84733000 is not on GST's HSN/SAC list" in error["message"]
    assert f"edit {sold['invoice_number']} to correct the HSN" in error["message"]
    assert client.get("/api/ledgers/tax-ledger/gstr1/export-json", params=_period()).status_code == 200
