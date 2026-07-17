"""Tests for #393 — Invoice View voucher-type filter, date-range filter, and CSV export."""

import csv
import io

from fastapi.testclient import TestClient


def _create_product(client: TestClient, sku: str, name: str, price: float = 100.0) -> dict:
    res = client.post("/api/products/", json={
        "sku": sku,
        "name": name,
        "price": price,
        "gst_rate": 18,
        "maintain_inventory": True,
        "initial_quantity": 500,
    })
    assert res.status_code == 200, res.text
    return res.json()


def _create_ledger(client: TestClient, name: str, gst: str) -> dict:
    res = client.post("/api/ledgers/", json={
        "name": name,
        "address": "123 Test St",
        "gst": gst,
        "phone_number": "9876543210",
        "email": "test@example.com",
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


def _create_invoice(client: TestClient, product_id: int, ledger_id: int,
                    voucher_type: str, invoice_date: str) -> dict:
    res = client.post("/api/invoices/", json={
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "invoice_date": invoice_date,
        "tax_inclusive": False,
        "apply_round_off": False,
        "items": [{"product_id": product_id, "quantity": 2, "unit_price": 100}],
    })
    assert res.status_code == 200, res.text
    return res.json()


def _seed(client: TestClient) -> None:
    product = _create_product(client, "VF-1", "View Filter Product")
    sales_ledger = _create_ledger(client, "Sales Customer", "27AADCB2230M1ZT")
    purchase_ledger = _create_ledger(client, "Purchase Supplier", "29AADCB2230M1ZX")
    _create_invoice(client, product["id"], sales_ledger["id"], "sales", "2026-01-15")
    _create_invoice(client, product["id"], sales_ledger["id"], "sales", "2026-03-20")
    _create_invoice(client, product["id"], purchase_ledger["id"], "purchase", "2026-02-10")


class TestInvoiceViewFilters:
    def test_voucher_type_filter(self, client):
        _seed(client)

        all_res = client.get("/api/invoices/", params={"page_size": 100})
        assert all_res.status_code == 200
        assert all_res.json()["total"] == 3

        sales_res = client.get("/api/invoices/", params={"voucher_type": "sales", "page_size": 100})
        assert sales_res.status_code == 200
        sales_items = sales_res.json()["items"]
        assert len(sales_items) == 2
        assert all(i["voucher_type"] == "sales" for i in sales_items)

        purchase_res = client.get("/api/invoices/", params={"voucher_type": "purchase", "page_size": 100})
        assert purchase_res.status_code == 200
        purchase_items = purchase_res.json()["items"]
        assert len(purchase_items) == 1
        assert purchase_items[0]["voucher_type"] == "purchase"

    def test_date_range_filter_is_inclusive(self, client):
        _seed(client)

        res = client.get("/api/invoices/", params={
            "date_from": "2026-02-01",
            "date_to": "2026-03-20",
            "page_size": 100,
        })
        assert res.status_code == 200
        items = res.json()["items"]
        # Feb 10 purchase + Mar 20 sales fall in range; Jan 15 excluded.
        assert len(items) == 2
        dates = sorted(i["invoice_date"][:10] for i in items)
        assert dates == ["2026-02-10", "2026-03-20"]

    def test_date_from_only(self, client):
        _seed(client)
        res = client.get("/api/invoices/", params={"date_from": "2026-02-10", "page_size": 100})
        assert res.status_code == 200
        assert res.json()["total"] == 2


class TestInvoiceExportCsv:
    def _read_csv(self, res):
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/csv")
        assert "attachment" in res.headers["content-disposition"]
        text = res.content.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(text)))

    def test_export_has_expected_columns_and_rows(self, client):
        _seed(client)
        rows = self._read_csv(client.get("/api/invoices/export"))
        header = rows[0]
        assert header == [
            "Invoice Number", "Invoice Date", "Voucher Type", "Party Name", "GSTIN",
            "Taxable Value", "CGST", "SGST", "IGST", "Grand Total", "Payment Status",
        ]
        # 3 invoices seeded + header row.
        assert len(rows) == 4

    def test_export_respects_voucher_type_filter(self, client):
        _seed(client)
        rows = self._read_csv(client.get("/api/invoices/export", params={"voucher_type": "purchase"}))
        assert len(rows) == 2  # header + 1 purchase
        assert rows[1][2] == "Purchase"
        assert rows[1][3] == "Purchase Supplier"

    def test_export_respects_date_range_filter(self, client):
        _seed(client)
        rows = self._read_csv(client.get("/api/invoices/export", params={
            "date_from": "2026-03-01",
            "date_to": "2026-03-31",
        }))
        assert len(rows) == 2  # header + Mar 20 sales
        assert rows[1][1] == "2026-03-20"
