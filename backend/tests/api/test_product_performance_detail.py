"""Tests for GET /api/analytics/product-performance/{product_id}.

The detail page must reconcile with the list it is opened from: its summary is
the list row, and its months add up to that row. Figures are ex-GST and chosen
so the expected values are exact (an 18% GST line of 100 carries 18 of tax).
"""

from datetime import date, datetime
from decimal import Decimal

from src.models.company import CompanyProfile
from src.models.product import Product
from src.services.analytics_reports import _sales_velocity
from tests.api.test_product_performance import (
    _create_invoice,
    _create_ledger,
    _create_note,
    _create_product,
    _line,
    _report,
    _today_window,
)

Q1 = {"from_date": "2026-01-01", "to_date": "2026-03-31"}
JAN, FEB, MAR = (datetime(2026, month, 10, 12, 0) for month in (1, 2, 3))

# Fields a month and its period row share that must sum exactly.
ADDITIVE = (
    "units_sold", "units_returned", "net_units_sold", "units_bought",
    "units_purchase_returned", "net_units_bought", "sales_value", "return_value",
    "revenue", "purchase_value", "purchase_return_value", "purchase_spend",
    "cogs", "gross_profit",
)


def _detail(client, product_id, **params):
    response = client.get(f"/api/analytics/product-performance/{product_id}", params={**Q1, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _list_row(client, product_id, **params):
    rows = _report(client, **{**Q1, **params})["rows"]
    return next(row for row in rows if row["product_id"] == product_id)


def _months(data):
    return {row["month"]: row for row in data["monthly_rows"]}


def _assert_months_sum_to(summary, monthly_rows):
    for field in ADDITIVE:
        total = sum(Decimal(str(row[field])) for row in monthly_rows)
        assert total == Decimal(str(summary[field])), field


class TestReconciliation:
    def _seed(self, client):
        widget = _create_product(client, "PD-1", "Widget", purchase_price=999)
        other = _create_product(client, "PD-2", "Other", purchase_price=5)
        supplier = _create_ledger(client, "Supplier")
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, supplier, [_line(widget, 10, 50)], voucher_type="purchase", invoice_date=JAN)
        _create_invoice(client, supplier, [_line(widget, 10, 70)], voucher_type="purchase", invoice_date=MAR)
        _create_invoice(client, customer, [_line(widget, 4, 100)], invoice_date=JAN)
        # A shared invoice with a 10% discount: the widget keeps only its share.
        _create_invoice(
            client, customer, [_line(widget, 6, 100), _line(other, 1, 400)], invoice_date=MAR,
            discount_type="percentage", discount_value=10,
        )
        return widget, customer

    def test_summary_is_the_list_row(self, client):
        widget, _ = self._seed(client)
        data = _detail(client, widget)
        assert data["summary"] == _list_row(client, widget)
        assert data["summary"]["revenue"] == 940.00  # 400 + 600 less its 10%
        assert data["summary"]["average_buying_price"] == 60.00

    def test_months_sum_to_the_summary(self, client):
        widget, _ = self._seed(client)
        data = _detail(client, widget)
        assert [row["month"] for row in data["monthly_rows"]] == ["2026-01", "2026-02", "2026-03"]
        assert [row["label"] for row in data["monthly_rows"]] == ["Jan 26", "Feb 26", "Mar 26"]
        _assert_months_sum_to(data["summary"], data["monthly_rows"])

        months = _months(data)
        assert months["2026-01"]["revenue"] == 400.00
        assert months["2026-01"]["cogs"] == 240.00  # 4 x the period cost of 60
        assert months["2026-03"]["revenue"] == 540.00
        assert months["2026-03"]["average_selling_price"] == 90.00

    def test_empty_month_is_zero_with_undefined_averages(self, client):
        widget, _ = self._seed(client)
        feb = _months(_detail(client, widget))["2026-02"]
        assert feb["units_sold"] == 0
        assert feb["revenue"] == 0
        assert feb["cogs"] == 0
        assert feb["average_selling_price"] is None
        assert feb["average_buying_price"] is None
        assert feb["margin_pct"] is None

    def test_monthly_buying_price_is_what_was_paid_that_month(self, client):
        widget, _ = self._seed(client)
        months = _months(_detail(client, widget))
        assert months["2026-01"]["average_buying_price"] == 50.00
        assert months["2026-03"]["average_buying_price"] == 70.00

    def test_cogs_rounding_never_drifts_from_the_period(self, client):
        """A unit cost of 10.00333… rounds to 10.00 a unit, but three units
        cost 30.01; the months must carry that paisa between them."""
        widget = _create_product(client, "PD-3", "Widget")
        supplier = _create_ledger(client, "Supplier")
        customer = _create_ledger(client, "Customer")
        _create_invoice(
            client, supplier, [_line(widget, 1, 10), _line(widget, 1, 10), _line(widget, 1, 10.01)],
            voucher_type="purchase", invoice_date=JAN,
        )
        for when in (JAN, FEB, MAR):
            _create_invoice(client, customer, [_line(widget, 1, 20)], invoice_date=when)

        data = _detail(client, widget)
        assert data["summary"]["cogs"] == 30.01
        assert [row["cogs"] for row in data["monthly_rows"]] == [10.00, 10.01, 10.00]
        _assert_months_sum_to(data["summary"], data["monthly_rows"])

    def test_ledger_filter_matches_the_filtered_list_row(self, client):
        widget, customer = self._seed(client)
        data = _detail(client, widget, ledger_id=customer)
        assert data["summary"] == _list_row(client, widget, ledger_id=customer)
        months = _months(data)
        # The customer filter hides the supplier's invoices from units bought…
        assert months["2026-01"]["units_bought"] == 0
        # …but not from what the product cost, as on the list.
        assert months["2026-01"]["average_buying_price"] == 50.00
        assert data["summary"]["average_buying_price"] == 60.00
        _assert_months_sum_to(data["summary"], data["monthly_rows"])


class TestReturns:
    def test_return_lands_in_the_notes_month_and_still_reconciles(self, client):
        widget = _create_product(client, "PD-4", "Widget", purchase_price=60)
        customer = _create_ledger(client, "Customer")
        sale = _create_invoice(client, customer, [_line(widget, 10, 100)], invoice_date=None)
        _create_note(client, sale, {sale["items"][0]["id"]: 4})

        window = _today_window()
        data = _detail(client, widget, **window)
        assert data["summary"] == _list_row(client, widget, **window)
        assert data["summary"]["units_returned"] == 4
        _assert_months_sum_to(data["summary"], data["monthly_rows"])

        this_month = data["monthly_rows"][-1]
        assert this_month["units_returned"] == 4
        assert this_month["return_value"] == 400.00
        assert this_month["net_units_sold"] == 6
        assert this_month["cogs"] == 360.00


class TestUncosted:
    def test_months_have_null_cost_figures(self, client):
        widget = _create_product(client, "PD-5", "Widget", purchase_price=0)
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, customer, [_line(widget, 2, 100)], invoice_date=FEB)

        data = _detail(client, widget)
        assert data["summary"]["cost_basis"] is None
        for row in data["monthly_rows"]:
            assert row["cogs"] is None
            assert row["gross_profit"] is None
        assert _months(data)["2026-02"]["revenue"] == 200.00


