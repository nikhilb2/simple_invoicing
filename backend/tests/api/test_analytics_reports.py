"""Tests for the sales analytics endpoints."""

from datetime import datetime, timedelta


def _create_product(client, sku, name, price, *, stock=1000, **extra):
    """Create a product, stocked by default so sales invoices can be raised.

    Pass stock=0 when the test sets its own stock level.
    """
    payload = {"sku": sku, "name": name, "price": price, "gst_rate": 18}
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


def _create_invoice(client, ledger_id, items, *, voucher_type="sales", invoice_date=None):
    """Create an invoice. Omitting invoice_date lets the column default to
    datetime.utcnow — which, unlike the API's date-only input, carries a real
    time component (see test_invoice_dated_today_is_included)."""
    payload = {"voucher_type": voucher_type, "ledger_id": ledger_id, "items": items}
    if invoice_date is not None:
        payload["invoice_date"] = invoice_date.date().isoformat()
    response = client.post("/api/invoices/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


class TestMonthlySales:
    def test_buckets_invoices_by_month(self, client):
        product = _create_product(client, "MON-1", "Widget", 100)
        ledger = _create_ledger(client, "Acme")

        march = datetime(2026, 3, 10, 12, 0)
        april = datetime(2026, 4, 12, 12, 0)
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}], invoice_date=march)
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 2, "unit_price": 100, "gst_rate": 18}], invoice_date=april)

        res = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-03-01", "to_date": "2026-04-30"})
        assert res.status_code == 200, res.text
        data = res.json()

        assert [row["month"] for row in data["rows"]] == ["2026-03", "2026-04"]
        assert [row["label"] for row in data["rows"]] == ["Mar 26", "Apr 26"]
        assert data["rows"][0]["invoice_count"] == 1
        assert data["rows"][0]["total_sales"] == 118.00
        assert data["rows"][0]["taxable_value"] == 100.00
        assert data["rows"][0]["gst_collected"] == 18.00
        assert data["rows"][1]["invoice_count"] == 1
        assert data["rows"][1]["total_sales"] == 236.00

    def test_empty_months_are_emitted_with_zeros(self, client):
        """A quiet month must appear as zero, not be omitted — charts read gaps."""
        product = _create_product(client, "MON-2", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}],
                        invoice_date=datetime(2026, 1, 15, 12, 0))

        res = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-01-01", "to_date": "2026-03-31"})
        data = res.json()

        assert len(data["rows"]) == 3
        assert data["rows"][1]["invoice_count"] == 0
        assert data["rows"][1]["total_sales"] == 0.0
        assert data["rows"][1]["average_invoice_value"] == 0.0

    def test_totals_match_sum_of_rows(self, client):
        product = _create_product(client, "MON-3", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        for day in (10, 20):
            _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}],
                            invoice_date=datetime(2026, 5, day, 12, 0))

        res = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-05-01", "to_date": "2026-05-31"})
        data = res.json()

        assert data["totals"]["invoice_count"] == sum(r["invoice_count"] for r in data["rows"])
        assert data["totals"]["total_sales"] == sum(r["total_sales"] for r in data["rows"])
        assert data["totals"]["average_invoice_value"] == 118.00

    def test_discount_given_is_derived(self, client):
        product = _create_product(client, "MON-4", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        # 10% off a 100 line = 10.00 given away.
        _create_invoice(
            client, ledger,
            [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18,
              "discount_type": "percentage", "discount_value": 10}],
            invoice_date=datetime(2026, 6, 10, 12, 0),
        )

        res = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-06-01", "to_date": "2026-06-30"})
        assert res.json()["rows"][0]["discount_given"] == 10.00

    def test_voucher_type_splits_sales_and_purchase(self, client):
        product = _create_product(client, "MON-5", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        when = datetime(2026, 7, 10, 12, 0)
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}],
                        voucher_type="sales", invoice_date=when)
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 5, "unit_price": 60, "gst_rate": 18}],
                        voucher_type="purchase", invoice_date=when)

        params = {"from_date": "2026-07-01", "to_date": "2026-07-31"}
        sales = client.get("/api/analytics/sales-by-month", params={**params, "voucher_type": "sales"}).json()
        purchases = client.get("/api/analytics/sales-by-month", params={**params, "voucher_type": "purchase"}).json()

        assert sales["totals"]["invoice_count"] == 1
        assert sales["totals"]["taxable_value"] == 100.00
        assert purchases["totals"]["invoice_count"] == 1
        assert purchases["totals"]["taxable_value"] == 300.00

    def test_cancelled_invoices_excluded(self, client):
        product = _create_product(client, "MON-6", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        invoice = _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}],
                                  invoice_date=datetime(2026, 8, 10, 12, 0))
        # DELETE is a soft-delete that sets status="cancelled".
        assert client.delete(f"/api/invoices/{invoice['id']}").status_code == 200

        res = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-08-01", "to_date": "2026-08-31"})
        assert res.json()["totals"]["invoice_count"] == 0

    def test_ledger_filter_narrows_results(self, client):
        product = _create_product(client, "MON-7", "Widget", 100)
        acme = _create_ledger(client, "Acme")
        globex = _create_ledger(client, "Globex")
        when = datetime(2026, 9, 10, 12, 0)
        _create_invoice(client, acme, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}], invoice_date=when)
        _create_invoice(client, globex, [{"product_id": product, "quantity": 3, "unit_price": 100, "gst_rate": 18}], invoice_date=when)

        params = {"from_date": "2026-09-01", "to_date": "2026-09-30"}
        assert client.get("/api/analytics/sales-by-month", params=params).json()["totals"]["invoice_count"] == 2
        narrowed = client.get("/api/analytics/sales-by-month", params={**params, "ledger_id": acme}).json()
        assert narrowed["totals"]["invoice_count"] == 1
        assert narrowed["totals"]["taxable_value"] == 100.00

    def test_invoice_dated_today_is_included(self, client):
        """The DateTime/date boundary.

        An invoice created without an explicit date gets invoice_date =
        datetime.utcnow(), i.e. today at a real wall-clock time. Reporting up to
        and including today must still count it — comparing the DateTime column
        against a bare date would silently drop every invoice raised today.
        """
        product = _create_product(client, "MON-8", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}])

        today = datetime.utcnow().date()
        res = client.get("/api/analytics/sales-by-month", params={
            "from_date": today.replace(day=1).isoformat(),
            "to_date": today.isoformat(),
        })
        assert res.json()["totals"]["invoice_count"] == 1

    def test_from_date_after_to_date_is_rejected(self, client):
        res = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-05-01", "to_date": "2026-04-01"})
        assert res.status_code == 400

    def test_empty_company_returns_zeros(self, client):
        res = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-01-01", "to_date": "2026-01-31"})
        assert res.status_code == 200
        data = res.json()
        assert data["totals"]["invoice_count"] == 0
        assert data["totals"]["total_sales"] == 0.0
        assert len(data["rows"]) == 1

    def test_period_is_echoed_back(self, client):
        res = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-02-01", "to_date": "2026-02-28"})
        period = res.json()["period"]
        assert period["from_date"] == "2026-02-01"
        assert period["to_date"] == "2026-02-28"


