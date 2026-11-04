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


def _create_invoice(client, ledger_id, items, *, voucher_type="sales", invoice_date=None, **extra):
    """Create an invoice. Omitting invoice_date lets the column default to
    datetime.utcnow — which, unlike the API's date-only input, carries a real
    time component (see test_invoice_dated_today_is_included)."""
    payload = {"voucher_type": voucher_type, "ledger_id": ledger_id, "items": items, **extra}
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

    def test_invoice_level_discount_reduces_sales_amount(self, client):
        """Issue #635: 1 x 1000 at 18% GST with a flat 118 invoice discount
        reports sales 900.00 (1000 - 118 x 1000/1180), as Product Performance does."""
        product = _create_product(client, "PRD-16", "Widget", 1000)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": product, "quantity": 1, "unit_price": 1000, "gst_rate": 18},
        ], invoice_date=datetime(2026, 10, 10, 12, 0),
            discount_type="net", discount_value=118)

        res = client.get("/api/analytics/sales-by-product", params={"from_date": "2026-10-01", "to_date": "2026-10-31"})
        assert res.status_code == 200, res.text
        row = res.json()["rows"][0]
        assert row["sales_amount"] == 900.00
        assert res.json()["totals"]["sales_amount"] == 900.00
        # Issue #674: Total Revenue includes GST, so the whole discount comes off.
        assert row["total_revenue"] == 1062.00
        assert res.json()["totals"]["total_revenue"] == 1062.00
        # Stored GST is left as the invoice wrote it.
        assert row["total_gst"] == 180.00
        # The monthly report reads the invoice header, so its taxable value
        # stays the pre-discount 1000.00 even though the line reports are net.
        monthly = client.get("/api/analytics/sales-by-month", params={"from_date": "2026-10-01", "to_date": "2026-10-31"}).json()
        assert monthly["rows"][0]["taxable_value"] == 1000.00

    def test_total_revenue_is_what_the_invoice_charged(self, client):
        """Issue #674: 1 x 1000 at 18% GST (1180) with a flat discount leaves
        Total Revenue equal to the invoice total, even when the discount is
        larger than the ex-GST value."""
        product = _create_product(client, "PRD-REV-1", "Widget", 1000)
        ledger = _create_ledger(client, "Acme")
        params = {"from_date": "2026-10-01", "to_date": "2026-10-31"}

        for discount, day, invoice_total, expected_total in (
            (1100, 10, 80.00, 80.00),
            (1180, 11, 0.00, 80.00),
        ):
            invoice = _create_invoice(client, ledger, [
                {"product_id": product, "quantity": 1, "unit_price": 1000, "gst_rate": 18},
            ], invoice_date=datetime(2026, 10, day, 12, 0),
                discount_type="net", discount_value=discount)
            assert invoice["total_amount"] == invoice_total
            row = client.get("/api/analytics/sales-by-product", params=params).json()["rows"][0]
            assert row["total_revenue"] == expected_total

    def test_total_revenue_splits_discount_by_line_total_across_gst_rates(self, client):
        """Issue #674: 1000 at 0% (1000) and 1000 at 28% (1280) with a flat 228
        discount, 10% of 2280, split by each line's GST-inclusive total."""
        exempt = _create_product(client, "PRD-REV-2", "Exempt", 1000)
        taxed = _create_product(client, "PRD-REV-3", "Taxed", 1000)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": exempt, "quantity": 1, "unit_price": 1000, "gst_rate": 0},
            {"product_id": taxed, "quantity": 1, "unit_price": 1000, "gst_rate": 28},
        ], invoice_date=datetime(2026, 10, 10, 12, 0),
            discount_type="net", discount_value=228)

        res = client.get("/api/analytics/sales-by-product", params={"from_date": "2026-10-01", "to_date": "2026-10-31"})
        rows = {row["name"]: row for row in res.json()["rows"]}
        assert rows["Exempt"]["total_revenue"] == 900.00
        assert rows["Taxed"]["total_revenue"] == 1152.00
        assert res.json()["totals"]["total_revenue"] == 2052.00

    def test_total_revenue_filter_takes_only_its_share_and_csv_agrees(self, client):
        """Issue #674: under a product filter, the whole discount is apportioned
        across all of the invoice's lines first, and the CSV shows the same figure."""
        widget = _create_product(client, "PRD-REV-4", "Widget", 100)
        gadget = _create_product(client, "PRD-REV-5", "Gadget", 50)
        ledger = _create_ledger(client, "Acme")
        # 118 + 59 = 177; a flat 17.70 is 10% of each line.
        _create_invoice(client, ledger, [
            {"product_id": widget, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": gadget, "quantity": 1, "unit_price": 50, "gst_rate": 18},
        ], invoice_date=datetime(2026, 10, 10, 12, 0),
            discount_type="net", discount_value=17.70)

        params = {"from_date": "2026-10-01", "to_date": "2026-10-31"}
        rows = {r["name"]: r for r in client.get("/api/analytics/sales-by-product", params=params).json()["rows"]}
        assert rows["Widget"]["total_revenue"] == 106.20
        assert rows["Gadget"]["total_revenue"] == 53.10

        narrowed = {**params, "product_id": widget}
        data = client.get("/api/analytics/sales-by-product", params=narrowed).json()
        assert [r["total_revenue"] for r in data["rows"]] == [106.20]
        assert data["totals"]["total_revenue"] == 106.20

        csv_text = client.get("/api/analytics/sales-by-product/csv", params=params).text
        assert "106.20" in csv_text
        assert "53.10" in csv_text
        assert "118.00" not in csv_text

    def test_product_filter_takes_only_its_share_of_discount(self, client):
        """Issue #635: under a product filter, the discount is apportioned
        across all of the invoice's lines before filtering."""
        widget = _create_product(client, "PRD-17", "Widget", 1000)
        gadget = _create_product(client, "PRD-18", "Gadget", 300)
        ledger = _create_ledger(client, "Acme")
        # 1300 taxable + 234 GST = 1534; 10% off = 153.40, of which 130.00
        # is ex-GST, split 100 to Widget and 30 to Gadget.
        _create_invoice(client, ledger, [
            {"product_id": widget, "quantity": 1, "unit_price": 1000, "gst_rate": 18},
            {"product_id": gadget, "quantity": 1, "unit_price": 300, "gst_rate": 18},
        ], invoice_date=datetime(2026, 10, 10, 12, 0),
            discount_type="percentage", discount_value=10)

        res = client.get("/api/analytics/sales-by-product", params={
            "from_date": "2026-10-01", "to_date": "2026-10-31", "product_id": widget,
        })
        rows = res.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["sales_amount"] == 900.00

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


class TestProfitLoss:
    def test_product_profit_uses_purchase_price(self, client):
        # Sell 10 @ 100 (ex-GST) with a cost of 60 → profit 400, margin 40%.
        product = _create_product(client, "PL-1", "Widget", 100, purchase_price=60)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 10, "unit_price": 100, "gst_rate": 18}],
                        invoice_date=datetime(2026, 3, 10, 12, 0))

        res = client.get("/api/analytics/profit-loss", params={"from_date": "2026-03-01", "to_date": "2026-03-31"})
        assert res.status_code == 200, res.text
        row = res.json()["product_rows"][0]
        assert row["quantity_sold"] == 10
        assert row["sales_amount"] == 1000.00  # ex-GST
        assert row["purchase_price"] == 60.00
        assert row["cogs"] == 600.00
        assert row["gross_profit"] == 400.00
        assert row["margin_pct"] == 40.00
        assert row["average_selling_price"] == 100.00

    def test_totals_and_margin(self, client):
        widget = _create_product(client, "PL-2", "Widget", 100, purchase_price=60)
        gadget = _create_product(client, "PL-3", "Gadget", 50, purchase_price=40)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": widget, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": gadget, "quantity": 1, "unit_price": 50, "gst_rate": 18},
        ], invoice_date=datetime(2026, 4, 10, 12, 0))

        totals = client.get("/api/analytics/profit-loss", params={
            "from_date": "2026-04-01", "to_date": "2026-04-30",
        }).json()["totals"]
        assert totals["product_count"] == 2
        assert totals["revenue"] == 150.00
        assert totals["cogs"] == 100.00  # 60 + 40
        assert totals["gross_profit"] == 50.00
        assert totals["margin_pct"] == round(50 / 150 * 100, 2)

    def test_loss_making_product_is_negative(self, client):
        # Cost above selling price → a loss.
        product = _create_product(client, "PL-4", "LossLeader", 50, purchase_price=80)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 2, "unit_price": 50, "gst_rate": 18}],
                        invoice_date=datetime(2026, 5, 10, 12, 0))

        row = client.get("/api/analytics/profit-loss", params={
            "from_date": "2026-05-01", "to_date": "2026-05-31",
        }).json()["product_rows"][0]
        assert row["cogs"] == 160.00
        assert row["gross_profit"] == -60.00
        assert row["margin_pct"] < 0

    def test_monthly_rows_bucket_profit(self, client):
        product = _create_product(client, "PL-5", "Widget", 100, purchase_price=60)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}],
                        invoice_date=datetime(2026, 6, 10, 12, 0))
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 2, "unit_price": 100, "gst_rate": 18}],
                        invoice_date=datetime(2026, 7, 10, 12, 0))

        rows = client.get("/api/analytics/profit-loss", params={
            "from_date": "2026-06-01", "to_date": "2026-07-31",
        }).json()["monthly_rows"]
        assert [r["month"] for r in rows] == ["2026-06", "2026-07"]
        assert rows[0]["gross_profit"] == 40.00  # 100 - 60
        assert rows[1]["gross_profit"] == 80.00  # 200 - 120

    def test_invoice_level_discount_reduces_revenue(self, client):
        """Issue #635: P&L revenue matches Product Performance on a discounted
        invoice, and an undiscounted invoice in the same period is unchanged."""
        product = _create_product(client, "PL-6", "Widget", 1000, purchase_price=60)
        plain = _create_product(client, "PL-7", "Plain", 100, purchase_price=40)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": product, "quantity": 1, "unit_price": 1000, "gst_rate": 18},
        ], invoice_date=datetime(2026, 3, 10, 12, 0),
            discount_type="net", discount_value=118)
        _create_invoice(client, ledger, [
            {"product_id": plain, "quantity": 1, "unit_price": 100, "gst_rate": 18},
        ], invoice_date=datetime(2026, 3, 12, 12, 0))

        data = client.get("/api/analytics/profit-loss", params={
            "from_date": "2026-03-01", "to_date": "2026-03-31",
        }).json()
        rows = {row["name"]: row for row in data["product_rows"]}
        assert rows["Widget"]["sales_amount"] == 900.00
        assert rows["Widget"]["gross_profit"] == 840.00  # 900 - 60
        assert rows["Plain"]["sales_amount"] == 100.00
        assert data["totals"]["revenue"] == 1000.00
        assert data["monthly_rows"][0]["revenue"] == 1000.00

    def test_product_filter_with_discount(self, client):
        """Review on #715: under a P&L product filter, the filtered product
        takes only its share of the invoice discount, and COGS / customer
        figures cover that product only. Widget 1000 + gadget 300, both at
        18%, 10% off: widget's ex-GST share is 1000 - 130 x 1000/1300 = 900."""
        widget = _create_product(client, "PL-8", "Widget", 1000, purchase_price=60)
        gadget = _create_product(client, "PL-9", "Gadget", 300, purchase_price=40)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": widget, "quantity": 1, "unit_price": 1000, "gst_rate": 18},
            {"product_id": gadget, "quantity": 1, "unit_price": 300, "gst_rate": 18},
        ], invoice_date=datetime(2026, 3, 10, 12, 0),
            discount_type="percentage", discount_value=10)

        data = client.get("/api/analytics/profit-loss", params={
            "from_date": "2026-03-01", "to_date": "2026-03-31", "product_id": widget,
        }).json()
        assert len(data["product_rows"]) == 1
        row = data["product_rows"][0]
        assert row["name"] == "Widget"
        assert row["quantity_sold"] == 1
        assert row["sales_amount"] == 900.00
        assert row["cogs"] == 60.00  # widget only, not gadget's 40
        assert data["totals"]["revenue"] == 900.00
        assert len(data["customer_rows"]) == 1
        assert data["customer_rows"][0]["revenue"] == 900.00
        assert data["customer_rows"][0]["invoice_count"] == 1

    def test_product_filter_narrows_monthly_rows(self, client):
        widget = _create_product(client, "PL-6", "Widget", 100, purchase_price=60)
        gadget = _create_product(client, "PL-7", "Gadget", 50, purchase_price=40)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [
            {"product_id": widget, "quantity": 1, "unit_price": 100, "gst_rate": 18},
            {"product_id": gadget, "quantity": 1, "unit_price": 50, "gst_rate": 18},
        ], invoice_date=datetime(2026, 8, 10, 12, 0))

        params = {"from_date": "2026-08-01", "to_date": "2026-08-31"}
        allp = client.get("/api/analytics/profit-loss", params=params).json()
        assert allp["monthly_rows"][0]["revenue"] == 150.00

        narrowed = client.get("/api/analytics/profit-loss", params={**params, "product_id": widget}).json()
        assert len(narrowed["product_rows"]) == 1
        assert narrowed["monthly_rows"][0]["revenue"] == 100.00
        assert narrowed["monthly_rows"][0]["gross_profit"] == 40.00

    def test_customer_rows_split_by_ledger(self, client):
        product = _create_product(client, "PL-8", "Widget", 100, purchase_price=60)
        acme = _create_ledger(client, "Acme")
        globex = _create_ledger(client, "Globex")
        when = datetime(2026, 9, 10, 12, 0)
        _create_invoice(client, acme, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}], invoice_date=when)
        _create_invoice(client, globex, [{"product_id": product, "quantity": 3, "unit_price": 100, "gst_rate": 18}], invoice_date=when)

        customers = {c["name"]: c for c in client.get("/api/analytics/profit-loss", params={
            "from_date": "2026-09-01", "to_date": "2026-09-30",
        }).json()["customer_rows"]}
        assert customers["Acme"]["gross_profit"] == 40.00
        assert customers["Globex"]["gross_profit"] == 120.00
        assert customers["Globex"]["invoice_count"] == 1

    def test_purchase_vouchers_excluded(self, client):
        product = _create_product(client, "PL-9", "Widget", 100, purchase_price=60)
        ledger = _create_ledger(client, "Acme")
        when = datetime(2026, 10, 10, 12, 0)
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 1, "unit_price": 100, "gst_rate": 18}],
                        voucher_type="purchase", invoice_date=when)

        totals = client.get("/api/analytics/profit-loss", params={
            "from_date": "2026-10-01", "to_date": "2026-10-31",
        }).json()["totals"]
        assert totals["product_count"] == 0
        assert totals["revenue"] == 0.0


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

    def test_profit_loss_csv(self, client):
        product = _create_product(client, "CSV-3", "Widget", 100, purchase_price=60)
        ledger = _create_ledger(client, "Acme")
        _create_invoice(client, ledger, [{"product_id": product, "quantity": 2, "unit_price": 100, "gst_rate": 18}],
                        invoice_date=datetime(2026, 4, 10, 12, 0))

        res = client.get("/api/analytics/profit-loss/csv", params={"from_date": "2026-04-01", "to_date": "2026-04-30"})
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        assert "profit_loss_2026-04-01_2026-04-30.csv" in res.headers["content-disposition"]

        body = res.content.decode("utf-8-sig")
        assert "Product,Item Code,Quantity Sold" in body
        assert "Gross Profit" in body
        assert "Widget" in body
        assert "Month,Quantity,Revenue" in body  # the second section
