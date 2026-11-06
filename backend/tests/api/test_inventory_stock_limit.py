"""
API tests for issue #747: total stock upper-bound enforcement.

Postgres-specific overflow is covered in tests/db/; these SQLite tests confirm
the 400 responses that the new guard layer produces before any DB write.
"""


def test_adjust_inventory_refuses_second_when_total_would_overflow(client):
    """Two +600 M adjustments: second returns 400, stock stays at 600 M."""
    product = client.post(
        "/api/products/",
        json={"sku": "STOCKLIM1", "name": "Widget", "price": 10, "allow_decimal": True},
    ).json()
    pid = product["id"]

    r1 = client.post("/api/inventory/adjust", json={"product_id": pid, "quantity": 600_000_000})
    assert r1.status_code == 200, r1.text

    r2 = client.post("/api/inventory/adjust", json={"product_id": pid, "quantity": 600_000_000})
    assert r2.status_code == 400, r2.text
    assert "Widget" in r2.json()["detail"]

    inv = client.get("/api/inventory/", params={"search": "STOCKLIM1"}).json()
    assert inv["items"][0]["quantity"] == 600_000_000


def test_adjust_inventory_refuses_single_oversized_adjustment(client):
    """A single +10 B adjustment on empty stock returns 400."""
    product = client.post(
        "/api/products/",
        json={"sku": "STOCKLIM2", "name": "Gadget", "price": 10, "allow_decimal": True},
    ).json()

    r = client.post(
        "/api/inventory/adjust",
        json={"product_id": product["id"], "quantity": 10_000_000_000},
    )
    assert r.status_code == 400, r.text
    assert "Gadget" in r.json()["detail"]

    inv = client.get("/api/inventory/", params={"search": "STOCKLIM2"}).json()
    assert inv["items"][0]["quantity"] == 0


def test_adjust_inventory_allows_reaching_maximum_stock(client):
    """Stock can be set to exactly 999,999,999.999 — the column maximum."""
    product = client.post(
        "/api/products/",
        json={"sku": "STOCKMAX1", "name": "MaxItem", "price": 10, "allow_decimal": True},
    ).json()

    r = client.post(
        "/api/inventory/adjust",
        json={"product_id": product["id"], "quantity": 999_999_999.999},
    )
    assert r.status_code == 200, r.text

    inv = client.get("/api/inventory/", params={"search": "STOCKMAX1"}).json()
    assert float(inv["items"][0]["quantity"]) == 999_999_999.999


def test_purchase_invoice_refuses_second_when_total_would_overflow(client):
    """Two 600 M-unit purchase invoices: second refused (400), no invoice created.

    unit_price=0.01 keeps line totals (6 M) well inside the invoice amount
    limit while quantity remains 600 M — large enough to overflow the stock
    column on the second invoice.
    """
    ledger = client.post(
        "/api/ledgers/",
        json={"name": "Stock Supplier", "address": "1 Main St", "phone_number": "9876543210"},
    ).json()
    product = client.post(
        "/api/products/",
        json={
            "sku": "STOCKLIM3",
            "name": "Bolt",
            "price": 0.01,
            "allow_decimal": True,
            "initial_quantity": 0,
        },
    ).json()
    pid, lid = product["id"], ledger["id"]

    inv1 = client.post(
        "/api/invoices/",
        json={
            "ledger_id": lid,
            "voucher_type": "purchase",
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [{"product_id": pid, "quantity": 600_000_000, "unit_price": 0.01}],
        },
    )
    assert inv1.status_code == 200, inv1.text

    inv2 = client.post(
        "/api/invoices/",
        json={
            "ledger_id": lid,
            "voucher_type": "purchase",
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [{"product_id": pid, "quantity": 600_000_000, "unit_price": 0.01}],
        },
    )
    assert inv2.status_code == 400, inv2.text
    assert "Bolt" in inv2.json()["detail"]

    # Only the first invoice was persisted
    invoices = client.get("/api/invoices/").json()
    assert invoices["total"] == 1

    # Stock unchanged at 600 M
    inv = client.get("/api/inventory/", params={"search": "STOCKLIM3"}).json()
    assert inv["items"][0]["quantity"] == 600_000_000

