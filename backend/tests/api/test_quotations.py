"""Creating, editing and closing quotations and proforma invoices."""

import json
from datetime import date, timedelta

import pytest
from quotation_helpers import (
    GST_KA,
    convert,
    create_ledger,
    create_product,
    create_quotation,
    iso_today,
    ok,
    quotation_payload,
    seed_company,
    series_counters,
)

from src.models.invoice import Invoice
from src.models.ledger_address import LedgerAddress
from src.models.quotation import Quotation
from src.services import series as series_service
from src.services.gst_tax_service import india_today


@pytest.fixture
def setup(client):
    seed_company(client)
    return client, create_ledger(client), create_product(client)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("document_type, prefix", [("quotation", "QT-"), ("proforma", "PI-")])
def test_create_uses_its_own_series_and_defaults(setup, document_type, prefix):
    client, ledger, product = setup
    created = create_quotation(client, ledger["id"], product["id"], document_type=document_type)

    assert created["document_type"] == document_type
    assert created["quotation_number"].startswith(prefix)
    assert created["quotation_number"].endswith("-001")
    assert created["status"] == "open"
    assert created["display_status"] == "open"
    assert created["is_expired"] is False
    assert created["quotation_date"] == iso_today()
    assert created["valid_until"] == (india_today() + timedelta(days=30)).isoformat()
    assert created["ledger_name"] == ledger["name"]
    assert created["company_name"] == "Acme Traders"
    assert created["items"][0]["product_name"] == product["name"]
    assert created["items"][0]["hsn_sac"] == "84713010"


def test_the_two_documents_count_separately(setup):
    client, ledger, product = setup
    assert create_quotation(client, ledger["id"], product["id"])["quotation_number"].endswith("-001")
    assert create_quotation(client, ledger["id"], product["id"], document_type="proforma")["quotation_number"].endswith("-001")
    assert create_quotation(client, ledger["id"], product["id"])["quotation_number"].endswith("-002")


def test_validity_can_be_blank_or_set(setup):
    client, ledger, product = setup
    assert create_quotation(client, ledger["id"], product["id"], valid_until=None)["valid_until"] is None
    chosen = (date.today() + timedelta(days=7)).isoformat()
    assert create_quotation(client, ledger["id"], product["id"], valid_until=chosen)["valid_until"] == chosen


def test_validity_cannot_precede_the_date(setup):
    client, ledger, product = setup
    response = client.post("/api/quotations/", json=quotation_payload(
        ledger["id"], product["id"],
        quotation_date="2026-06-10",
        valid_until="2026-06-09",
    ))
    assert response.status_code == 422
    # Also when the date is left to default to today.
    response = client.post("/api/quotations/", json=quotation_payload(
        ledger["id"], product["id"],
        valid_until=(date.today() - timedelta(days=1)).isoformat(),
    ))
    assert response.status_code == 400


def test_a_quotation_cannot_be_posted_as_an_invoice_voucher(setup):
    client, ledger, product = setup
    for voucher_type in ("quotation", "proforma"):
        response = client.post("/api/invoices/", json={
            "ledger_id": ledger["id"],
            "voucher_type": voucher_type,
            "items": [{"product_id": product["id"], "quantity": 1}],
        })
        assert response.status_code == 422


def test_needs_a_line_and_a_catalogue_product(setup):
    client, ledger, product = setup
    empty = client.post("/api/quotations/", json={"ledger_id": ledger["id"], "items": []})
    assert empty.status_code == 400
    assert "Quotation must have" in empty.text
    unknown = client.post("/api/quotations/", json=quotation_payload(ledger["id"], 999999))
    assert unknown.status_code == 404
    no_free_text = client.post("/api/quotations/", json={
        "ledger_id": ledger["id"],
        "items": [{"description": "Just some text", "quantity": 1, "unit_price": 10}],
    })
    assert no_free_text.status_code == 422


