"""Tests for the merged Products+Inventory endpoint and CSV export/import."""

import csv
import io
import pytest
from fastapi.testclient import TestClient


def _create_product(client: TestClient, sku: str, name: str, price: float = 99.0, gst_rate: float = 18.0, maintain_inventory: bool = True, initial_quantity: float = 0) -> dict:
    res = client.post("/api/products/", json={
        "sku": sku,
        "name": name,
        "price": price,
        "gst_rate": gst_rate,
        "maintain_inventory": maintain_inventory,
        "initial_quantity": initial_quantity,
    })
    assert res.status_code == 200, f"Failed to create product: {res.text}"
    return res.json()


class TestProductsWithInventory:
    def test_list_products_with_inventory(self, client):
        _create_product(client, "PI001", "Widget A", price=50, initial_quantity=10)
        _create_product(client, "PI002", "Widget B", price=75, initial_quantity=5)
        _create_product(client, "PI003", "Service C", price=100, maintain_inventory=False)

        res = client.get("/api/products/with-inventory")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert data["total"] >= 3

        items = data["items"]
        names = {item["name"] for item in items}
        assert "Widget A" in names
        assert "Widget B" in names
        assert "Service C" in names

        # Verify inventory fields
        for item in items:
            if item["name"] == "Widget A":
                assert item["current_stock"] == 10
                assert item["status"] == "active"
            elif item["name"] == "Widget B":
                assert item["current_stock"] == 5
            elif item["name"] == "Service C":
                assert item["current_stock"] == 0
                assert item["status"] == "inactive"

    def test_search_products_with_inventory(self, client):
        _create_product(client, "SRCH1", "Apple Juice")
        _create_product(client, "SRCH2", "Banana Bread")
        _create_product(client, "SRCH3", "Orange Soda")

        res = client.get("/api/products/with-inventory?search=banana")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Banana Bread"

        res = client.get("/api/products/with-inventory?search=SRCH")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 3

    def test_status_filter(self, client):
        _create_product(client, "FILT1", "Tracked Item", maintain_inventory=True, initial_quantity=5)
        _create_product(client, "FILT2", "Untracked Item", maintain_inventory=False)

        res = client.get("/api/products/with-inventory?status=active")
        assert res.status_code == 200
        data = res.json()
        for item in data["items"]:
            assert item["status"] == "active"

        res = client.get("/api/products/with-inventory?status=inactive")
        assert res.status_code == 200
        data = res.json()
        for item in data["items"]:
            assert item["status"] == "inactive"

    def test_sort_by_price(self, client):
        _create_product(client, "SORT1", "Cheap", price=10)
        _create_product(client, "SORT2", "Expensive", price=100)

        res = client.get("/api/products/with-inventory?sort_by=price&sort_order=asc")
        assert res.status_code == 200
        items = res.json()["items"]
        # Only consider items we just created
        prices = [i["selling_price"] for i in items if i["name"] in ("Cheap", "Expensive")]
        assert prices == sorted(prices)

    def test_update_product_with_inventory(self, client):
        p = _create_product(client, "UPD1", "Update Me", price=25, initial_quantity=3)

        # Update name and price
        res = client.put(f"/api/products/{p['id']}/with-inventory", json={
            "name": "Updated Name",
            "selling_price": 30,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Updated Name"
        assert data["selling_price"] == 30

        # Verify via list endpoint
        list_res = client.get("/api/products/with-inventory?search=Updated")
        assert list_res.status_code == 200
        item = list_res.json()["items"][0]
        assert item["name"] == "Updated Name"
        assert item["selling_price"] == 30

    def test_update_inventory_stock(self, client):
        p = _create_product(client, "STK1", "Stock Test", initial_quantity=10)

        res = client.put(f"/api/products/{p['id']}/with-inventory", json={
            "current_stock": 25,
        })
        assert res.status_code == 200
        assert res.json()["current_stock"] == 25

        # Verify via list
        list_res = client.get("/api/products/with-inventory?search=Stock Test")
        assert list_res.json()["items"][0]["current_stock"] == 25

    def test_toggle_status(self, client):
        p = _create_product(client, "TOG1", "Toggle Me", maintain_inventory=True, initial_quantity=1)

        # Toggle to inactive
        res = client.put(f"/api/products/{p['id']}/with-inventory", json={"status": "inactive"})
        assert res.status_code == 200
        assert res.json()["status"] == "inactive"

        # Toggle back to active
        res = client.put(f"/api/products/{p['id']}/with-inventory", json={"status": "active"})
        assert res.status_code == 200
        assert res.json()["status"] == "active"

    def test_update_nonexistent_product(self, client):
        res = client.put("/api/products/99999/with-inventory", json={"name": "Ghost"})
        assert res.status_code == 404


class TestCSVExport:
    def test_export_csv(self, client):
        _create_product(client, "CSV1", "Alpha", price=10, gst_rate=5, initial_quantity=7)
        _create_product(client, "CSV2", "Beta", price=20, gst_rate=12)

        res = client.get("/api/products/export-csv")
        assert res.status_code == 200
        assert res.headers["content-type"] == "text/csv"

        content = res.text
        reader = csv.DictReader(io.StringIO(content))

        headers = reader.fieldnames
        assert "Item Name" in headers
        assert "Item Code" in headers
        assert "Selling Price" in headers
        assert "Current Stock" in headers
        assert "Tax" in headers

        rows = list(reader)
        skus = [r["Item Code"] for r in rows]
        assert "CSV1" in skus
        assert "CSV2" in skus


class TestCSVImport:
    def test_import_csv_creates_new_products(self, client):
        csv_content = (
            "Item Name,Item Code,Selling Price,Current Stock,Tax,Description,HSN Code,Unit\n"
            "Imported A,IMP001,15.50,20,18,Test desc,8471,Pieces\n"
            "Imported B,IMP002,25.00,5,0,,9983,Kg\n"
        )

        res = client.post(
            "/api/products/import-csv",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["created"] == 2
        assert data["updated"] == 0
        assert len(data["errors"]) == 0

        # Verify products exist
        list_res = client.get("/api/products/with-inventory?search=Imported")
        items = list_res.json()["items"]
        assert len(items) == 2

        imp_a = next(i for i in items if i["sku"] == "IMP001")
        assert imp_a["selling_price"] == 15.5
        assert imp_a["current_stock"] == 20
        assert imp_a["gst_rate"] == 18

        imp_b = next(i for i in items if i["sku"] == "IMP002")
        assert imp_b["selling_price"] == 25
        assert imp_b["current_stock"] == 5
        assert imp_b["unit"] == "Kg"

    def test_import_csv_updates_existing(self, client):
        p = _create_product(client, "IMP003", "Original Name", price=10, initial_quantity=3)

        csv_content = (
            "Item Name,Item Code,Selling Price,Current Stock\n"
            "Updated Name,IMP003,20,15\n"
        )

        res = client.post(
            "/api/products/import-csv",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["created"] == 0
        assert data["updated"] == 1

        # Verify update
        list_res = client.get("/api/products/with-inventory?search=Updated")
        items = list_res.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Updated Name"
        assert items[0]["selling_price"] == 20
        assert items[0]["current_stock"] == 15

    def test_import_csv_with_errors(self, client):
        csv_content = (
            "Item Name,Item Code,Selling Price\n"
            "Missing Code,,10\n"
            ",IMP004,10\n"
        )

        res = client.post(
            "/api/products/import-csv",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["created"] == 0  # Rows with errors are skipped
        assert len(data["errors"]) == 2

    def test_import_csv_empty_file(self, client):
        res = client.post(
            "/api/products/import-csv",
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["created"] == 0
        assert len(data["errors"]) > 0


class TestProductPurchasePriceAndReorderLevel:
    """Tests for purchase_price and reorder_level fields on products (Issue #385)."""

    def test_create_product_with_purchase_price_and_reorder_level(self, client):
        res = client.post("/api/products/", json={
            "sku": "PPR001",
            "name": "Margin Test Product",
            "price": 150.0,
            "purchase_price": 90.0,
            "reorder_level": 5.0,
            "gst_rate": 18,
            "maintain_inventory": True,
            "initial_quantity": 20,
        })
        assert res.status_code == 200

        # Fields should appear in the inventory grid
        inv_res = client.get("/api/products/with-inventory?search=Margin")
        assert inv_res.status_code == 200
        items = inv_res.json()["items"]
        assert len(items) == 1
        assert items[0]["purchase_price"] == 90.0
        assert items[0]["reorder_level"] == 5.0
        assert items[0]["selling_price"] == 150.0

    def test_update_purchase_price_via_inventory_endpoint(self, client):
        # Create with defaults
        create_res = client.post("/api/products/", json={
            "sku": "PPR002",
            "name": "Update Purchase Price",
            "price": 100.0,
            "gst_rate": 0,
            "maintain_inventory": True,
            "initial_quantity": 10,
        })
        assert create_res.status_code == 200
        product_id = create_res.json()["id"]

        # Update purchase_price via with-inventory endpoint
        update_res = client.put(f"/api/products/{product_id}/with-inventory", json={
            "purchase_price": 60.0,
        })
        assert update_res.status_code == 200
        assert update_res.json()["purchase_price"] == 60.0

        # Verify persisted
        inv_res = client.get("/api/products/with-inventory?search=Update Purchase")
        assert inv_res.status_code == 200
        item = inv_res.json()["items"][0]
        assert item["purchase_price"] == 60.0

    def test_update_reorder_level_via_inventory_endpoint(self, client):
        create_res = client.post("/api/products/", json={
            "sku": "PPR003",
            "name": "Reorder Level Test",
            "price": 50.0,
            "gst_rate": 5,
            "maintain_inventory": True,
            "initial_quantity": 0,
        })
        assert create_res.status_code == 200
        product_id = create_res.json()["id"]

        update_res = client.put(f"/api/products/{product_id}/with-inventory", json={
            "reorder_level": 10.0,
        })
        assert update_res.status_code == 200
        assert update_res.json()["reorder_level"] == 10.0

        inv_res = client.get("/api/products/with-inventory?search=Reorder Level")
        item = inv_res.json()["items"][0]
        assert item["reorder_level"] == 10.0

    def test_purchase_price_appears_in_csv_export(self, client):
        client.post("/api/products/", json={
            "sku": "PPR004",
            "name": "CSV Purchase Price",
            "price": 200.0,
            "purchase_price": 120.0,
            "reorder_level": 3.0,
            "gst_rate": 12,
            "maintain_inventory": True,
            "initial_quantity": 7,
        })

        res = client.get("/api/products/export-csv")
        assert res.status_code == 200
        content = res.text

        import csv, io
        reader = csv.DictReader(io.StringIO(content))
        headers = reader.fieldnames
        assert "Purchase Price" in headers, f"Missing 'Purchase Price' in CSV headers: {headers}"
        assert "Reorder Level" in headers, f"Missing 'Reorder Level' in CSV headers: {headers}"

        rows = {r["Item Code"]: r for r in reader}
        assert "PPR004" in rows
        assert float(rows["PPR004"]["Purchase Price"]) == 120.0
        assert float(rows["PPR004"]["Reorder Level"]) == 3.0
        assert float(rows["PPR004"]["Selling Price"]) == 200.0

    def test_csv_import_with_purchase_price_and_reorder_level(self, client):
        csv_content = (
            "Item Name,Item Code,Selling Price,Purchase Price,Reorder Level,Current Stock,Tax\n"
            "Import Margin A,PPR005,150,90,5,20,18\n"
        )
        res = client.post(
            "/api/products/import-csv",
            files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["created"] == 1
        assert data["errors"] == []

        inv_res = client.get("/api/products/with-inventory?search=Import Margin")
        items = inv_res.json()["items"]
        assert len(items) == 1
        assert items[0]["purchase_price"] == 90.0
        assert items[0]["reorder_level"] == 5.0
        assert items[0]["selling_price"] == 150.0
        assert items[0]["current_stock"] == 20

    def test_default_purchase_price_and_reorder_level_are_zero(self, client):
        """Products created without purchase_price/reorder_level default to 0."""
        res = client.post("/api/products/", json={
            "sku": "PPR006",
            "name": "Default Fields Test",
            "price": 75.0,
            "gst_rate": 0,
            "maintain_inventory": True,
            "initial_quantity": 0,
        })
        assert res.status_code == 200

        inv_res = client.get("/api/products/with-inventory?search=Default Fields")
        item = inv_res.json()["items"][0]
        assert item["purchase_price"] == 0.0
        assert item["reorder_level"] == 0.0


class TestCSVExportFields:
    """Verify exported CSV contains all required fields per Issue #385."""

    def test_export_csv_has_all_required_fields(self, client):
        import csv, io
        client.post("/api/products/", json={
            "sku": "FLD001",
            "name": "Full Fields Test",
            "price": 50.0,
            "purchase_price": 30.0,
            "reorder_level": 2.0,
            "gst_rate": 18,
            "maintain_inventory": True,
            "initial_quantity": 5,
        })
        res = client.get("/api/products/export-csv")
        assert res.status_code == 200
        reader = csv.DictReader(io.StringIO(res.text))
        headers = set(reader.fieldnames or [])
        required = {"Item Name", "Item Code", "Purchase Price", "Selling Price",
                    "Current Stock", "Reorder Level", "Description", "HSN Code", "Unit", "Tax"}
        missing = required - headers
        assert not missing, f"CSV export missing fields: {missing}"


class TestCSVExportImportRoundtrip:
    def test_export_then_import_csv(self, client):
        """Export all products to CSV, then import them back — should update existing, create none."""
        _create_product(client, "RND1", "Roundtrip A", price=42, gst_rate=18, initial_quantity=3)

        # Export
        export_res = client.get("/api/products/export-csv")
        assert export_res.status_code == 200
        csv_bytes = export_res.text.encode("utf-8")

        # Import the same CSV
        import_res = client.post(
            "/api/products/import-csv",
            files={"file": ("roundtrip.csv", csv_bytes, "text/csv")},
        )
        assert import_res.status_code == 200
        data = import_res.json()
        # All should be updated, none created (since they already exist)
        assert data["created"] == 0
        assert data["errors"] == []

        # Verify product still exists with same data
        list_res = client.get("/api/products/with-inventory?search=Roundtrip")
        items = list_res.json()["items"]
        assert len(items) == 1
        assert items[0]["sku"] == "RND1"
        assert items[0]["selling_price"] == 42
