"""Tests for GET /api/analytics/product-performance.

Every figure is ex-GST. Numbers are chosen so the expected values are exact:
an 18% GST line of 100 carries 18 of tax, so a 472 invoice is 400 + 72.
"""

from datetime import date, datetime, timedelta

from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice, InvoiceItem

MARCH = {"from_date": "2026-03-01", "to_date": "2026-03-31"}
IN_MARCH = datetime(2026, 3, 10, 12, 0)


def _create_product(client, sku, name, price=100, *, purchase_price=0, stock=1000, **extra):
    payload = {"sku": sku, "name": name, "price": price, "gst_rate": 18, "purchase_price": purchase_price}
    payload.update(extra)
    response = client.post("/api/products/", json=payload)
    assert response.status_code == 200, response.text
    product_id = response.json()["id"]
    if stock and extra.get("maintain_inventory", True):
        adjust = client.post("/api/inventory/adjust", json={"product_id": product_id, "quantity": stock})
        assert adjust.status_code == 200, adjust.text
    return product_id


def _create_ledger(client, name):
    response = client.post(
        "/api/ledgers/",
        json={"name": name, "address": "1 Market St", "phone_number": "1234567890"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _line(product_id, quantity, unit_price, gst_rate=18):
    return {"product_id": product_id, "quantity": quantity, "unit_price": unit_price, "gst_rate": gst_rate}


def _create_invoice(client, ledger_id, items, *, voucher_type="sales", invoice_date=IN_MARCH, **extra):
    """invoice_date=None leaves the column default (now), which credit-note
    tests need: a note is dated by its created_at, i.e. today."""
    payload = {"voucher_type": voucher_type, "ledger_id": ledger_id, "items": items, **extra}
    if invoice_date is not None:
        payload["invoice_date"] = invoice_date.date().isoformat()
    response = client.post("/api/invoices/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _create_note(client, invoice, quantities, *, direction="outward", note_type="return"):
    """quantities maps invoice_item_id -> units (or the inclusive amount for a
    discount note)."""
    items = []
    for item_id, amount in quantities.items():
        entry = {"invoice_id": invoice["id"], "invoice_item_id": item_id}
        if note_type == "discount":
            entry["discount_amount_inclusive"] = amount
        else:
            entry["quantity"] = amount
        items.append(entry)
    payload = {
        "ledger_id": invoice["ledger_id"],
        "invoice_ids": [invoice["id"]],
        "credit_note_type": note_type,
        "direction": direction,
        "items": items,
    }
    if direction == "inward":
        payload["supplier_credit_note_number"] = "SUP-CN-1"
        payload["supplier_credit_note_date"] = date.today().isoformat()
    response = client.post("/api/credit-notes/", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _report(client, **params):
    response = client.get("/api/analytics/product-performance", params={**MARCH, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _rows(data):
    return {row["name"]: row for row in data["rows"]}


def _today_window():
    # Credit notes are stamped with utcnow; a wide window keeps the test
    # independent of the day of the month it runs on.
    today = datetime.utcnow().date()
    return {"from_date": (today - timedelta(days=400)).isoformat(), "to_date": today.isoformat()}


class TestCostBasis:
    def test_average_cost_across_purchases_at_different_prices(self, client):
        # purchase_price is deliberately wrong: purchases in the period win.
        widget = _create_product(client, "PP-1", "Widget", purchase_price=999)
        supplier = _create_ledger(client, "Supplier")
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, supplier, [_line(widget, 10, 50)], voucher_type="purchase")
        _create_invoice(client, supplier, [_line(widget, 30, 70)], voucher_type="purchase")
        _create_invoice(client, customer, [_line(widget, 20, 100)])

        row = _rows(_report(client))["Widget"]
        assert row["cost_basis"] == "purchases"
        assert row["units_bought"] == 40
        assert row["purchase_spend"] == 2600.00  # 500 + 2100, ex-GST
        assert row["average_buying_price"] == 65.00  # 2600 / 40
        assert row["units_sold"] == 20
        assert row["average_selling_price"] == 100.00
        assert row["revenue"] == 2000.00
        assert row["cogs"] == 1300.00  # 20 x 65
        assert row["gross_profit"] == 700.00
        assert row["margin_pct"] == 35.00
        assert row["profit_per_unit"] == 35.00

    def test_falls_back_to_current_purchase_price(self, client):
        widget = _create_product(client, "PP-2", "Widget", purchase_price=60)
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, customer, [_line(widget, 10, 100)])

        data = _report(client)
        row = _rows(data)["Widget"]
        assert row["cost_basis"] == "current_price"
        assert row["average_buying_price"] == 60.00
        assert row["units_bought"] == 0
        assert row["cogs"] == 600.00
        assert row["gross_profit"] == 400.00
        assert row["margin_pct"] == 40.00
        assert data["totals"]["current_price_product_count"] == 1

    def test_product_without_any_cost_reports_null_profit(self, client):
        free = _create_product(client, "PP-3", "Uncosted", purchase_price=0)
        costed = _create_product(client, "PP-4", "Costed", purchase_price=60)
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, customer, [_line(free, 1, 500), _line(costed, 1, 100)])

        data = _report(client)
        row = _rows(data)["Uncosted"]
        assert row["cost_basis"] is None
        for field in ("average_buying_price", "cogs", "gross_profit", "margin_pct", "profit_per_unit"):
            assert row[field] is None, field
        assert row["revenue"] == 500.00  # revenue is still known

        totals = data["totals"]
        assert totals["revenue"] == 600.00
        assert totals["uncosted_product_count"] == 1
        # Profit totals cover the costed product only, so the uncosted 500
        # neither inflates profit nor dilutes the margin.
        assert totals["costed_revenue"] == 100.00
        assert totals["gross_profit"] == 40.00
        assert totals["margin_pct"] == 40.00

    def test_ledger_filter_does_not_change_the_cost(self, client):
        """Cost is what the product cost the business, whoever bought it."""
        widget = _create_product(client, "PP-5", "Widget", purchase_price=999)
        supplier = _create_ledger(client, "Supplier")
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, supplier, [_line(widget, 10, 40)], voucher_type="purchase")
        _create_invoice(client, customer, [_line(widget, 5, 100)])

        row = _rows(_report(client, ledger_id=customer))["Widget"]
        assert row["cost_basis"] == "purchases"
        assert row["average_buying_price"] == 40.00
        assert row["units_bought"] == 0  # the supplier's invoice is filtered out
        assert row["gross_profit"] == 300.00


class TestInvoiceDiscounts:
    def test_percentage_invoice_discount_is_apportioned(self, client):
        a = _create_product(client, "ID-1", "Alpha", purchase_price=10)
        b = _create_product(client, "ID-2", "Beta", purchase_price=10)
        customer = _create_ledger(client, "Customer")
        # 400 + 72 GST = 472; 10% off = 47.20, of which 400/472 = 40.00 is ex-GST.
        _create_invoice(
            client, customer, [_line(a, 1, 100), _line(b, 1, 300)],
            discount_type="percentage", discount_value=10,
        )

        data = _report(client)
        rows = _rows(data)
        assert rows["Alpha"]["revenue"] == 90.00
        assert rows["Beta"]["revenue"] == 270.00
        assert data["totals"]["revenue"] == 360.00

    def test_fixed_invoice_discount_is_apportioned(self, client):
        a = _create_product(client, "ID-3", "Alpha", purchase_price=10)
        b = _create_product(client, "ID-4", "Beta", purchase_price=10)
        customer = _create_ledger(client, "Customer")
        # 59 off a 472 invoice: 59 x 400/472 = 50.00 ex-GST, split 1:3.
        _create_invoice(
            client, customer, [_line(a, 1, 100), _line(b, 3, 100)],
            discount_type="net", discount_value=59,
        )

        rows = _rows(_report(client))
        assert rows["Alpha"]["revenue"] == 87.50
        assert rows["Beta"]["revenue"] == 262.50
        assert rows["Beta"]["average_selling_price"] == 87.50

    def test_purchase_invoice_discount_lowers_spend_and_cost(self, client):
        widget = _create_product(client, "ID-5", "Widget")
        supplier = _create_ledger(client, "Supplier")
        # 1000 + 180 GST; 118 off is 100 ex-GST.
        _create_invoice(
            client, supplier, [_line(widget, 10, 100)], voucher_type="purchase",
            discount_type="net", discount_value=118,
        )

        row = _rows(_report(client))["Widget"]
        assert row["purchase_spend"] == 900.00
        assert row["average_buying_price"] == 90.00

    def test_product_filter_keeps_only_that_products_share(self, client):
        a = _create_product(client, "ID-6", "Alpha", purchase_price=10)
        b = _create_product(client, "ID-7", "Beta", purchase_price=10)
        customer = _create_ledger(client, "Customer")
        _create_invoice(
            client, customer, [_line(a, 1, 100), _line(b, 1, 300)],
            discount_type="percentage", discount_value=10,
        )

        data = _report(client, product_id=a)
        assert [row["name"] for row in data["rows"]] == ["Alpha"]
        assert data["rows"][0]["revenue"] == 90.00


class TestTaxInclusive:
    def test_tax_inclusive_purchase_is_costed_ex_gst(self, client):
        widget = _create_product(client, "TI-1", "Widget")
        supplier = _create_ledger(client, "Supplier")
        customer = _create_ledger(client, "Customer")
        # 118 incl. 18% GST is 100 ex-GST.
        _create_invoice(client, supplier, [_line(widget, 5, 118)], voucher_type="purchase", tax_inclusive=True)
        _create_invoice(client, customer, [_line(widget, 2, 150)])

        row = _rows(_report(client))["Widget"]
        assert row["purchase_spend"] == 500.00
        assert row["average_buying_price"] == 100.00
        assert row["cogs"] == 200.00
        assert row["gross_profit"] == 100.00


class TestReturns:
    def test_sales_return_nets_units_revenue_and_cogs(self, client):
        widget = _create_product(client, "RT-1", "Widget")
        supplier = _create_ledger(client, "Supplier")
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, supplier, [_line(widget, 10, 60)], voucher_type="purchase", invoice_date=None)
        sale = _create_invoice(client, customer, [_line(widget, 10, 100)], invoice_date=None)
        _create_note(client, sale, {sale["items"][0]["id"]: 4})

        row = _rows(_report(client, **_today_window()))["Widget"]
        assert row["units_sold"] == 10
        assert row["units_returned"] == 4
        assert row["net_units_sold"] == 6
        assert row["sales_value"] == 1000.00
        assert row["return_value"] == 400.00
        assert row["revenue"] == 600.00
        assert row["average_selling_price"] == 100.00  # over gross sales
        assert row["cogs"] == 360.00  # 6 net units x 60
        assert row["gross_profit"] == 240.00
        assert row["profit_per_unit"] == 40.00

    def test_purchase_return_nets_units_and_spend(self, client):
        widget = _create_product(client, "RT-2", "Widget")
        supplier = _create_ledger(client, "Supplier")
        purchase = _create_invoice(client, supplier, [_line(widget, 10, 60)], voucher_type="purchase", invoice_date=None)
        _create_note(client, purchase, {purchase["items"][0]["id"]: 3}, direction="inward")

        row = _rows(_report(client, **_today_window()))["Widget"]
        assert row["units_bought"] == 10
        assert row["units_purchase_returned"] == 3
        assert row["net_units_bought"] == 7
        assert row["purchase_value"] == 600.00
        assert row["purchase_return_value"] == 180.00
        assert row["purchase_spend"] == 420.00
        assert row["average_buying_price"] == 60.00

    def test_discount_note_reduces_value_but_not_units(self, client):
        widget = _create_product(client, "RT-3", "Widget", purchase_price=50)
        customer = _create_ledger(client, "Customer")
        sale = _create_invoice(client, customer, [_line(widget, 10, 100)], invoice_date=None)
        # 118 inclusive of 18% GST is a 100 ex-GST price credit.
        _create_note(client, sale, {sale["items"][0]["id"]: 118}, note_type="discount")

        row = _rows(_report(client, **_today_window()))["Widget"]
        assert row["units_returned"] == 0
        assert row["net_units_sold"] == 10
        assert row["return_value"] == 100.00
        assert row["revenue"] == 900.00
        assert row["cogs"] == 500.00

    def test_cancelled_credit_note_is_excluded(self, client):
        widget = _create_product(client, "RT-4", "Widget", purchase_price=50)
        customer = _create_ledger(client, "Customer")
        sale = _create_invoice(client, customer, [_line(widget, 10, 100)], invoice_date=None)
        note = _create_note(client, sale, {sale["items"][0]["id"]: 4})
        assert client.post(f"/api/credit-notes/{note['id']}/cancel").status_code == 200

        row = _rows(_report(client, **_today_window()))["Widget"]
        assert row["units_returned"] == 0
        assert row["revenue"] == 1000.00


class TestScope:
    def test_cancelled_invoices_are_excluded(self, client):
        widget = _create_product(client, "SC-1", "Widget", purchase_price=999)
        supplier = _create_ledger(client, "Supplier")
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, supplier, [_line(widget, 10, 50)], voucher_type="purchase")
        cancelled_purchase = _create_invoice(client, supplier, [_line(widget, 10, 90)], voucher_type="purchase")
        _create_invoice(client, customer, [_line(widget, 1, 100)])
        cancelled_sale = _create_invoice(client, customer, [_line(widget, 5, 100)])
        assert client.delete(f"/api/invoices/{cancelled_sale['id']}").status_code == 200
        assert client.delete(f"/api/invoices/{cancelled_purchase['id']}").status_code == 200

        row = _rows(_report(client))["Widget"]
        assert row["units_sold"] == 1
        assert row["units_bought"] == 10
        assert row["average_buying_price"] == 50.00

    def test_other_company_and_null_company_rows_are_excluded(self, client, db_session):
        widget = _create_product(client, "SC-2", "Widget", purchase_price=60)
        customer = _create_ledger(client, "Customer")
        own = _create_invoice(client, customer, [_line(widget, 1, 100)])

        own_company_id = db_session.get(Invoice, own["id"]).company_id
        other = CompanyProfile(name="Other Co", address="Elsewhere", phone_number="5555555555", currency_code="INR")
        db_session.add(other)
        db_session.flush()

        for company_id in (other.id, None):
            invoice = Invoice(
                company_id=company_id, ledger_id=customer, voucher_type="sales", status="active",
                created_by=1, invoice_date=IN_MARCH,
                taxable_amount=700, total_tax_amount=126, total_amount=826,
            )
            db_session.add(invoice)
            db_session.flush()
            db_session.add(InvoiceItem(
                invoice_id=invoice.id, product_id=widget, quantity=7, unit_price=100, gst_rate=18,
                taxable_amount=700, tax_amount=126, line_total=826,
            ))
            note = CreditNote(
                credit_note_number=f"CN-X-{company_id}", company_id=company_id, ledger_id=customer,
                created_by=1, credit_note_type="return", direction="outward", status="active",
                taxable_amount=100, total_amount=118, created_at=IN_MARCH,
            )
            db_session.add(note)
            db_session.flush()
            db_session.add(CreditNoteItem(
                credit_note_id=note.id, company_id=company_id, product_id=widget, quantity=1,
                unit_price=100, gst_rate=18, taxable_amount=100, tax_amount=18, line_total=118,
            ))
        db_session.commit()
        assert own_company_id is not None and own_company_id != other.id

        row = _rows(_report(client))["Widget"]
        assert row["units_sold"] == 1
        assert row["units_returned"] == 0
        assert row["revenue"] == 100.00

    def test_currency_and_period_are_reported(self, client):
        data = _report(client)
        assert data["rows"] == []
        assert data["totals"]["product_count"] == 0
        assert data["totals"]["margin_pct"] is None
        assert data["period"]["from_date"] == "2026-03-01"
        assert data["currency_code"]