@pytest.mark.parametrize("field, value", [
    ("quantity", "NaN"),
    ("quantity", "Infinity"),
    ("unit_price", "NaN"),
    ("discount_value", "Infinity"),
])
def test_a_number_that_is_not_a_number_is_refused(setup, field, value):
    client, ledger, product = setup
    line = {"product_id": product["id"], "quantity": 1, "unit_price": 100, "discount_type": "net", "discount_value": 1}
    body = json.dumps({"ledger_id": ledger["id"], "items": [{**line, field: "__VALUE__"}]}).replace('"__VALUE__"', value)
    response = client.post("/api/quotations/", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422


@pytest.mark.parametrize("field, value", [
    ("unit_price", 33.333),
    ("quantity", 1.2345),
    ("discount_value", 12.345),
])
def test_a_figure_more_precise_than_its_column_is_refused(setup, field, value):
    """It would be priced as sent, stored rounded, and convert to a different total."""
    client, ledger, product = setup
    decimal_product = create_product(client, "BULK-1", allow_decimal=True)
    line = {"product_id": decimal_product["id"], "quantity": 1, "unit_price": 100, "discount_type": "net", "discount_value": 1}
    response = client.post("/api/quotations/", json={"ledger_id": ledger["id"], "items": [{**line, field: value}]})
    assert response.status_code == 422
    assert "decimal places" in response.text


def test_the_most_precise_figures_allowed_convert_to_the_same_total(setup):
    client, ledger, _ = setup
    decimal_product = create_product(client, "BULK-2", allow_decimal=True)
    quote = ok(client.post("/api/quotations/", json={
        "ledger_id": ledger["id"],
        "items": [{"product_id": decimal_product["id"], "quantity": 2.125, "unit_price": 33.33, "discount_type": "percentage", "discount_value": 12.34}],
    }))
    assert ok(convert(client, quote["id"]))["total_amount"] == quote["total_amount"]


def test_whole_number_rule_applies(setup):
    client, ledger, product = setup
    response = client.post("/api/quotations/", json=quotation_payload(ledger["id"], product["id"], quantity=1.5))
    assert response.status_code == 400
    assert "whole number" in response.text


def test_serial_tracked_product_needs_no_serials_but_must_be_convertible_as_written(setup):
    client, ledger, _ = setup
    tracked = create_product(client, "PHONE-1", track_serials=True, initial_quantity=0)

    created = create_quotation(client, ledger["id"], tracked["id"], quantity=2)
    assert "serial_numbers" not in created["items"][0]

    two_lines = client.post("/api/quotations/", json={
        "ledger_id": ledger["id"],
        "items": [
            {"product_id": tracked["id"], "quantity": 1},
            {"product_id": tracked["id"], "quantity": 1},
        ],
    })
    assert two_lines.status_code == 400
    assert "one line" in two_lines.text


def test_serials_are_not_accepted_on_a_line(setup):
    client, ledger, product = setup
    body = quotation_payload(ledger["id"], product["id"])
    body["items"][0]["serial_numbers"] = ["ABC"]
    created = ok(client.post("/api/quotations/", json=body))
    assert "serial_numbers" not in created["items"][0]


def test_totals_match_an_invoice_with_the_same_lines(setup):
    """The arithmetic is shared, so a discounted, rounded quote equals its invoice."""
    client, ledger, product = setup
    body = {
        "ledger_id": ledger["id"],
        "tax_inclusive": True,
        "apply_round_off": True,
        "discount_type": "percentage",
        "discount_value": 5,
        "items": [
            {"product_id": product["id"], "quantity": 3, "unit_price": 33.33, "discount_type": "percentage", "discount_value": 10},
            {"product_id": product["id"], "quantity": 1, "unit_price": 19.99, "discount_type": "net", "discount_value": 2},
        ],
    }
    quote = ok(client.post("/api/quotations/", json=body))
    invoice = ok(client.post("/api/invoices/", json={**body, "voucher_type": "sales"}))

    for field in ("taxable_amount", "total_tax_amount", "cgst_amount", "sgst_amount", "igst_amount", "round_off_amount", "total_amount"):
        assert quote[field] == invoice[field], field
    for quoted, invoiced in zip(quote["items"], invoice["items"]):
        for field in ("taxable_amount", "tax_amount", "cgst_amount", "sgst_amount", "igst_amount", "line_total"):
            assert quoted[field] == invoiced[field], field


def test_an_interstate_buyer_is_quoted_igst(setup):
    client, _, product = setup
    other_state = create_ledger(client, "Out of State", gst=GST_KA)
    quote = create_quotation(client, other_state["id"], product["id"])
    assert quote["igst_amount"] == 36 and quote["cgst_amount"] == 0 and quote["sgst_amount"] == 0


def test_series_prefix_is_editable_like_the_rest(setup):
    client, ledger, product = setup
    series = next(row for row in ok(client.get("/api/invoice-series/")) if row["voucher_type"] == "proforma")
    assert series["prefix"] == "PI"
    ok(client.put(f"/api/invoice-series/{series['id']}", json={
        "prefix": "PF", "suffix": "", "include_year": False, "year_format": "YYYY", "separator": "/", "pad_digits": 4,
    }))
    created = create_quotation(client, ledger["id"], product["id"], document_type="proforma")
    assert created["quotation_number"] == "PF/0001"


def test_fallback_number_is_not_invoice_styled(db_session):
    assert series_service.generate_next_number(db_session, "quotation", company_id=None).startswith("QT-")
    assert series_service.generate_next_number(db_session, "proforma", company_id=None).startswith("PI-")
    assert series_service.generate_next_number(db_session, "sales", company_id=None).startswith("INV-")


def test_number_lookup_checks_the_quotations_table(setup, db_session):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    assert series_service._number_taken(db_session, "quotation", quote["quotation_number"], None) is True
    assert series_service._number_taken(db_session, "sales", quote["quotation_number"], None) is False


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

def _update_body(ledger_id, product_id, **extra):
    body = {"ledger_id": ledger_id, "items": [{"product_id": product_id, "quantity": 5, "unit_price": 10}]}
    body.update(extra)
    return body


def test_edit_replaces_lines_and_keeps_the_number(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    updated = ok(client.put(f"/api/quotations/{quote['id']}", json=_update_body(ledger["id"], product["id"])))
    assert updated["quotation_number"] == quote["quotation_number"]
    assert len(updated["items"]) == 1
    assert updated["items"][0]["quantity"] == 5
    assert updated["taxable_amount"] == 50
    # Left out: validity unchanged. Null: cleared.
    assert updated["valid_until"] == quote["valid_until"]
    cleared = ok(client.put(f"/api/quotations/{quote['id']}", json=_update_body(ledger["id"], product["id"], valid_until=None)))
    assert cleared["valid_until"] is None


def test_financial_year_follows_the_date_on_edit(setup):
    client, ledger, product = setup
    today = date.today()
    later = ok(client.post("/api/financial-years/", json={
        "label": "LATER-FY",
        "start_date": date(today.year + 2, 1, 1).isoformat(),
        "end_date": date(today.year + 2, 12, 31).isoformat(),
    }), 201)
    quote = create_quotation(client, ledger["id"], product["id"], valid_until=None)
    assert quote["financial_year_id"] != later["id"]
    updated = ok(client.put(f"/api/quotations/{quote['id']}", json=_update_body(
        ledger["id"], product["id"], quotation_date=date(today.year + 2, 6, 1).isoformat(),
    )))
    assert updated["financial_year_id"] == later["id"]


def test_document_type_is_fixed_once_created(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    response = client.put(
        f"/api/quotations/{quote['id']}",
        json=_update_body(ledger["id"], product["id"], document_type="proforma"),
    )
    assert response.status_code == 422


def test_edit_does_not_consume_a_number(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    before = series_counters(client)
    ok(client.put(f"/api/quotations/{quote['id']}", json=_update_body(ledger["id"], product["id"])))
    assert series_counters(client) == before


@pytest.mark.parametrize("closing", ["cancel", "decline", "convert"])
def test_closed_documents_cannot_be_edited(setup, closing):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    if closing == "cancel":
        ok(client.post(f"/api/quotations/{quote['id']}/cancel"))
    elif closing == "decline":
        ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "declined"}))
    else:
        ok(convert(client, quote["id"]))
    response = client.put(f"/api/quotations/{quote['id']}", json=_update_body(ledger["id"], product["id"]))
    assert response.status_code == 400


def test_an_accepted_quote_can_still_be_edited(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "accepted"}))
    updated = ok(client.put(f"/api/quotations/{quote['id']}", json=_update_body(ledger["id"], product["id"])))
    assert updated["status"] == "accepted"


