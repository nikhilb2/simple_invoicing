"""Tests for the unified Catalogue list endpoint — /products/with-inventory as a
superset of the old /products and /inventory grids, plus the filtered CSV export."""

import csv
import io
from datetime import datetime

from fastapi.testclient import TestClient

from sqlalchemy import func

from src.models.company import CompanyProfile
from src.models.product import Product
from src.models.product_serial import STATUS_SOLD, ProductSerial


def _create_product(client: TestClient, sku: str, name: str, **overrides) -> dict:
    payload = {
        "sku": sku,
        "name": name,
        "price": 100.0,
        "gst_rate": 18.0,
        "maintain_inventory": True,
        "initial_quantity": 0,
    }
    payload.update(overrides)
    headers = payload.pop("headers", None)
    res = client.post("/api/products/", json=payload, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _create_ledger(client: TestClient, name: str, gst: str) -> dict:
    res = client.post("/api/ledgers/", json={
        "name": name,
        "address": "123 Test St",
        "gst": gst,
        "phone_number": "9876543210",
        "email": f"{name.lower().replace(' ', '')}@example.com",
        "website": "",
        "bank_name": "",
        "branch_name": "",
        "account_name": "",
        "account_number": "",
        "ifsc_code": "",
        "opening_balance": 0,
    })
    assert res.status_code == 200, res.text
    return res.json()


def _create_invoice(client: TestClient, product_id: int, ledger_id: int, invoice_date: str, quantity: int = 1) -> dict:
    res = client.post("/api/invoices/", json={
        "ledger_id": ledger_id,
        "voucher_type": "sales",
        "invoice_date": invoice_date,
        "tax_inclusive": False,
        "apply_round_off": False,
        "items": [{"product_id": product_id, "quantity": quantity, "unit_price": 100}],
    })
    assert res.status_code == 200, res.text
    return res.json()


def _catalogue(client: TestClient, **params) -> dict:
    res = client.get("/api/products/with-inventory", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _skus(payload: dict) -> list[str]:
    return [item["sku"] for item in payload["items"]]


def _by_sku(payload: dict, sku: str) -> dict:
    return next(item for item in payload["items"] if item["sku"] == sku)


def _other_company(db_session) -> int:
    company = CompanyProfile(
        name="Second Shop",
        address="Pune",
        gst="27ZZZZZ1234F1Z5",
        phone_number="8888888888",
        currency_code="INR",
    )
    db_session.add(company)
    db_session.commit()
    return company.id


class TestCatalogueSupersetFields:
    def test_list_returns_the_inventory_page_fields(self, client):
        _create_product(
            client,
            "CAT-FIELDS-1",
            "Bulk Oil",
            unit="l",
            allow_decimal=True,
            is_producable=True,
            production_cost=42.5,
            purchase_price=60.0,
            reorder_level=3.0,
            initial_quantity=8,
        )

        item = _by_sku(_catalogue(client, search="CAT-FIELDS-1"), "CAT-FIELDS-1")
        assert item["maintain_inventory"] is True
        assert item["allow_decimal"] is True
        assert item["is_producable"] is True
        assert item["production_cost"] == 42.5
        assert item["date_added"] is not None
        assert item["last_sold_at"] is None

    def test_untracked_product_reports_its_flags(self, client):
        _create_product(client, "CAT-FIELDS-2", "Consulting", maintain_inventory=False)

        item = _by_sku(_catalogue(client, search="CAT-FIELDS-2"), "CAT-FIELDS-2")
        assert item["maintain_inventory"] is False
        assert item["allow_decimal"] is False
        assert item["is_producable"] is False
        assert item["production_cost"] is None
        assert item["status"] == "inactive"

    def test_existing_fields_are_unchanged(self, client):
        _create_product(
            client,
            "CAT-FIELDS-3",
            "Widget",
            description="A widget",
            hsn_sac="8471",
            price=150.0,
            purchase_price=90.0,
            gst_rate=12.0,
            reorder_level=4.0,
            initial_quantity=6,
        )

        item = _by_sku(_catalogue(client, search="CAT-FIELDS-3"), "CAT-FIELDS-3")
        assert item["name"] == "Widget"
        assert item["description"] == "A widget"
        assert item["hsn_sac"] == "8471"
        assert item["purchase_price"] == 90.0
        assert item["selling_price"] == 150.0
        assert item["current_stock"] == 6
        assert item["reorder_level"] == 4.0
        assert item["status"] == "active"
        assert item["unit"] == "Pieces"
        assert item["gst_rate"] == 12.0
        assert item["track_serials"] is False

    def test_last_sold_at_reflects_the_latest_invoice(self, client):
        product = _create_product(client, "CAT-SOLD-1", "Sold Item", initial_quantity=20)
        ledger = _create_ledger(client, "Sold Customer", "27AADCB2230M1ZT")

        _create_invoice(client, product["id"], ledger["id"], "2026-01-15")
        _create_invoice(client, product["id"], ledger["id"], "2026-03-20")

        item = _by_sku(_catalogue(client, search="CAT-SOLD-1"), "CAT-SOLD-1")
        assert item["last_sold_at"].startswith("2026-03-20")

    def test_cancelled_invoices_do_not_count_as_a_sale(self, client):
        product = _create_product(client, "CAT-SOLD-2", "Cancelled Sale Item", initial_quantity=20)
        ledger = _create_ledger(client, "Cancelled Customer", "29AADCB2230M1ZX")

        _create_invoice(client, product["id"], ledger["id"], "2026-01-15")
        latest = _create_invoice(client, product["id"], ledger["id"], "2026-03-20")

        cancel = client.delete(f"/api/invoices/{latest['id']}")
        assert cancel.status_code == 200, cancel.text

        item = _by_sku(_catalogue(client, search="CAT-SOLD-2"), "CAT-SOLD-2")
        assert item["last_sold_at"].startswith("2026-01-15")

    def test_last_sold_at_is_null_when_only_sale_is_cancelled(self, client):
        product = _create_product(client, "CAT-SOLD-3", "Only Cancelled Item", initial_quantity=20)
        ledger = _create_ledger(client, "Only Cancelled Customer", "24AADCB2230M1ZP")

        invoice = _create_invoice(client, product["id"], ledger["id"], "2026-02-10")
        cancel = client.delete(f"/api/invoices/{invoice['id']}")
        assert cancel.status_code == 200, cancel.text

        item = _by_sku(_catalogue(client, search="CAT-SOLD-3"), "CAT-SOLD-3")
        assert item["last_sold_at"] is None


class TestCatalogueSorting:
    def test_sort_by_purchase_price(self, client):
        _create_product(client, "CAT-SORT-P1", "Sort Purchase A", purchase_price=30.0)
        _create_product(client, "CAT-SORT-P2", "Sort Purchase B", purchase_price=10.0)
        _create_product(client, "CAT-SORT-P3", "Sort Purchase C", purchase_price=20.0)

        asc = _catalogue(client, search="Sort Purchase", sort_by="purchase_price", sort_order="asc")
        assert _skus(asc) == ["CAT-SORT-P2", "CAT-SORT-P3", "CAT-SORT-P1"]

        desc = _catalogue(client, search="Sort Purchase", sort_by="purchase_price", sort_order="desc")
        assert _skus(desc) == ["CAT-SORT-P1", "CAT-SORT-P3", "CAT-SORT-P2"]

    def test_sort_by_reorder_level(self, client):
        _create_product(client, "CAT-SORT-R1", "Sort Reorder A", reorder_level=7.0)
        _create_product(client, "CAT-SORT-R2", "Sort Reorder B", reorder_level=1.0)
        _create_product(client, "CAT-SORT-R3", "Sort Reorder C", reorder_level=4.0)

        asc = _catalogue(client, search="Sort Reorder", sort_by="reorder_level", sort_order="asc")
        assert _skus(asc) == ["CAT-SORT-R2", "CAT-SORT-R3", "CAT-SORT-R1"]

        desc = _catalogue(client, search="Sort Reorder", sort_by="reorder_level", sort_order="desc")
        assert _skus(desc) == ["CAT-SORT-R1", "CAT-SORT-R3", "CAT-SORT-R2"]

    def test_sort_by_gst_rate(self, client):
        _create_product(client, "CAT-SORT-G1", "Sort Gst A", gst_rate=18.0)
        _create_product(client, "CAT-SORT-G2", "Sort Gst B", gst_rate=0.0)
        _create_product(client, "CAT-SORT-G3", "Sort Gst C", gst_rate=5.0)

        asc = _catalogue(client, search="Sort Gst", sort_by="gst_rate", sort_order="asc")
        assert _skus(asc) == ["CAT-SORT-G2", "CAT-SORT-G3", "CAT-SORT-G1"]

        desc = _catalogue(client, search="Sort Gst", sort_by="gst_rate", sort_order="desc")
        assert _skus(desc) == ["CAT-SORT-G1", "CAT-SORT-G3", "CAT-SORT-G2"]

    def test_sort_by_date_added(self, client, db_session):
        _create_product(client, "CAT-SORT-D1", "Sort Date A")
        _create_product(client, "CAT-SORT-D2", "Sort Date B")
        _create_product(client, "CAT-SORT-D3", "Sort Date C")

        # created_at lands on the same second for all three here, so the order
        # has to be made explicit for the assertion to mean anything.
        stamps = {
            "CAT-SORT-D1": datetime(2026, 3, 1, 9, 0, 0),
            "CAT-SORT-D2": datetime(2026, 1, 1, 9, 0, 0),
            "CAT-SORT-D3": datetime(2026, 2, 1, 9, 0, 0),
        }
        for sku, stamp in stamps.items():
            product = db_session.query(Product).filter(Product.sku == sku).first()
            product.created_at = stamp
        db_session.commit()

        asc = _catalogue(client, search="Sort Date", sort_by="date_added", sort_order="asc")
        assert _skus(asc) == ["CAT-SORT-D2", "CAT-SORT-D3", "CAT-SORT-D1"]
        assert _by_sku(asc, "CAT-SORT-D2")["date_added"].startswith("2026-01-01")

        desc = _catalogue(client, search="Sort Date", sort_by="date_added", sort_order="desc")
        assert _skus(desc) == ["CAT-SORT-D1", "CAT-SORT-D3", "CAT-SORT-D2"]

    def test_sort_by_last_sold_keeps_never_sold_products_last(self, client):
        ledger = _create_ledger(client, "Sort Sold Customer", "27AADCB2230M1ZT")
        early = _create_product(client, "CAT-SORT-S1", "Sort Sold A", initial_quantity=20)
        late = _create_product(client, "CAT-SORT-S2", "Sort Sold B", initial_quantity=20)
        _create_product(client, "CAT-SORT-S3", "Sort Sold C", initial_quantity=20)

        _create_invoice(client, early["id"], ledger["id"], "2026-01-15")
        _create_invoice(client, late["id"], ledger["id"], "2026-04-15")

        asc = _catalogue(client, search="Sort Sold", sort_by="last_sold", sort_order="asc")
        assert _skus(asc) == ["CAT-SORT-S1", "CAT-SORT-S2", "CAT-SORT-S3"]

        desc = _catalogue(client, search="Sort Sold", sort_by="last_sold", sort_order="desc")
        assert _skus(desc) == ["CAT-SORT-S2", "CAT-SORT-S1", "CAT-SORT-S3"]


class TestLowStockFilter:
    def _seed(self, client):
        _create_product(client, "CAT-LOW-1", "Low Below", reorder_level=5.0, initial_quantity=2)
        _create_product(client, "CAT-LOW-2", "Low At Level", reorder_level=5.0, initial_quantity=5)
        _create_product(client, "CAT-LOW-3", "Low Above", reorder_level=5.0, initial_quantity=10)
        _create_product(client, "CAT-LOW-4", "Low No Threshold", reorder_level=0.0, initial_quantity=0)

    def test_low_stock_returns_products_at_or_below_reorder_level(self, client):
        self._seed(client)

        payload = _catalogue(client, search="CAT-LOW", low_stock=True)
        assert sorted(_skus(payload)) == ["CAT-LOW-1", "CAT-LOW-2"]
        assert payload["total"] == 2

    def test_low_stock_defaults_to_off(self, client):
        self._seed(client)

        payload = _catalogue(client, search="CAT-LOW")
        assert payload["total"] == 4

    def test_low_stock_excludes_products_without_a_reorder_level(self, client):
        self._seed(client)

        payload = _catalogue(client, search="CAT-LOW", low_stock=True)
        assert "CAT-LOW-4" not in _skus(payload)

    def test_low_stock_composes_with_search(self, client):
        self._seed(client)

        payload = _catalogue(client, search="Low At Level", low_stock=True)
        assert _skus(payload) == ["CAT-LOW-2"]
        assert payload["total"] == 1

    def test_low_stock_composes_with_status(self, client):
        self._seed(client)
        _create_product(
            client,
            "CAT-LOW-5",
            "Low Untracked",
            maintain_inventory=False,
            reorder_level=5.0,
        )

        active = _catalogue(client, search="CAT-LOW", status="active", low_stock=True)
        assert sorted(_skus(active)) == ["CAT-LOW-1", "CAT-LOW-2"]
        assert active["total"] == 2

        inactive = _catalogue(client, search="CAT-LOW", status="inactive", low_stock=True)
        assert _skus(inactive) == ["CAT-LOW-5"]
        assert inactive["total"] == 1

    def test_low_stock_does_not_reach_across_companies(self, client, db_session):
        self._seed(client)
        other_id = _other_company(db_session)
        headers = {"X-Company-Id": str(other_id)}

        _create_product(
            client,
            "CAT-LOW-OTHER",
            "Other Company Low",
            reorder_level=5.0,
            initial_quantity=1,
            headers=headers,
        )

        mine = _catalogue(client, low_stock=True)
        assert sorted(_skus(mine)) == ["CAT-LOW-1", "CAT-LOW-2"]
        assert mine["total"] == 2

        res = client.get("/api/products/with-inventory", params={"low_stock": True}, headers=headers)
        assert res.status_code == 200, res.text
        theirs = res.json()
        assert _skus(theirs) == ["CAT-LOW-OTHER"]
        assert theirs["total"] == 1


class TestExportCsvFilters:
    def _seed(self, client):
        _create_product(client, "CAT-EXP-1", "Export Below", reorder_level=5.0, initial_quantity=2)
        _create_product(client, "CAT-EXP-2", "Export Above", reorder_level=5.0, initial_quantity=10)
        _create_product(client, "CAT-EXP-3", "Export Service", maintain_inventory=False)

    def _export(self, client, **params) -> list[dict]:
        res = client.get("/api/products/export-csv", params=params)
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/csv")
        return list(csv.DictReader(io.StringIO(res.text)))

    def test_export_headers_are_unchanged(self, client):
        self._seed(client)

        res = client.get("/api/products/export-csv")
        assert res.status_code == 200
        reader = csv.DictReader(io.StringIO(res.text))
        assert reader.fieldnames == [
            "Item Name", "Item Code", "Category", "Purchase Price",
            "Selling Price", "Current Stock", "Reorder Level",
            "Description", "HSN Code", "Unit", "Tax",
        ]

    def test_export_without_filters_returns_everything(self, client):
        self._seed(client)

        codes = [row["Item Code"] for row in self._export(client)]
        assert sorted(codes) == ["CAT-EXP-1", "CAT-EXP-2", "CAT-EXP-3"]

    def test_export_honours_search(self, client):
        self._seed(client)

        codes = [row["Item Code"] for row in self._export(client, search="Export Below")]
        assert codes == ["CAT-EXP-1"]

    def test_export_honours_status(self, client):
        self._seed(client)

        codes = [row["Item Code"] for row in self._export(client, status="inactive")]
        assert codes == ["CAT-EXP-3"]

    def test_export_honours_low_stock(self, client):
        self._seed(client)

        codes = [row["Item Code"] for row in self._export(client, low_stock=True)]
        assert codes == ["CAT-EXP-1"]

    def test_export_matches_the_rows_on_screen(self, client):
        self._seed(client)

        params = {"search": "Export", "status": "active", "low_stock": True}
        listed = _catalogue(client, **params)
        exported = [row["Item Code"] for row in self._export(client, **params)]
        assert exported == _skus(listed)
        assert len(exported) == listed["total"]


class TestSerialFilters:
    """`serials=` on the grid and the export, plus searching by serial number."""

    def _serialised(self, client, sku: str, name: str, codes: list[str], **overrides) -> dict:
        return _create_product(
            client,
            sku,
            name,
            track_serials=True,
            serial_numbers=codes,
            initial_quantity=len(codes),
            **overrides,
        )

    def _seed(self, client):
        self._serialised(client, "CAT-SER-1", "Serial Handset", ["IMEI-AAA-111", "IMEI-AAA-222"])
        self._serialised(client, "CAT-SER-2", "Serial Router", ["IMEI-BBB-333"])
        _create_product(client, "CAT-SER-3", "Plain Cable", initial_quantity=10)

    def test_tracked_returns_only_serial_tracked_products(self, client):
        self._seed(client)

        payload = _catalogue(client, search="CAT-SER", serials="tracked")
        assert sorted(_skus(payload)) == ["CAT-SER-1", "CAT-SER-2"]
        assert payload["total"] == 2

    def test_untracked_returns_only_the_rest(self, client):
        self._seed(client)

        payload = _catalogue(client, search="CAT-SER", serials="untracked")
        assert _skus(payload) == ["CAT-SER-3"]
        assert payload["total"] == 1

    def test_filter_defaults_to_all(self, client):
        self._seed(client)

        assert _catalogue(client, search="CAT-SER")["total"] == 3
        # An unrecognised value falls through as "all", the way `status` does,
        # so a hand-edited URL degrades to the unfiltered list rather than to
        # an empty one.
        assert _catalogue(client, search="CAT-SER", serials="nonsense")["total"] == 3

    def test_composes_with_the_other_filters(self, client):
        self._serialised(client, "CAT-SER-LOW", "Serial Low", ["IMEI-LOW-1"], reorder_level=5.0)
        self._serialised(client, "CAT-SER-OK", "Serial Ok", ["IMEI-OK-1"], reorder_level=0.0)
        _create_product(client, "CAT-SER-PLAIN-LOW", "Plain Low", reorder_level=5.0, initial_quantity=1)

        payload = _catalogue(client, serials="tracked", low_stock=True)
        assert _skus(payload) == ["CAT-SER-LOW"]

    def test_search_finds_the_product_a_serial_belongs_to(self, client):
        self._seed(client)

        payload = _catalogue(client, search="IMEI-BBB-333")
        assert _skus(payload) == ["CAT-SER-2"]

    def test_search_matches_a_serial_case_insensitively_and_partially(self, client):
        self._seed(client)

        # Lower case, and only the tail of the code — what an operator types
        # when reading the sticker on the unit rather than the box.
        payload = _catalogue(client, search="aaa-222")
        assert _skus(payload) == ["CAT-SER-1"]

    def test_search_still_finds_a_unit_that_has_left_the_shelf(self, client, db_session):
        self._seed(client)
        serial = (
            db_session.query(ProductSerial)
            .filter(func.upper(ProductSerial.serial_number) == "IMEI-BBB-333")
            .one()
        )
        serial.status = STATUS_SOLD
        db_session.commit()

        # Tracing a handset a customer walked back in with is exactly the case
        # where the unit is no longer in stock.
        assert _skus(_catalogue(client, search="IMEI-BBB-333")) == ["CAT-SER-2"]

    def test_search_by_serial_does_not_reach_across_companies(self, client, db_session):
        # Seed the default company first: it is created lazily, so building the
        # second one up front would make *it* company 1 and the active one.
        self._serialised(client, "CAT-SER-MINE", "My Handset", ["IMEI-MINE-1"])
        other_id = _other_company(db_session)
        headers = {"X-Company-Id": str(other_id)}
        self._serialised(client, "CAT-SER-THEIRS", "Their Handset", ["IMEI-THEIRS-1"], headers=headers)

        # Their serial must not name their product from inside my catalogue...
        assert _catalogue(client, search="IMEI-THEIRS-1")["total"] == 0
        # ...nor mine from inside theirs, and my own lookup still works, so the
        # empty result is scoping rather than a broken join.
        res = client.get(
            "/api/products/with-inventory", params={"search": "IMEI-MINE-1"}, headers=headers
        )
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 0
        assert _skus(_catalogue(client, search="IMEI-MINE-1")) == ["CAT-SER-MINE"]

    def test_export_honours_the_serial_filter(self, client):
        self._seed(client)

        res = client.get("/api/products/export-csv", params={"search": "CAT-SER", "serials": "tracked"})
        assert res.status_code == 200, res.text
        codes = [row["Item Code"] for row in csv.DictReader(io.StringIO(res.text))]
        assert sorted(codes) == ["CAT-SER-1", "CAT-SER-2"]

    def test_export_matches_the_rows_on_screen(self, client):
        self._seed(client)

        params = {"search": "CAT-SER", "serials": "untracked"}
        listed = _catalogue(client, **params)
        res = client.get("/api/products/export-csv", params=params)
        assert res.status_code == 200, res.text
        exported = [row["Item Code"] for row in csv.DictReader(io.StringIO(res.text))]
        assert exported == _skus(listed)
        assert len(exported) == listed["total"]


class TestGetProductById:
    """`GET /products/{id}` — what a deep-linked citation resolves against.

    Before this existed the frontend walked up to ten pages of the list looking
    for one id, so a citation cost up to 5000 rows to open.
    """

    def test_returns_the_product(self, client):
        created = _create_product(client, "CAT-ONE-1", "Single Widget", price=250.0)

        res = client.get(f"/api/products/{created['id']}")

        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["id"] == created["id"]
        assert payload["sku"] == "CAT-ONE-1"
        assert payload["name"] == "Single Widget"

    def test_unknown_id_is_a_404(self, client):
        res = client.get("/api/products/99999999")

        assert res.status_code == 404

    def test_does_not_reach_across_companies(self, client, db_session):
        # Seed the default company first: it is created lazily, so building the
        # second one up front would make *it* company 1 and the active one.
        mine = _create_product(client, "CAT-ONE-MINE", "My Widget")
        other_id = _other_company(db_session)
        theirs = _create_product(
            client,
            "CAT-ONE-OTHER",
            "Their Widget",
            headers={"X-Company-Id": str(other_id)},
        )

        # The id is real, just not this company's — that has to be a 404 and
        # never a peek at another tenant's catalogue.
        res = client.get(f"/api/products/{theirs['id']}")

        assert res.status_code == 404
        # ...while my own is still reachable, so the 404 is scoping and not a
        # broken route.
        assert client.get(f"/api/products/{mine['id']}").status_code == 200

    def test_the_literal_routes_still_win_over_the_id_pattern(self, client):
        """`/products/with-inventory` must not be parsed as a product id."""
        _create_product(client, "CAT-ONE-2", "Route Order Widget")

        assert client.get("/api/products/with-inventory").status_code == 200
        assert client.get("/api/products/export-csv").status_code == 200