class TestSorting:
    def _seed(self, client):
        high = _create_product(client, "SO-1", "High", purchase_price=10)
        low = _create_product(client, "SO-2", "Low", purchase_price=90)
        none = _create_product(client, "SO-3", "Uncosted", purchase_price=0)
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, customer, [_line(high, 1, 100), _line(low, 1, 100), _line(none, 5, 100)])

    def test_sort_by_gross_profit_puts_nulls_last_both_ways(self, client):
        self._seed(client)
        desc = _report(client, sort_by="gross_profit", sort_dir="desc")
        asc = _report(client, sort_by="gross_profit", sort_dir="asc")
        assert [r["name"] for r in desc["rows"]] == ["High", "Low", "Uncosted"]
        assert [r["name"] for r in asc["rows"]] == ["Low", "High", "Uncosted"]

    def test_sort_by_revenue_and_name(self, client):
        self._seed(client)
        by_revenue = _report(client, sort_by="revenue", sort_dir="desc")
        by_name = _report(client, sort_by="name", sort_dir="asc")
        assert [r["name"] for r in by_revenue["rows"]][0] == "Uncosted"
        assert [r["name"] for r in by_name["rows"]] == ["High", "Low", "Uncosted"]

    def test_limit_and_totals_follow_the_returned_rows(self, client):
        self._seed(client)
        data = _report(client, sort_by="margin_pct", sort_dir="desc", limit=1)
        assert [r["name"] for r in data["rows"]] == ["High"]
        assert data["totals"]["product_count"] == 1
        assert data["totals"]["gross_profit"] == 90.00

    def test_invalid_sort_field_is_rejected(self, client):
        response = client.get("/api/analytics/product-performance", params={**MARCH, "sort_by": "bogus"})
        assert response.status_code == 422

    def test_route_and_builder_agree_on_sort_fields(self):
        from typing import get_args

        from src.api.routes.analytics import PerformanceSortBy
        from src.services.analytics_reports import PRODUCT_PERFORMANCE_SORTS

        assert set(get_args(PerformanceSortBy)) == set(PRODUCT_PERFORMANCE_SORTS)

    def test_every_sort_field_is_accepted(self, client):
        from src.services.analytics_reports import PRODUCT_PERFORMANCE_SORTS

        self._seed(client)
        for field in PRODUCT_PERFORMANCE_SORTS:
            data = _report(client, sort_by=field)
            assert len(data["rows"]) == 3, field