# ---------------------------------------------------------------------------
# Shipping
# ---------------------------------------------------------------------------

def _saved_address(client, ledger_id: int) -> dict:
    return ok(client.post(
        f"/api/ledgers/{ledger_id}/addresses/",
        json={"label": "Warehouse", "address": "9 Dock Road"},
    ), 201)


def test_saved_shipping_address_is_snapshotted_with_its_id(setup):
    client, ledger, product = setup
    address = _saved_address(client, ledger["id"])
    quote = create_quotation(
        client, ledger["id"], product["id"],
        shipping_address_same_as_billing=False,
        shipping_address_id=address["id"],
    )
    assert quote["shipping_address"] == "9 Dock Road"
    assert quote["shipping_address_label"] == "Warehouse"
    assert quote["shipping_address_id"] == address["id"]


def test_resaving_an_address_does_not_duplicate_it(setup, db_session):
    client, ledger, product = setup
    new_address = {"label": "Site A", "address": "7 Mill Lane"}
    quote = create_quotation(
        client, ledger["id"], product["id"],
        shipping_address_same_as_billing=False,
        new_shipping_address=new_address,
    )
    assert quote["shipping_address_id"] is not None
    ok(client.put(f"/api/quotations/{quote['id']}", json={
        **_update_body(ledger["id"], product["id"]),
        "shipping_address_same_as_billing": False,
        "new_shipping_address": new_address,
    }))
    assert db_session.query(LedgerAddress).filter(LedgerAddress.ledger_id == ledger["id"]).count() == 1


def test_conversion_reuses_the_saved_address_rather_than_adding_one(setup, db_session):
    """The trap: the invoice path inserts a row for anything in new_shipping_address."""
    client, ledger, product = setup
    address = _saved_address(client, ledger["id"])
    quote = create_quotation(
        client, ledger["id"], product["id"],
        shipping_address_same_as_billing=False,
        shipping_address_id=address["id"],
    )
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    assert draft["invoice"]["shipping_address_id"] == address["id"]
    assert draft["invoice"]["new_shipping_address"] is None
    assert draft["invoice"]["shipping_address_same_as_billing"] is False

    invoice = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"]))
    assert invoice["shipping_address"] == "9 Dock Road"
    assert db_session.query(LedgerAddress).filter(LedgerAddress.ledger_id == ledger["id"]).count() == 1