class TestProductSales:
    def test_aggregates_per_product(self, client):
        widget = _create_product(client, "PRD-1", "Widget", 100)
        gadget = _create_product(client, "PRD-2", "Gadget", 50)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": widget, "quantity": 2, "unit_price": 100, "gst_rate": 18},
            {"product_id": gadget, "quantity": 4, "unit_price": 50, "gst_rate": 18},
        ], invoice_date=datetime(2026, 3, 10, 12, 0))

        res = client.get("/api/analytics/sales-by-product", params={"from_date": "2026-03-01", "to_date": "2026-03-31"})
        assert res.status_code == 200, res.text
        rows = {row["name"]: row for row in res.json()["rows"]}

        assert rows["Widget"]["quantity_sold"] == 2
        assert rows["Widget"]["sales_amount"] == 200.00  # ex-GST
        assert rows["Widget"]["total_gst"] == 36.00
        assert rows["Widget"]["total_revenue"] == 236.00  # incl. GST
        assert rows["Widget"]["average_selling_price"] == 100.00
        assert rows["Widget"]["sku"] == "PRD-1"
        assert rows["Gadget"]["quantity_sold"] == 4

    def test_invoice_count_is_distinct_per_invoice(self, client):
        """One invoice listing the same product twice must count as one invoice.

        A plain count() over line items reports 2 here.
        """
        product = _create_product(client, "PRD-3", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": product, "quantity": 3, "unit_price": 100, "gst_rate": 18},
        ], invoice_date=datetime(2026, 4, 10, 12, 0))

        res = client.get("/api/analytics/sales-by-product", params={"from_date": "2026-04-01", "to_date": "2026-04-30"})
        row = res.json()["rows"][0]
        assert row["invoice_count"] == 1
        assert row["quantity_sold"] == 4

    def test_current_stock_is_null_when_not_tracked(self, client):
        tracked = _create_product(client, "PRD-4", "Tracked", 100, stock=0, maintain_inventory=True)
        untracked = _create_product(client, "PRD-5", "Untracked", 100, maintain_inventory=False)
        assert client.post("/api/inventory/adjust", json={"product_id": tracked, "quantity": 25}).status_code == 200

        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": tracked, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": untracked, "quantity": 1, "unit_price": 100, "gst_rate": 18},
        ], invoice_date=datetime(2026, 5, 10, 12, 0))

        res = client.get("/api/analytics/sales-by-product", params={"from_date": "2026-05-01", "to_date": "2026-05-31"})
        rows = {row["name"]: row for row in res.json()["rows"]}

        assert rows["Untracked"]["current_stock"] is None
        assert rows["Tracked"]["current_stock"] == 24  # 25 in, 1 sold

    def test_sort_by_revenue(self, client):
        small = _create_product(client, "PRD-6", "Small", 10)
        big = _create_product(client, "PRD-7", "Big", 500)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": small, "quantity": 1, "unit_price": 10, "gst_rate": 18},
            {"product_id": big, "quantity": 1, "unit_price": 500, "gst_rate": 18},
        ], invoice_date=datetime(2026, 6, 10, 12, 0))

        params = {"from_date": "2026-06-01", "to_date": "2026-06-30"}
        desc = client.get("/api/analytics/sales-by-product", params={**params, "sort_by": "revenue", "sort_dir": "desc"}).json()
        asc = client.get("/api/analytics/sales-by-product", params={**params, "sort_by": "revenue", "sort_dir": "asc"}).json()

        assert [r["name"] for r in desc["rows"]] == ["Big", "Small"]
        assert [r["name"] for r in asc["rows"]] == ["Small", "Big"]

    def test_sort_by_quantity_and_name(self, client):
        alpha = _create_product(client, "PRD-8", "Alpha", 100)
        zulu = _create_product(client, "PRD-9", "Zulu", 100)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": alpha, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": zulu, "quantity": 9, "unit_price": 100, "gst_rate": 18},
        ], invoice_date=datetime(2026, 7, 10, 12, 0))

        params = {"from_date": "2026-07-01", "to_date": "2026-07-31"}
        by_qty = client.get("/api/analytics/sales-by-product", params={**params, "sort_by": "quantity", "sort_dir": "desc"}).json()
        by_name = client.get("/api/analytics/sales-by-product", params={**params, "sort_by": "name", "sort_dir": "asc"}).json()

        assert [r["name"] for r in by_qty["rows"]] == ["Zulu", "Alpha"]
        assert [r["name"] for r in by_name["rows"]] == ["Alpha", "Zulu"]

    def test_sort_by_stock_puts_untracked_last_in_both_directions(self, client):
        tracked = _create_product(client, "PRD-10", "Tracked", 100, stock=0, maintain_inventory=True)
        untracked = _create_product(client, "PRD-11", "Untracked", 100, maintain_inventory=False)
        assert client.post("/api/inventory/adjust", json={"product_id": tracked, "quantity": 50}).status_code == 200

        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": tracked, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": untracked, "quantity": 1, "unit_price": 100, "gst_rate": 18},
        ], invoice_date=datetime(2026, 8, 10, 12, 0))

        params = {"from_date": "2026-08-01", "to_date": "2026-08-31", "sort_by": "stock"}
        desc = client.get("/api/analytics/sales-by-product", params={**params, "sort_dir": "desc"}).json()
        asc = client.get("/api/analytics/sales-by-product", params={**params, "sort_dir": "asc"}).json()

        assert [r["name"] for r in desc["rows"]] == ["Tracked", "Untracked"]
        assert [r["name"] for r in asc["rows"]] == ["Tracked", "Untracked"]

    def test_limit_truncates_rows(self, client):
        ledger = _create_ledger(client, "Acme")
        items = []
        for index in range(3):
            pid = _create_product(client, f"PRD-LIM-{index}", f"Item {index}", 100)
            items.append({"product_id": pid, "quantity": index + 1, "unit_price": 100, "gst_rate": 18})
        _create_invoice(client, ledger, items, invoice_date=datetime(2026, 9, 10, 12, 0))

        res = client.get("/api/analytics/sales-by-product", params={
            "from_date": "2026-09-01", "to_date": "2026-09-30", "limit": 2,
        })
        assert len(res.json()["rows"]) == 2

    def test_product_filter_narrows_results(self, client):
        widget = _create_product(client, "PRD-12", "Widget", 100)
        gadget = _create_product(client, "PRD-13", "Gadget", 100)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": widget, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": gadget, "quantity": 1, "unit_price": 100, "gst_rate": 18},
        ], invoice_date=datetime(2026, 10, 10, 12, 0))

        res = client.get("/api/analytics/sales-by-product", params={
            "from_date": "2026-10-01", "to_date": "2026-10-31", "product_id": widget,
        })
        rows = res.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["name"] == "Widget"

    def test_totals_do_not_double_count_shared_invoices(self, client):
        """Two products on one invoice is one invoice in the totals, not two."""
        widget = _create_product(client, "PRD-14", "Widget", 100)
        gadget = _create_product(client, "PRD-15", "Gadget", 100)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": widget, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": gadget, "quantity": 1, "unit_price": 100, "gst_rate": 18},
        ], invoice_date=datetime(2026, 11, 10, 12, 0))

        res = client.get("/api/analytics/sales-by-product", params={"from_date": "2026-11-01", "to_date": "2026-11-30"})
        totals = res.json()["totals"]
        assert totals["product_count"] == 2
        assert totals["invoice_count"] == 1
        assert totals["sales_amount"] == 200.00

    def test_cancelled_invoices_excluded(self, client):
        product = _create_product(client, "PRD-16", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        invoice = _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}],
                                  invoice_date=datetime(2026, 12, 10, 12, 0))
        # DELETE is a soft-delete that sets status="cancelled".
        assert client.delete(f"/api/invoices/{invoice['id']}").status_code == 200

        res = client.get("/api/analytics/sales-by-product", params={"from_date": "2026-12-01", "to_date": "2026-12-31"})
        assert res.json()["rows"] == []

    def test_empty_company_returns_zeros(self, client):
        res = client.get("/api/analytics/sales-by-product", params={"from_date": "2026-01-01", "to_date": "2026-01-31"})
        assert res.status_code == 200
        data = res.json()
        assert data["rows"] == []
        assert data["totals"]["product_count"] == 0
        assert data["totals"]["invoice_count"] == 0

    def test_invalid_sort_field_is_rejected(self, client):
        res = client.get("/api/analytics/sales-by-product", params={
            "from_date": "2026-01-01", "to_date": "2026-01-31", "sort_by": "bogus",
        })
        assert res.status_code == 422


