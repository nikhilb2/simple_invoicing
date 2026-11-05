from datetime import datetime, timedelta
from decimal import Decimal

from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product


def _create_product(client, sku, name, price, **extra):
    payload = {"sku": sku, "name": name, "price": price, "gst_rate": 18}
    payload.update(extra)
    response = client.post("/api/products/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_ledger(client, name):
    response = client.post(
        "/api/ledgers/",
        json={"name": name, "address": "1 Market St", "phone_number": "1234567890"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_dashboard_metrics_aggregates_across_all_invoices(client):
    # Two products, one with a reorder level so we can exercise low-stock logic.
    low_product = _create_product(client, "DASH-LOW", "Low Stock Widget", 100, reorder_level=10)
    ok_product = _create_product(client, "DASH-OK", "Healthy Widget", 50, reorder_level=0)

    # Drive stock below the reorder level on the first product.
    assert client.post("/api/inventory/adjust", json={"product_id": low_product, "quantity": 5}).status_code == 200
    assert client.post("/api/inventory/adjust", json={"product_id": ok_product, "quantity": 80}).status_code == 200

    # Create a sales invoice with two line items.
    ledger_id = _create_ledger(client, "Acme Buyer")
    invoice_payload = {
        "voucher_type": "sales",
        "ledger_id": ledger_id,
        "items": [
            {"product_id": low_product, "quantity": 2, "unit_price": 100, "gst_rate": 18},
            {"product_id": ok_product, "quantity": 4, "unit_price": 50, "gst_rate": 18},
        ],
    }
    inv_res = client.post("/api/invoices/", json=invoice_payload)
    assert inv_res.status_code == 200, inv_res.text

    res = client.get("/api/dashboard/metrics")
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["catalog"]["total_products"] == 2
    assert data["inventory"]["tracked_products"] == 2
    assert data["inventory"]["low_stock_count"] == 1  # only the reorder-level product
    assert data["sales"]["sales_invoice_count"] == 1
    assert data["sales"]["total_sales"] > 0
    assert data["receivables"]["unpaid_count"] == 1
    assert data["receivables"]["outstanding_amount"] > 0

    # Charts always span the trailing 12 months and surface the sold products.
    assert len(data["charts"]["monthly"]) == 12
    assert any(point["sales"] > 0 for point in data["charts"]["monthly"])
    top_names = {p["name"] for p in data["charts"]["top_products"]}
    assert "Low Stock Widget" in top_names


def test_dashboard_metrics_empty_company(client):
    res = client.get("/api/dashboard/metrics")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["catalog"]["total_products"] == 0
    assert data["sales"]["total_sales"] == 0
    assert data["receivables"]["outstanding_amount"] == 0
    assert len(data["charts"]["monthly"]) == 12
    assert data["charts"]["top_products"] == []


def _record_product_sale(db_session, lines, *, discount=0, voucher_type="sales", status="active"):
    """Persist line and invoice totals as the invoice processor stores them."""
    taxable = sum(taxable for _, taxable, _ in lines)
    tax = sum(tax for _, _, tax in lines)
    invoice = Invoice(
        company_id=db_session.get(Product, lines[0][0]).company_id,
        created_by=1,
        voucher_type=voucher_type,
        status=status,
        taxable_amount=taxable,
        total_tax_amount=tax,
        total_amount=taxable + tax - discount,
    )
    invoice.items = [
        InvoiceItem(product_id=product_id, quantity=1, unit_price=Decimal(taxable),
                    taxable_amount=taxable, tax_amount=tax, line_total=taxable + tax)
        for product_id, taxable, tax in lines
    ]
    db_session.add(invoice)
    db_session.commit()


def _top_products(client):
    response = client.get("/api/dashboard/metrics")
    assert response.status_code == 200, response.text
    return response.json()["charts"]["top_products"]


def test_dashboard_top_product_revenue_subtracts_invoice_discount(client):
    product = _create_product(client, "DASH-DISC", "Discounted Widget", 1100, initial_quantity=1)
    ledger = _create_ledger(client, "Discount buyer")
    response = client.post("/api/invoices/", json={
        "voucher_type": "sales",
        "ledger_id": ledger,
        "discount_type": "net",
        "discount_value": 100,
        "items": [{
            "product_id": product, "quantity": 1, "unit_price": 1100, "gst_rate": 0,
            "discount_type": "net", "discount_value": 100,
        }],
    })
    assert response.status_code == 200, response.text
    assert response.json()["total_amount"] == 900

    assert [(row["quantity"], row["revenue"]) for row in _top_products(client)] == [(1, 900)]


def test_dashboard_top_products_split_discount_by_gst_inclusive_line_total(client, db_session):
    exempt = _create_product(client, "DASH-EX", "Exempt Widget", 1000)
    taxed = _create_product(client, "DASH-TAX", "Taxed Widget", 1000)
    _record_product_sale(db_session, [(exempt, 1000, 0), (taxed, 1000, 280)], discount=228)

    assert [(row["product_id"], row["revenue"]) for row in _top_products(client)] == [
        (taxed, 1152), (exempt, 900),
    ]


def test_dashboard_top_products_ranks_net_revenue_before_taking_five(client, db_session):
    discounted = _create_product(client, "DASH-DROP", "Discounted", 1000)
    _record_product_sale(db_session, [(discounted, 1000, 0)], discount=600)
    _record_product_sale(db_session, [(discounted, 2000, 0)], status="cancelled")
    _record_product_sale(db_session, [(discounted, 2000, 0)], voucher_type="purchase")

    expected = []
    for revenue in [900, 800, 700, 600, 500]:
        product = _create_product(client, f"DASH-RANK-{revenue}", f"Widget {revenue}", revenue)
        _record_product_sale(db_session, [(product, revenue, 0)])
        expected.append((product, revenue))

    assert [(row["product_id"], row["revenue"]) for row in _top_products(client)] == expected