def test_conversion_warns_when_the_address_has_gone(setup, db_session):
    client, ledger, product = setup
    address = _saved_address(client, ledger["id"])
    quote = create_quotation(
        client, ledger["id"], product["id"],
        shipping_address_same_as_billing=False,
        shipping_address_id=address["id"],
    )
    # SQLite does not run ON DELETE SET NULL; on Postgres the id would already be null.
    db_session.query(LedgerAddress).filter(LedgerAddress.id == address["id"]).delete()
    db_session.commit()

    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    assert draft["invoice"]["shipping_address_same_as_billing"] is True
    assert draft["invoice"]["shipping_address_id"] is None
    assert "shipping_address_gone" in {w["code"] for w in draft["warnings"]}


def test_another_ledgers_address_is_refused(setup):
    client, ledger, product = setup
    other = create_ledger(client, "Other Buyer", gst="")
    address = _saved_address(client, other["id"])
    response = client.post("/api/quotations/", json=quotation_payload(
        ledger["id"], product["id"],
        shipping_address_same_as_billing=False,
        shipping_address_id=address["id"],
    ))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_status_moves(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    url = f"/api/quotations/{quote['id']}/status"

    accepted = ok(client.post(url, json={"status": "accepted", "note": "PO 123 by email"}))
    assert accepted["status"] == "accepted"
    assert accepted["status_note"] == "PO 123 by email"
    assert accepted["accepted_at"] is not None

    reopened = ok(client.post(url, json={"status": "open"}))
    assert reopened["status"] == "open" and reopened["accepted_at"] is None

    declined = ok(client.post(url, json={"status": "declined", "note": "Too dear"}))
    assert declined["status"] == "declined" and declined["declined_at"] is not None

    assert ok(client.post(url, json={"status": "open"}))["declined_at"] is None


@pytest.mark.parametrize("start, target", [
    ("open", "open"),
    ("accepted", "declined"),
    ("declined", "accepted"),
    ("cancelled", "open"),
])
def test_illegal_moves_are_refused(setup, start, target):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    if start == "cancelled":
        ok(client.post(f"/api/quotations/{quote['id']}/cancel"))
    elif start != "open":
        ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": start}))
    assert client.post(f"/api/quotations/{quote['id']}/status", json={"status": target}).status_code == 400


@pytest.mark.parametrize("target", ["converted", "cancelled", "expired", "draft"])
def test_status_route_only_takes_the_manual_statuses(setup, target):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    assert client.post(f"/api/quotations/{quote['id']}/status", json={"status": target}).status_code == 422


def test_expired_is_derived_and_not_stored(setup, db_session):
    client, ledger, product = setup
    past = date.today() - timedelta(days=40)
    quote = create_quotation(
        client, ledger["id"], product["id"],
        quotation_date=past.isoformat(),
        valid_until=(past + timedelta(days=30)).isoformat(),
    )
    assert quote["status"] == "open"
    assert quote["is_expired"] is True
    assert quote["display_status"] == "expired"
    assert db_session.query(Quotation).filter(Quotation.id == quote["id"]).one().status == "open"


def test_valid_through_the_last_day(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], valid_until=iso_today())
    assert quote["is_expired"] is False


def test_a_blank_validity_never_expires(setup):
    client, ledger, product = setup
    quote = create_quotation(
        client, ledger["id"], product["id"],
        quotation_date=(date.today() - timedelta(days=400)).isoformat(),
        valid_until=None,
    )
    assert quote["is_expired"] is False


def test_only_a_live_document_can_expire(setup):
    client, ledger, product = setup
    past = date.today() - timedelta(days=40)
    quote = create_quotation(
        client, ledger["id"], product["id"],
        quotation_date=past.isoformat(),
        valid_until=(past + timedelta(days=30)).isoformat(),
    )
    declined = ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "declined"}))
    assert declined["is_expired"] is False and declined["display_status"] == "declined"


# ---------------------------------------------------------------------------
# Cancel and duplicate
# ---------------------------------------------------------------------------

def test_cancel_keeps_the_number(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    cancelled = ok(client.post(f"/api/quotations/{quote['id']}/cancel"))
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_at"] is not None
    assert cancelled["quotation_number"] == quote["quotation_number"]
    assert client.post(f"/api/quotations/{quote['id']}/cancel").status_code == 400
    # The next one moves on rather than reusing it.
    assert create_quotation(client, ledger["id"], product["id"])["quotation_number"].endswith("-002")


def test_cancel_is_refused_while_an_invoice_is_live(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(convert(client, quote["id"]))
    assert client.post(f"/api/quotations/{quote['id']}/cancel").status_code == 400


def test_duplicate_is_fresh_and_open(setup):
    client, ledger, product = setup
    past = date.today() - timedelta(days=40)
    quote = create_quotation(
        client, ledger["id"], product["id"],
        document_type="proforma",
        quotation_date=past.isoformat(),
        valid_until=(past + timedelta(days=14)).isoformat(),
        reference_notes="Tender 9",
    )
    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "declined"}))

    copy = ok(client.post(f"/api/quotations/{quote['id']}/duplicate"))
    assert copy["id"] != quote["id"]
    assert copy["quotation_number"] != quote["quotation_number"]
    assert copy["quotation_number"].startswith("PI-")
    assert copy["document_type"] == "proforma"
    assert copy["status"] == "open"
    assert copy["quotation_date"] == iso_today()
    assert copy["valid_until"] == (india_today() + timedelta(days=14)).isoformat()
    assert copy["reference_notes"] == "Tender 9"
    assert copy["total_amount"] == quote["total_amount"]
    assert copy["invoices"] == []