class TestProductAndStock:
    def test_product_with_no_activity_still_reports(self, client):
        widget = _create_product(client, "PD-6", "Idle", price=120, purchase_price=80, stock=25)
        data = _detail(client, widget)
        assert data["summary"] is None
        assert len(data["monthly_rows"]) == 3
        assert all(row["units_sold"] == 0 for row in data["monthly_rows"])
        assert data["product"]["name"] == "Idle"
        assert data["product"]["current_stock"] == 25
        assert data["product"]["price"] == 120.00
        assert data["product"]["purchase_price"] == 80.00
        assert data["velocity"]["daily_sales_rate"] is None
        assert data["velocity"]["stock_cover_days"] is None
        assert data["currency_code"]
        assert data["period"]["from_date"] == "2026-01-01"

    def test_untracked_product_has_no_stock(self, client):
        service = _create_product(client, "PD-7", "Service", stock=0, maintain_inventory=False)
        data = _detail(client, service)
        assert data["product"]["maintain_inventory"] is False
        assert data["product"]["current_stock"] is None

    def test_cover_uses_the_period_sales_rate(self, client):
        widget = _create_product(client, "PD-8", "Widget", purchase_price=10, stock=100)
        customer = _create_ledger(client, "Customer")
        _create_invoice(client, customer, [_line(widget, 90, 20)], invoice_date=JAN)

        # Q1 2026 is wholly in the past: 90 days elapsed, one unit a day.
        velocity = _detail(client, widget)["velocity"]
        assert velocity["elapsed_days"] == 90
        assert velocity["daily_sales_rate"] == 1.0
        assert velocity["stock_cover_days"] == 10.0  # 100 in stock - 90 sold = 10 left


class TestVelocity:
    def test_rate_is_over_elapsed_days_only(self):
        velocity = _sales_velocity(
            net_units_sold=Decimal("30"), current_stock=Decimal("45"),
            from_date=date(2026, 4, 1), to_date=date(2027, 3, 31), today=date(2026, 4, 30),
        )
        assert velocity["elapsed_days"] == 30
        assert velocity["daily_sales_rate"] == Decimal("1.000")
        assert velocity["stock_cover_days"] == Decimal("45.00")

    def test_future_period_and_negative_stock(self):
        future = _sales_velocity(
            net_units_sold=Decimal("0"), current_stock=Decimal("5"),
            from_date=date(2027, 1, 1), to_date=date(2027, 1, 31), today=date(2026, 6, 1),
        )
        assert future == {"elapsed_days": 0, "daily_sales_rate": None, "stock_cover_days": None}

        oversold = _sales_velocity(
            net_units_sold=Decimal("10"), current_stock=Decimal("-3"),
            from_date=date(2026, 1, 1), to_date=date(2026, 1, 10), today=date(2026, 6, 1),
        )
        assert oversold["stock_cover_days"] == Decimal("0.00")


class TestScope:
    def test_unknown_product_is_404(self, client):
        response = client.get("/api/analytics/product-performance/999999", params=Q1)
        assert response.status_code == 404

    def test_other_companys_product_is_404(self, client, db_session):
        _create_product(client, "PD-9", "Ours")  # makes sure the active company exists
        other = CompanyProfile(name="Other Co", address="Elsewhere", phone_number="5555555555", currency_code="INR")
        db_session.add(other)
        db_session.flush()
        theirs = Product(company_id=other.id, sku="PD-X", name="Theirs", price=10, purchase_price=5)
        db_session.add(theirs)
        db_session.commit()

        response = client.get(f"/api/analytics/product-performance/{theirs.id}", params=Q1)
        assert response.status_code == 404

    def test_inverted_range_is_rejected(self, client):
        widget = _create_product(client, "PD-10", "Widget")
        response = client.get(
            f"/api/analytics/product-performance/{widget}",
            params={"from_date": "2026-03-01", "to_date": "2026-01-01"},
        )
        assert response.status_code == 400