class TestCsvExports:
    def test_monthly_csv(self, client):
        product = _create_product(client, "CSV-1", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}],
                        invoice_date=datetime(2026, 3, 10, 12, 0))

        res = client.get("/api/analytics/sales-by-month/csv", params={"from_date": "2026-03-01", "to_date": "2026-03-31"})
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        assert "attachment" in res.headers["content-disposition"]
        assert "sales_by_month_2026-03-01_2026-03-31.csv" in res.headers["content-disposition"]

        body = res.content.decode("utf-8-sig")
        assert "Month,Invoices,Total Sales" in body
        assert "Mar 26" in body
        assert "Totals" in body

    def test_product_csv(self, client):
        product = _create_product(client, "CSV-2", "Widget", 100)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 2, "unit_price": 100, "gst_rate": 18}],
                        invoice_date=datetime(2026, 4, 10, 12, 0))

        res = client.get("/api/analytics/sales-by-product/csv", params={"from_date": "2026-04-01", "to_date": "2026-04-30"})
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")

        body = res.content.decode("utf-8-sig")
        assert "Product,Item Code,Quantity Sold" in body
        assert "Widget" in body
        assert "CSV-2" in body
        assert "Totals" in body

    def test_csv_has_excel_bom(self, client):
        """The BOM is what makes Excel render the currency correctly."""
        res = client.get("/api/analytics/sales-by-month/csv", params={"from_date": "2026-01-01", "to_date": "2026-01-31"})
        assert res.content.startswith(b"\xef\xbb\xbf")