def test_duplicate_keeps_a_shipping_address_whose_saved_row_has_gone(setup, db_session):
    client, ledger, product = setup
    address = _saved_address(client, ledger["id"])
    quote = create_quotation(
        client, ledger["id"], product["id"],
        shipping_address_same_as_billing=False,
        shipping_address_id=address["id"],
    )
    row = db_session.query(Quotation).filter(Quotation.id == quote["id"]).one()
    row.shipping_address_id = None  # What ON DELETE SET NULL leaves on Postgres.
    db_session.query(LedgerAddress).filter(LedgerAddress.id == address["id"]).delete()
    db_session.commit()

    copy = ok(client.post(f"/api/quotations/{quote['id']}/duplicate"))
    assert copy["shipping_address"] == "9 Dock Road"
    assert copy["shipping_address_label"] == "Warehouse"


def test_duplicate_uses_todays_tax_rate(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(client.put(f"/api/products/{product['id']}", json={**product, "gst_rate": 5}))
    copy = ok(client.post(f"/api/quotations/{quote['id']}/duplicate"))
    assert copy["items"][0]["gst_rate"] == 5


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_filters_and_counts(setup):
    client, ledger, product = setup
    other = create_ledger(client, "Second Buyer", gst="")
    open_quote = create_quotation(client, ledger["id"], product["id"])
    proforma = create_quotation(client, other["id"], product["id"], document_type="proforma")
    past = date.today() - timedelta(days=40)
    expired = create_quotation(
        client, ledger["id"], product["id"],
        quotation_date=past.isoformat(),
        valid_until=(past + timedelta(days=30)).isoformat(),
    )
    accepted = create_quotation(client, ledger["id"], product["id"])
    ok(client.post(f"/api/quotations/{accepted['id']}/status", json={"status": "accepted"}))

    def ids(**params):
        return {row["id"] for row in ok(client.get("/api/quotations/", params=params))["items"]}

    everything = ok(client.get("/api/quotations/"))
    assert everything["total"] == 4
    assert everything["status_counts"] == {"open": 2, "accepted": 1, "expired": 1}

    assert ids(status="open") == {open_quote["id"], proforma["id"]}
    assert ids(status="expired") == {expired["id"]}
    assert ids(status="accepted") == {accepted["id"]}
    assert ids(document_type="proforma") == {proforma["id"]}
    assert ids(ledger_id=other["id"]) == {proforma["id"]}
    assert ids(search=proforma["quotation_number"]) == {proforma["id"]}
    assert ids(search="second buyer") == {proforma["id"]}
    assert ids(date_to=past.isoformat()) == {expired["id"]}
    assert ids(date_from=iso_today()) == {open_quote["id"], proforma["id"], accepted["id"]}


def test_list_names_the_live_invoice_and_keeps_the_history(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    first = ok(convert(client, quote["id"]))

    row = ok(client.get("/api/quotations/", params={"status": "converted"}))["items"][0]
    assert row["converted_invoice_id"] == first["id"]
    assert row["converted_invoice_number"] == first["invoice_number"]

    ok(client.delete(f"/api/invoices/{first['id']}"))
    detail = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert detail["converted_invoice_id"] is None
    assert detail["invoices"] == [{"id": first["id"], "invoice_number": first["invoice_number"], "status": "cancelled"}]


def test_unknown_id_is_not_found(setup):
    client, ledger, product = setup
    assert client.get("/api/quotations/999").status_code == 404
    assert client.put("/api/quotations/999", json=_update_body(ledger["id"], product["id"])).status_code == 404
    assert client.post("/api/quotations/999/status", json={"status": "accepted"}).status_code == 404
    assert client.post("/api/quotations/999/cancel").status_code == 404
    assert client.post("/api/quotations/999/duplicate").status_code == 404
    assert client.get("/api/quotations/999/pdf").status_code == 404
    assert client.get("/api/quotations/999/conversion-draft").status_code == 404
    assert client.post("/api/quotations/999/convert", json={"ledger_id": ledger["id"], "items": []}).status_code == 404


# ---------------------------------------------------------------------------
# Delete guards
# ---------------------------------------------------------------------------

def test_a_quoted_product_cannot_be_deleted(setup):
    client, ledger, product = setup
    create_quotation(client, ledger["id"], product["id"])
    response = client.delete(f"/api/products/{product['id']}")
    assert response.status_code == 400
    assert "quotations" in response.text


def test_a_quoted_ledger_cannot_be_deleted(setup):
    client, ledger, product = setup
    create_quotation(client, ledger["id"], product["id"])
    response = client.delete(f"/api/ledgers/{ledger['id']}")
    assert response.status_code == 400
    assert "quotations" in response.text


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def _stock(client, product_id: int) -> float:
    rows = ok(client.get("/api/inventory/", params={"page_size": 500}))["items"]
    return next(row["quantity"] for row in rows if row["product_id"] == product_id)


def test_conversion_creates_one_linked_invoice_and_closes_the_quote(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], quantity=3)
    before = series_counters(client)

    invoice = ok(convert(client, quote["id"]))

    assert invoice["voucher_type"] == "sales"
    assert invoice["invoice_number"].startswith("INV-")
    assert invoice["source_quotation_id"] == quote["id"]
    assert invoice["source_quotation_number"] == quote["quotation_number"]
    assert invoice["reference_notes"] == f"Against quotation {quote['quotation_number']}"
    assert invoice["total_amount"] == quote["total_amount"]
    assert invoice["paid_amount"] == 0
    assert _stock(client, product["id"]) == 97

    after = series_counters(client)
    assert after["sales"] == before["sales"] + 1
    assert after["quotation"] == before["quotation"]

    detail = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert detail["status"] == "converted"
    assert detail["converted_at"] is not None
    assert detail["converted_invoice_id"] == invoice["id"]


@pytest.mark.parametrize("body", [
    {"tax_inclusive": False, "apply_round_off": False},
    {"tax_inclusive": True, "apply_round_off": False},
    {"tax_inclusive": False, "apply_round_off": True},
    {"tax_inclusive": False, "apply_round_off": True, "discount_type": "percentage", "discount_value": 7.5},
    {"tax_inclusive": True, "apply_round_off": True, "discount_type": "net", "discount_value": 11},
])
@pytest.mark.parametrize("buyer_gst", ["same", "other"])
def test_an_unchanged_quote_converts_to_identical_figures(setup, body, buyer_gst):
    client, ledger, product = setup
    buyer = ledger if buyer_gst == "same" else create_ledger(client, "Out of State", gst=GST_KA)
    quote = ok(client.post("/api/quotations/", json={
        "ledger_id": buyer["id"],
        "items": [
            {"product_id": product["id"], "quantity": 3, "unit_price": 33.33, "discount_type": "percentage", "discount_value": 10},
            {"product_id": product["id"], "quantity": 1, "unit_price": 19.99},
        ],
        **body,
    }))
    invoice = ok(convert(client, quote["id"]))
    for field in ("taxable_amount", "total_tax_amount", "cgst_amount", "sgst_amount", "igst_amount", "round_off_amount", "total_amount"):
        assert invoice[field] == quote[field], field


def test_edits_in_the_composer_are_what_gets_invoiced(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], quantity=3)
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    draft["items"][0]["quantity"] = 1
    draft["items"][0]["unit_price"] = 80
    draft["reference_notes"] = "PO 42"
    invoice = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft))
    assert invoice["items"][0]["quantity"] == 1
    assert invoice["items"][0]["unit_price"] == 80
    assert invoice["reference_notes"] == "PO 42"
    assert _stock(client, product["id"]) == 99
    # Full conversion only: the rest is not left open.
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "converted"


def test_the_invoice_can_go_to_another_buyer(setup):
    client, ledger, product = setup
    firm = create_ledger(client, "Their Firm", gst="")
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"], ledger_id=firm["id"]))
    assert invoice["ledger_id"] == firm["id"]
    assert invoice["source_quotation_id"] == quote["id"]


def test_only_a_sales_invoice_can_come_of_it(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    response = convert(client, quote["id"], voucher_type="purchase")
    assert response.status_code == 400
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "open"


def test_second_conversion_gets_409_with_the_existing_invoice(setup, db_session):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    first = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft))

    second = client.post(f"/api/quotations/{quote['id']}/convert", json=draft)
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "quotation_already_converted"
    assert detail["invoice_id"] == first["id"]
    assert detail["invoice_number"] == first["invoice_number"]
    assert first["invoice_number"] in detail["message"]

    assert db_session.query(Invoice).filter(Invoice.source_quotation_id == quote["id"]).count() == 1
    assert _stock(client, product["id"]) == 98
    # The draft says the same, so a stale tab finds out on opening.
    assert client.get(f"/api/quotations/{quote['id']}/conversion-draft").status_code == 409


def test_declined_must_be_reopened_first(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "declined"}))

    response = client.post(f"/api/quotations/{quote['id']}/convert", json=draft)
    assert response.status_code == 400
    assert "Reopen" in response.text
    assert client.get(f"/api/quotations/{quote['id']}/conversion-draft").status_code == 400

    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "open"}))
    ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft))


def test_cancelled_cannot_convert(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["invoice"]
    ok(client.post(f"/api/quotations/{quote['id']}/cancel"))
    response = client.post(f"/api/quotations/{quote['id']}/convert", json=draft)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "quotation_cancelled"


def test_expired_converts_with_a_warning(setup):
    client, ledger, product = setup
    past = date.today() - timedelta(days=40)
    quote = create_quotation(
        client, ledger["id"], product["id"],
        quotation_date=past.isoformat(),
        valid_until=(past + timedelta(days=30)).isoformat(),
    )
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    assert "expired" in {w["code"] for w in draft["warnings"]}
    ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"]))


def test_an_unchanged_quote_has_no_warnings(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    assert ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))["warnings"] == []


@pytest.mark.parametrize("tax_inclusive, expected", [
    (False, "the total changes"),
    (True, "the taxable value changes and the total stays the same"),
])
def test_rate_change_uses_the_current_rate_and_says_which_figure_moves(setup, tax_inclusive, expected):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], tax_inclusive=tax_inclusive)
    ok(client.put(f"/api/products/{product['id']}", json={**product, "gst_rate": 5}))

    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    warning = next(w for w in draft["warnings"] if w["code"] == "rate_changed")
    assert "18%" in warning["message"] and "5%" in warning["message"]
    assert expected in warning["message"]
    # The draft leaves the rate to the product, and the price as quoted.
    assert draft["invoice"]["items"][0]["gst_rate"] is None
    assert draft["invoice"]["items"][0]["unit_price"] == 100

    invoice = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"]))
    assert invoice["items"][0]["gst_rate"] == 5
    assert invoice["items"][0]["unit_price"] == 100
    if tax_inclusive:
        # The tax split rounds each head, which can move an inclusive total by a paisa.
        assert invoice["total_amount"] == pytest.approx(quote["total_amount"], abs=0.02)
        assert invoice["taxable_amount"] != quote["taxable_amount"]
    else:
        assert invoice["total_amount"] == 210
        assert invoice["taxable_amount"] == quote["taxable_amount"]


def test_price_change_warns_and_keeps_the_quoted_price(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(client.put(f"/api/products/{product['id']}", json={**product, "price": 150}))
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    assert "price_changed" in {w["code"] for w in draft["warnings"]}
    invoice = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"]))
    assert invoice["items"][0]["unit_price"] == 100


def test_tax_heads_are_recomputed_from_current_data(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    assert quote["cgst_amount"] == 18 and quote["igst_amount"] == 0

    ok(client.put(f"/api/ledgers/{ledger['id']}", json={
        "name": ledger["name"], "address": ledger["address"], "gst": GST_KA,
        "phone_number": ledger["phone_number"], "email": "", "website": "", "bank_name": "",
        "branch_name": "", "account_name": "", "account_number": "", "ifsc_code": "",
    }))
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    warning = next(w for w in draft["warnings"] if w["code"] == "tax_split_changed")
    assert "IGST" in warning["message"]
    invoice = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"]))
    assert invoice["igst_amount"] == 36 and invoice["cgst_amount"] == 0
    # The quote keeps what it said at the time.
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["cgst_amount"] == 18


def test_stock_shortfall_warns_early_and_is_refused_at_conversion_only(setup):
    client, ledger, _ = setup
    scarce = create_product(client, "SCARCE-1", initial_quantity=1)
    quote = create_quotation(client, ledger["id"], scarce["id"], quantity=5)  # No check at quote time.
    assert _stock(client, scarce["id"]) == 1

    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    assert "stock_shortfall" in {w["code"] for w in draft["warnings"]}

    before = series_counters(client)
    response = client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"])
    assert response.status_code == 400

    # Everything rolled back, the invoice number included.
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "open"
    assert series_counters(client) == before
    assert _stock(client, scarce["id"]) == 1
    assert ok(client.get("/api/invoices/"))["total"] == 0


def test_failed_conversion_leaves_no_trace_when_a_later_line_is_bad(setup, db_session):
    client, ledger, product = setup
    scarce = create_product(client, "SCARCE-2", initial_quantity=1)
    quote = ok(client.post("/api/quotations/", json={
        "ledger_id": ledger["id"],
        "items": [
            {"product_id": product["id"], "quantity": 2, "unit_price": 100},
            {"product_id": scarce["id"], "quantity": 5, "unit_price": 100},
        ],
    }))
    before = series_counters(client)
    response = convert(client, quote["id"])
    assert response.status_code == 400

    db_session.expire_all()
    assert _stock(client, product["id"]) == 100
    assert series_counters(client) == before
    assert db_session.query(Invoice).count() == 0
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "open"


def test_serial_tracked_line_needs_its_serials_at_conversion(setup):
    client, ledger, _ = setup
    tracked = create_product(client, "PHONE-2", track_serials=True, initial_quantity=0)
    ok(client.post("/api/invoices/", json={
        "ledger_id": ledger["id"],
        "voucher_type": "purchase",
        "items": [{"product_id": tracked["id"], "quantity": 2, "unit_price": 50, "serial_numbers": ["IMEI-A", "IMEI-B"]}],
    }))
    quote = create_quotation(client, ledger["id"], tracked["id"], quantity=2)
    draft = ok(client.get(f"/api/quotations/{quote['id']}/conversion-draft"))
    assert "serials_required" in {w["code"] for w in draft["warnings"]}
    assert not draft["invoice"]["items"][0]["serial_numbers"]

    before = series_counters(client)
    refused = client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"])
    assert refused.status_code == 400
    assert "serial" in refused.text.lower()
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "open"
    assert series_counters(client) == before

    draft["invoice"]["items"][0]["serial_numbers"] = ["IMEI-A", "IMEI-B"]
    invoice = ok(client.post(f"/api/quotations/{quote['id']}/convert", json=draft["invoice"]))
    assert sorted(invoice["items"][0]["serial_numbers"]) == ["IMEI-A", "IMEI-B"]


def test_an_invoice_duplicate_does_not_inherit_the_link(setup, db_session):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"]))
    copy = ok(client.post(f"/api/invoices/{invoice['id']}/duplicate"))
    row = db_session.query(Invoice).filter(Invoice.id == copy["id"]).one()
    assert row.source_quotation_id is None


def test_voucher_type_cannot_flip_on_a_linked_invoice(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"]))
    response = client.put(f"/api/invoices/{invoice['id']}", json={
        "ledger_id": ledger["id"],
        "voucher_type": "purchase",
        "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 100}],
    })
    assert response.status_code == 400
    assert "quotation" in response.text
    # An ordinary edit still goes through, and keeps the link.
    edited = ok(client.put(f"/api/invoices/{invoice['id']}", json={
        "ledger_id": ledger["id"],
        "voucher_type": "sales",
        "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 100}],
    }))
    assert edited["source_quotation_id"] == quote["id"]


# ---------------------------------------------------------------------------
# Cancelling and restoring the invoice
# ---------------------------------------------------------------------------

def test_cancelling_the_invoice_reopens_the_quote_and_keeps_the_link(setup, db_session):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"]))

    ok(client.delete(f"/api/invoices/{invoice['id']}"))

    detail = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert detail["status"] == "open"
    assert detail["converted_at"] is None
    assert detail["invoices"][0]["status"] == "cancelled"
    assert _stock(client, product["id"]) == 100
    assert db_session.query(Invoice).filter(Invoice.id == invoice["id"]).one().source_quotation_id == quote["id"]


def test_an_accepted_quote_returns_to_accepted(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "accepted"}))
    invoice = ok(convert(client, quote["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "accepted"


def test_restoring_closes_the_quote_again(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    detail = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert detail["status"] == "converted"
    assert detail["converted_invoice_id"] == invoice["id"]


def test_reinvoicing_then_restoring_the_old_invoice_is_blocked(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    first = ok(convert(client, quote["id"]))
    ok(client.delete(f"/api/invoices/{first['id']}"))
    second = ok(convert(client, quote["id"]))
    assert second["id"] != first["id"]

    stock = _stock(client, product["id"])
    response = client.post(f"/api/invoices/{first['id']}/restore")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "quotation_reinvoiced"
    assert detail["invoice_id"] == second["id"]
    assert second["invoice_number"] in detail["message"]
    assert _stock(client, product["id"]) == stock

    history = ok(client.get(f"/api/quotations/{quote['id']}"))["invoices"]
    assert [row["status"] for row in history] == ["cancelled", "active"]

    # Cancel the newer one and the old one can come back.
    ok(client.delete(f"/api/invoices/{second['id']}"))
    ok(client.post(f"/api/invoices/{first['id']}/restore"))


def test_restoring_over_a_later_decline_leaves_no_decline_behind(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    ok(client.post(f"/api/quotations/{quote['id']}/status", json={"status": "declined", "note": "Too dear"}))

    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))

    detail = ok(client.get(f"/api/quotations/{quote['id']}"))
    assert detail["status"] == "converted"
    assert detail["declined_at"] is None


def test_restoring_after_the_quote_was_cancelled_leaves_it_cancelled(setup):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    invoice = ok(convert(client, quote["id"]))
    ok(client.delete(f"/api/invoices/{invoice['id']}"))
    ok(client.post(f"/api/quotations/{quote['id']}/cancel"))
    ok(client.post(f"/api/invoices/{invoice['id']}/restore"))
    assert ok(client.get(f"/api/quotations/{quote['id']}"))["status"] == "cancelled"


def test_the_index_is_the_backstop(setup, db_session):
    """Force what the lock prevents: a second live invoice against one quotation."""
    from sqlalchemy.exc import IntegrityError

    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"])
    ok(convert(client, quote["id"]))
    other = ok(client.post("/api/invoices/", json={
        "ledger_id": ledger["id"],
        "voucher_type": "sales",
        "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 100}],
    }))
    row = db_session.query(Invoice).filter(Invoice.id == other["id"]).one()
    row.source_quotation_id = quote["id"]
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ---------------------------------------------------------------------------
# PDF route
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("document_type", ["quotation", "proforma"])
def test_pdf_downloads(setup, document_type):
    client, ledger, product = setup
    quote = create_quotation(client, ledger["id"], product["id"], document_type=document_type)
    response = client.get(f"/api/quotations/{quote['id']}/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert f'{document_type}_{quote["quotation_number"]}.pdf' in response.headers["content-disposition"]
