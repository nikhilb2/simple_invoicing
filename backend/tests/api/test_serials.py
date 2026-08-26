"""
API tests for serial / IMEI tracking.

Covers the two new routes (``GET /api/serials/scan`` and ``GET /api/serials/``)
plus the serial behaviour of the invoice core: registering units on a purchase,
consuming them on a sale, and the core invariant
``inventory.quantity == count(serials WHERE status='in_stock')`` holding across
create → edit → cancel → restore.
"""
from decimal import Decimal

import pytest

from src.models.inventory import Inventory
from src.models.product import Product
from src.models.product_serial import (
    STATUS_IN_STOCK,
    STATUS_SOLD,
    STATUS_VOID,
    ProductSerial,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_ledger(client, name: str, gst: str = "27ABCDE1234F1Z5"):
    response = client.post(
        "/api/ledgers/",
        json={
            "name": name,
            "address": "Mumbai",
            "gst": gst,
            "phone_number": "9999999999",
            "email": f"{name.lower().replace(' ', '')}@example.com",
            "website": "",
            "bank_name": "",
            "branch_name": "",
            "account_name": "",
            "account_number": "",
            "ifsc_code": "",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_product(
    client,
    db_session,
    *,
    sku: str = "IPHONE-15-128",
    name: str = "iPhone 15 128GB",
    track_serials: bool = True,
    maintain_inventory: bool = True,
    initial_quantity: float = 0,
):
    """Create a product and, when asked, flip on serial tracking.

    ``track_serials`` is not exposed on ``ProductCreate`` yet, so the flag is
    set directly on the row — the invoice flows under test read it off the
    product master either way.
    """
    response = client.post(
        "/api/products/",
        json={
            "sku": sku,
            "name": name,
            "description": "",
            "hsn_sac": "8517",
            "price": 100,
            "gst_rate": 18,
            "unit": "Pieces",
            "allow_decimal": False,
            "maintain_inventory": maintain_inventory,
            "initial_quantity": initial_quantity,
        },
    )
    assert response.status_code == 200, response.text
    product_id = response.json()["id"]

    if track_serials:
        db_session.query(Product).filter(Product.id == product_id).update(
            {"track_serials": True}
        )
        db_session.commit()
    return product_id


def _invoice_payload(ledger_id, voucher_type, product_id, quantity, serials=None):
    item = {"product_id": product_id, "quantity": quantity, "unit_price": 100}
    if serials is not None:
        item["serial_numbers"] = serials
    return {
        "ledger_id": ledger_id,
        "voucher_type": voucher_type,
        "tax_inclusive": False,
        "apply_round_off": False,
        "items": [item],
    }


def _create_invoice(client, ledger_id, voucher_type, product_id, quantity, serials=None):
    response = client.post(
        "/api/invoices/",
        json=_invoice_payload(ledger_id, voucher_type, product_id, quantity, serials),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _update_invoice(client, invoice_id, ledger_id, voucher_type, product_id, quantity, serials=None):
    response = client.put(
        f"/api/invoices/{invoice_id}",
        json=_invoice_payload(ledger_id, voucher_type, product_id, quantity, serials),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _stock_of(client, ledger_id, product_id, serials):
    """Receive *serials* on a purchase so the product has units to sell."""
    return _create_invoice(
        client, ledger_id, "purchase", product_id, len(serials), serials
    )


def assert_serial_invariant(db_session, product_id) -> int:
    """The core invariant: ``inventory.quantity == count(in_stock serials)``.

    Every rule in this feature exists to hold this line, so it is asserted
    after each transition rather than only at the end.  Returns the in-stock
    count so a caller can pin the absolute number too.
    """
    db_session.expire_all()
    inventory = (
        db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
    )
    quantity = Decimal(str(inventory.quantity)) if inventory is not None else Decimal("0")
    in_stock = (
        db_session.query(ProductSerial)
        .filter(
            ProductSerial.product_id == product_id,
            ProductSerial.status == STATUS_IN_STOCK,
        )
        .count()
    )
    assert quantity == Decimal(in_stock), (
        f"invariant broken for product {product_id}: "
        f"inventory.quantity={quantity} but {in_stock} serial(s) in stock"
    )
    return in_stock


def _serial_row(db_session, number) -> ProductSerial:
    db_session.expire_all()
    return (
        db_session.query(ProductSerial)
        .filter(ProductSerial.serial_number == number)
        .one()
    )


def _line_serials(invoice, index=0):
    return invoice["items"][index]["serial_numbers"]


# ---------------------------------------------------------------------------
# Purchase registers units
# ---------------------------------------------------------------------------

def test_purchase_registers_serials_in_stock(client, db_session):
    ledger_id = _create_ledger(client, name="Serial Supplier")
    product_id = _create_product(client, db_session, sku="SER-PUR-1")

    codes = ["356938035643809", "356938035643817", "356938035643825"]
    invoice = _create_invoice(client, ledger_id, "purchase", product_id, 3, codes)

    db_session.expire_all()
    rows = (
        db_session.query(ProductSerial)
        .filter(ProductSerial.product_id == product_id)
        .order_by(ProductSerial.id.asc())
        .all()
    )
    assert [row.serial_number for row in rows] == codes
    assert all(row.status == STATUS_IN_STOCK for row in rows)
    assert all(row.purchase_invoice_id == invoice["id"] for row in rows)
    assert assert_serial_invariant(db_session, product_id) == 3


def test_purchase_rejects_a_serial_already_registered_in_this_company(client, db_session):
    ledger_id = _create_ledger(client, name="Dup Supplier")
    product_id = _create_product(client, db_session, sku="SER-PUR-DUP")

    first = _create_invoice(
        client, ledger_id, "purchase", product_id, 1, ["356938035643809"]
    )

    response = client.post(
        "/api/invoices/",
        json=_invoice_payload(
            ledger_id, "purchase", product_id, 1, ["356938035643809"]
        ),
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "already registered to iPhone 15 128GB" in detail
    assert first["invoice_number"] in detail
    assert assert_serial_invariant(db_session, product_id) == 1


def test_serial_count_must_equal_quantity_in_both_directions(client, db_session):
    ledger_id = _create_ledger(client, name="Count Supplier")
    product_id = _create_product(client, db_session, sku="SER-COUNT")

    too_few = client.post(
        "/api/invoices/",
        json=_invoice_payload(ledger_id, "purchase", product_id, 3, ["A1", "A2"]),
    )
    assert too_few.status_code == 400, too_few.text
    assert (
        "needs 3 serial numbers for quantity 3 (2 provided)"
        in too_few.json()["detail"]
    )

    too_many = client.post(
        "/api/invoices/",
        json=_invoice_payload(
            ledger_id, "purchase", product_id, 2, ["A1", "A2", "A3"]
        ),
    )
    assert too_many.status_code == 400, too_many.text
    assert (
        "needs 2 serial numbers for quantity 2 (3 provided)"
        in too_many.json()["detail"]
    )

    # Neither half-write left anything behind.
    assert assert_serial_invariant(db_session, product_id) == 0


def test_tracked_product_may_appear_on_only_one_line(client, db_session):
    ledger_id = _create_ledger(client, name="One Line Supplier")
    product_id = _create_product(client, db_session, sku="SER-ONELINE")

    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": "purchase",
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [
                {
                    "product_id": product_id,
                    "quantity": 1,
                    "unit_price": 100,
                    "serial_numbers": ["A1"],
                },
                {
                    "product_id": product_id,
                    "quantity": 1,
                    "unit_price": 100,
                    "serial_numbers": ["A2"],
                },
            ],
        },
    )
    assert response.status_code == 400, response.text
    assert "can only appear on one line per invoice" in response.json()["detail"]
    assert assert_serial_invariant(db_session, product_id) == 0


def test_serials_rejected_on_a_non_tracked_product(client, db_session):
    ledger_id = _create_ledger(client, name="Accessory Supplier")
    product_id = _create_product(
        client,
        db_session,
        sku="SER-UNTRACKED",
        name="USB-C Cable",
        track_serials=False,
    )

    response = client.post(
        "/api/invoices/",
        json=_invoice_payload(ledger_id, "purchase", product_id, 1, ["A1"]),
    )
    assert response.status_code == 400, response.text
    assert "USB-C Cable is not serial-tracked" in response.json()["detail"]
    db_session.expire_all()
    assert (
        db_session.query(ProductSerial)
        .filter(ProductSerial.product_id == product_id)
        .count()
        == 0
    )


# ---------------------------------------------------------------------------
# Sale consumes units
# ---------------------------------------------------------------------------

def test_sale_consumes_serials_and_marks_them_sold(client, db_session):
    supplier_id = _create_ledger(client, name="Sale Supplier")
    customer_id = _create_ledger(client, name="Sale Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-SALE")

    _stock_of(client, supplier_id, product_id, ["A1", "A2"])
    sale = _create_invoice(client, customer_id, "sales", product_id, 1, ["A1"])

    sold = _serial_row(db_session, "A1")
    assert sold.status == STATUS_SOLD
    assert sold.sales_invoice_id == sale["id"]
    assert _serial_row(db_session, "A2").status == STATUS_IN_STOCK
    assert assert_serial_invariant(db_session, product_id) == 1


def test_selling_an_already_sold_serial_names_the_invoice_it_went_out_on(client, db_session):
    supplier_id = _create_ledger(client, name="Resell Supplier")
    customer_id = _create_ledger(client, name="Resell Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-RESELL")

    _stock_of(client, supplier_id, product_id, ["356938035643809"])
    sale = _create_invoice(
        client, customer_id, "sales", product_id, 1, ["356938035643809"]
    )

    response = client.post(
        "/api/invoices/",
        json=_invoice_payload(
            customer_id, "sales", product_id, 1, ["356938035643809"]
        ),
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "356938035643809 has already been sold" in detail
    # The invoice it went out on is the whole point of this message — it is what
    # the shop reads back to the customer standing at the counter.
    assert sale["invoice_number"] in detail


def test_selling_a_serial_of_a_different_product_is_rejected(client, db_session):
    supplier_id = _create_ledger(client, name="Mixed Supplier")
    customer_id = _create_ledger(client, name="Mixed Customer", gst="27ABCDE9999F1Z5")
    phone_id = _create_product(client, db_session, sku="SER-PHONE")
    tablet_id = _create_product(
        client, db_session, sku="SER-TABLET", name="iPad Air"
    )

    _stock_of(client, supplier_id, tablet_id, ["TAB-1"])

    response = client.post(
        "/api/invoices/",
        json=_invoice_payload(customer_id, "sales", phone_id, 1, ["TAB-1"]),
    )
    assert response.status_code == 400, response.text
    assert "Serial TAB-1 is already registered to iPad Air" in response.json()["detail"]
    assert _serial_row(db_session, "TAB-1").status == STATUS_IN_STOCK


def test_selling_an_unknown_serial_is_rejected(client, db_session):
    customer_id = _create_ledger(client, name="Unknown Customer")
    product_id = _create_product(client, db_session, sku="SER-UNKNOWN")

    response = client.post(
        "/api/invoices/",
        json=_invoice_payload(customer_id, "sales", product_id, 1, ["NOPE-1"]),
    )
    assert response.status_code == 400, response.text
    assert "Serial NOPE-1 is not in stock" in response.json()["detail"]


# ---------------------------------------------------------------------------
# The core invariant across a full lifecycle
# ---------------------------------------------------------------------------

def test_invariant_holds_across_a_sales_invoice_lifecycle(client, db_session):
    supplier_id = _create_ledger(client, name="Life Supplier")
    customer_id = _create_ledger(client, name="Life Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-LIFE-SAL")

    _stock_of(client, supplier_id, product_id, ["A1", "A2", "A3"])
    assert assert_serial_invariant(db_session, product_id) == 3

    # create
    sale = _create_invoice(client, customer_id, "sales", product_id, 2, ["A1", "A2"])
    assert assert_serial_invariant(db_session, product_id) == 1

    # edit — add a serial
    edited = _update_invoice(
        client, sale["id"], customer_id, "sales", product_id, 3, ["A1", "A2", "A3"]
    )
    assert sorted(_line_serials(edited)) == ["A1", "A2", "A3"]
    assert assert_serial_invariant(db_session, product_id) == 0

    # edit — remove a serial
    edited = _update_invoice(
        client, sale["id"], customer_id, "sales", product_id, 2, ["A1", "A2"]
    )
    assert sorted(_line_serials(edited)) == ["A1", "A2"]
    assert _serial_row(db_session, "A3").status == STATUS_IN_STOCK
    assert assert_serial_invariant(db_session, product_id) == 1

    # cancel — the units come back
    cancel = client.delete(f"/api/invoices/{sale['id']}")
    assert cancel.status_code == 200, cancel.text
    assert assert_serial_invariant(db_session, product_id) == 3

    # restore — they go back out
    restore = client.post(f"/api/invoices/{sale['id']}/restore")
    assert restore.status_code == 200, restore.text
    assert assert_serial_invariant(db_session, product_id) == 1
    assert _serial_row(db_session, "A1").status == STATUS_SOLD
    assert _serial_row(db_session, "A2").status == STATUS_SOLD


def test_invariant_holds_across_a_purchase_invoice_lifecycle(client, db_session):
    supplier_id = _create_ledger(client, name="Life Purchase Supplier")
    product_id = _create_product(client, db_session, sku="SER-LIFE-PUR")

    # create
    purchase = _create_invoice(
        client, supplier_id, "purchase", product_id, 2, ["B1", "B2"]
    )
    assert assert_serial_invariant(db_session, product_id) == 2

    # edit — add a serial
    edited = _update_invoice(
        client, purchase["id"], supplier_id, "purchase", product_id, 3,
        ["B1", "B2", "B3"],
    )
    assert sorted(_line_serials(edited)) == ["B1", "B2", "B3"]
    assert assert_serial_invariant(db_session, product_id) == 3

    # edit — remove a serial
    edited = _update_invoice(
        client, purchase["id"], supplier_id, "purchase", product_id, 2, ["B1", "B3"]
    )
    assert sorted(_line_serials(edited)) == ["B1", "B3"]
    db_session.expire_all()
    assert (
        db_session.query(ProductSerial)
        .filter(ProductSerial.serial_number == "B2")
        .count()
        == 0
    )
    assert assert_serial_invariant(db_session, product_id) == 2

    # cancel — the units are voided
    cancel = client.delete(f"/api/invoices/{purchase['id']}")
    assert cancel.status_code == 200, cancel.text
    assert _serial_row(db_session, "B1").status == STATUS_VOID
    assert assert_serial_invariant(db_session, product_id) == 0

    # restore — they come back in stock
    restore = client.post(f"/api/invoices/{purchase['id']}/restore")
    assert restore.status_code == 200, restore.text
    assert assert_serial_invariant(db_session, product_id) == 2


# ---------------------------------------------------------------------------
# Cancelling a purchase
# ---------------------------------------------------------------------------

def test_cancelling_a_purchase_whose_serial_is_sold_is_refused(client, db_session):
    supplier_id = _create_ledger(client, name="Refuse Supplier")
    customer_id = _create_ledger(client, name="Refuse Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-REFUSE")

    purchase = _create_invoice(
        client, supplier_id, "purchase", product_id, 2,
        ["356938035643809", "356938035643817"],
    )
    sale = _create_invoice(
        client, customer_id, "sales", product_id, 1, ["356938035643817"]
    )

    response = client.delete(f"/api/invoices/{purchase['id']}")
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "356938035643817" in detail
    assert sale["invoice_number"] in detail
    assert "Cancel that sale first" in detail

    # The refusal is all-or-nothing: the purchase is still active and nothing
    # was voided.
    still = client.get(f"/api/invoices/{purchase['id']}")
    assert still.json()["status"] == "active"
    assert assert_serial_invariant(db_session, product_id) == 1


def test_cancelling_a_purchase_voids_its_units_and_frees_the_number(client, db_session):
    """The unique index skips voided rows, so a wrongly-entered IMEI can be
    received again once the purchase carrying it is cancelled.  Worth pinning
    explicitly — a partial unique index behaves differently per dialect."""
    supplier_id = _create_ledger(client, name="Void Supplier")
    product_id = _create_product(client, db_session, sku="SER-VOID")

    purchase = _create_invoice(
        client, supplier_id, "purchase", product_id, 1, ["356938035643809"]
    )
    cancel = client.delete(f"/api/invoices/{purchase['id']}")
    assert cancel.status_code == 200, cancel.text
    assert _serial_row(db_session, "356938035643809").status == STATUS_VOID
    assert assert_serial_invariant(db_session, product_id) == 0

    # The same number is now free again.
    again = _create_invoice(
        client, supplier_id, "purchase", product_id, 1, ["356938035643809"]
    )
    db_session.expire_all()
    rows = (
        db_session.query(ProductSerial)
        .filter(ProductSerial.serial_number == "356938035643809")
        .order_by(ProductSerial.id.asc())
        .all()
    )
    assert [row.status for row in rows] == [STATUS_VOID, STATUS_IN_STOCK]
    assert rows[1].purchase_invoice_id == again["id"]
    assert assert_serial_invariant(db_session, product_id) == 1


# ---------------------------------------------------------------------------
# GET /api/serials/scan
# ---------------------------------------------------------------------------

def test_scan_resolves_a_serial_in_stock(client, db_session):
    supplier_id = _create_ledger(client, name="Scan Supplier")
    product_id = _create_product(client, db_session, sku="SER-SCAN-1")
    _stock_of(client, supplier_id, product_id, ["356938035643809"])

    response = client.get("/api/serials/scan", params={"code": "356938035643809"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "serial"
    assert body["product"] is None
    assert body["serial"]["serial_number"] == "356938035643809"
    assert body["serial"]["status"] == STATUS_IN_STOCK
    assert body["serial"]["product"]["id"] == product_id
    assert body["serial"]["product"]["name"] == "iPhone 15 128GB"
    assert body["serial"]["sales_invoice"] is None
    assert body["serial"]["purchase_invoice"]["invoice_number"] is not None


def test_scan_of_a_sold_serial_carries_its_sales_invoice(client, db_session):
    """The warranty lookup: scan a handset carried back into the shop and see
    the invoice it went out on."""
    supplier_id = _create_ledger(client, name="Warranty Supplier")
    customer_id = _create_ledger(client, name="Warranty Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-SCAN-SOLD")

    _stock_of(client, supplier_id, product_id, ["356938035643809"])
    sale = _create_invoice(
        client, customer_id, "sales", product_id, 1, ["356938035643809"]
    )

    response = client.get("/api/serials/scan", params={"code": "356938035643809"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "serial"
    assert body["serial"]["status"] == STATUS_SOLD
    assert body["serial"]["sales_invoice"]["id"] == sale["id"]
    assert body["serial"]["sales_invoice"]["invoice_number"] == sale["invoice_number"]
    assert body["serial"]["sales_invoice"]["invoice_date"] is not None


def test_scan_is_case_insensitive_and_tolerates_stray_spacing(client, db_session):
    supplier_id = _create_ledger(client, name="Case Supplier")
    product_id = _create_product(client, db_session, sku="SER-SCAN-CASE")
    _stock_of(client, supplier_id, product_id, ["imei-Ab12"])

    for code in ("IMEI-AB12", "imei-ab12", "  IMEI-Ab12  "):
        response = client.get("/api/serials/scan", params={"code": code})
        assert response.status_code == 200, f"{code}: {response.text}"
        assert response.json()["kind"] == "serial"
        # The row is returned as it was received, not as it was scanned.
        assert response.json()["serial"]["serial_number"] == "imei-Ab12"


def test_scan_falls_back_to_an_exact_product_sku(client, db_session):
    product_id = _create_product(
        client, db_session, sku="CABLE-USBC", name="USB-C Cable",
        track_serials=False,
    )

    response = client.get("/api/serials/scan", params={"code": "CABLE-USBC"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "product"
    assert body["serial"] is None
    assert body["product"]["id"] == product_id
    assert body["product"]["sku"] == "CABLE-USBC"


def test_scan_sku_match_is_case_insensitive(client, db_session):
    product_id = _create_product(
        client, db_session, sku="CABLE-LOWER", track_serials=False
    )

    response = client.get("/api/serials/scan", params={"code": "cable-lower"})
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "product"
    assert response.json()["product"]["id"] == product_id


def test_scan_sku_match_must_be_exact_not_partial(client, db_session):
    _create_product(client, db_session, sku="CABLE-EXACT", track_serials=False)

    response = client.get("/api/serials/scan", params={"code": "CABLE"})
    assert response.status_code == 404, response.text


def test_scan_of_an_unknown_code_is_404_with_a_printable_message(client, db_session):
    _create_product(client, db_session, sku="SER-SCAN-404")

    response = client.get("/api/serials/scan", params={"code": "NOT-A-THING"})
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == 'No product or serial number found for "NOT-A-THING"'


def test_scan_does_not_resolve_a_voided_serial(client, db_session):
    supplier_id = _create_ledger(client, name="Scan Void Supplier")
    product_id = _create_product(client, db_session, sku="SER-SCAN-VOID")

    purchase = _create_invoice(
        client, supplier_id, "purchase", product_id, 1, ["VOIDED-1"]
    )
    assert client.delete(f"/api/invoices/{purchase['id']}").status_code == 200

    response = client.get("/api/serials/scan", params={"code": "VOIDED-1"})
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# GET /api/serials/
# ---------------------------------------------------------------------------

def test_list_serials_filters_by_product_and_status(client, db_session):
    supplier_id = _create_ledger(client, name="List Supplier")
    customer_id = _create_ledger(client, name="List Customer", gst="27ABCDE9999F1Z5")
    phone_id = _create_product(client, db_session, sku="SER-LIST-PHONE")
    tablet_id = _create_product(
        client, db_session, sku="SER-LIST-TABLET", name="iPad Air"
    )

    _stock_of(client, supplier_id, phone_id, ["P1", "P2", "P3"])
    _stock_of(client, supplier_id, tablet_id, ["T1"])
    _create_invoice(client, customer_id, "sales", phone_id, 1, ["P1"])

    by_product = client.get("/api/serials/", params={"product_id": phone_id})
    assert by_product.status_code == 200, by_product.text
    assert by_product.json()["total"] == 3
    assert {item["serial_number"] for item in by_product.json()["items"]} == {
        "P1", "P2", "P3"
    }

    in_stock = client.get(
        "/api/serials/", params={"product_id": phone_id, "status": "in_stock"}
    )
    assert in_stock.status_code == 200, in_stock.text
    assert [item["serial_number"] for item in in_stock.json()["items"]] == ["P2", "P3"]

    sold = client.get(
        "/api/serials/", params={"product_id": phone_id, "status": "sold"}
    )
    assert [item["serial_number"] for item in sold.json()["items"]] == ["P1"]
    assert sold.json()["items"][0]["sales_invoice"] is not None


def test_list_serials_is_oldest_first(client, db_session):
    supplier_id = _create_ledger(client, name="FIFO Supplier")
    product_id = _create_product(client, db_session, sku="SER-FIFO")

    _stock_of(client, supplier_id, product_id, ["OLD-1", "OLD-2"])
    _stock_of(client, supplier_id, product_id, ["NEW-1"])

    response = client.get(
        "/api/serials/", params={"product_id": product_id, "status": "in_stock"}
    )
    assert response.status_code == 200, response.text
    # FIFO: the shop moves the units it received first.
    assert [item["serial_number"] for item in response.json()["items"]] == [
        "OLD-1", "OLD-2", "NEW-1",
    ]


def test_list_serials_hides_voided_units_unless_asked_for(client, db_session):
    supplier_id = _create_ledger(client, name="List Void Supplier")
    product_id = _create_product(client, db_session, sku="SER-LIST-VOID")

    purchase = _create_invoice(
        client, supplier_id, "purchase", product_id, 1, ["GONE-1"]
    )
    assert client.delete(f"/api/invoices/{purchase['id']}").status_code == 200

    default = client.get("/api/serials/", params={"product_id": product_id})
    assert default.json()["total"] == 0

    voided = client.get(
        "/api/serials/", params={"product_id": product_id, "status": "void"}
    )
    assert [item["serial_number"] for item in voided.json()["items"]] == ["GONE-1"]


def test_list_serials_search_matches_a_partial_number(client, db_session):
    supplier_id = _create_ledger(client, name="Search Supplier")
    product_id = _create_product(client, db_session, sku="SER-SEARCH")

    _stock_of(
        client, supplier_id, product_id,
        ["356938035643809", "356938035643817", "999999999999999"],
    )

    response = client.get("/api/serials/", params={"search": "3809"})
    assert response.status_code == 200, response.text
    assert [item["serial_number"] for item in response.json()["items"]] == [
        "356938035643809"
    ]


# ---------------------------------------------------------------------------
# InvoiceItemOut.serial_numbers on the read paths
# ---------------------------------------------------------------------------

def test_serial_numbers_are_returned_on_create_detail_and_list(client, db_session):
    supplier_id = _create_ledger(client, name="Read Supplier")
    customer_id = _create_ledger(client, name="Read Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-READ")

    _stock_of(client, supplier_id, product_id, ["A1", "A2"])
    sale = _create_invoice(client, customer_id, "sales", product_id, 2, ["A1", "A2"])

    # create response
    assert sorted(_line_serials(sale)) == ["A1", "A2"]

    # detail endpoint
    detail = client.get(f"/api/invoices/{sale['id']}")
    assert detail.status_code == 200, detail.text
    assert sorted(_line_serials(detail.json())) == ["A1", "A2"]

    # list endpoint
    listing = client.get("/api/invoices/", params={"voucher_type": "sales"})
    assert listing.status_code == 200, listing.text
    listed = [inv for inv in listing.json()["items"] if inv["id"] == sale["id"]]
    assert len(listed) == 1
    assert sorted(_line_serials(listed[0])) == ["A1", "A2"]


def test_untracked_product_lines_carry_an_empty_serial_list(client, db_session):
    ledger_id = _create_ledger(client, name="Empty Serials Ledger")
    product_id = _create_product(
        client, db_session, sku="SER-READ-EMPTY", track_serials=False,
        initial_quantity=10,
    )

    sale = _create_invoice(client, ledger_id, "sales", product_id, 2)
    assert _line_serials(sale) == []

    detail = client.get(f"/api/invoices/{sale['id']}")
    assert _line_serials(detail.json()) == []


# ---------------------------------------------------------------------------
# Duplicating an invoice
# ---------------------------------------------------------------------------

def test_duplicating_an_invoice_does_not_copy_serials(client, db_session):
    supplier_id = _create_ledger(client, name="Dup Supplier")
    customer_id = _create_ledger(client, name="Dup Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-DUP")

    _stock_of(client, supplier_id, product_id, ["A1", "A2"])
    sale = _create_invoice(client, customer_id, "sales", product_id, 1, ["A1"])

    response = client.post(f"/api/invoices/{sale['id']}/duplicate")
    assert response.status_code == 200, response.text
    duplicate_id = response.json()["id"]

    duplicate = client.get(f"/api/invoices/{duplicate_id}")
    assert duplicate.status_code == 200, duplicate.text
    body = duplicate.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["product_id"] == product_id
    # Every unit is unique, so the duplicate starts empty and the shopkeeper
    # scans the handsets actually going out on it.
    assert _line_serials(body) == []

    # The original keeps its unit, and no row moved to the duplicate.
    assert _serial_row(db_session, "A1").sales_invoice_id == sale["id"]
    assert assert_serial_invariant(db_session, product_id) == 1


# ---------------------------------------------------------------------------
# Editing an invoice rejects a unit that is no longer available
# ---------------------------------------------------------------------------

def test_editing_a_sale_to_add_a_sold_serial_names_the_other_invoice(client, db_session):
    supplier_id = _create_ledger(client, name="Edit Supplier")
    customer_id = _create_ledger(client, name="Edit Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-EDIT-SOLD")

    _stock_of(client, supplier_id, product_id, ["A1", "A2"])
    other = _create_invoice(client, customer_id, "sales", product_id, 1, ["A2"])
    sale = _create_invoice(client, customer_id, "sales", product_id, 1, ["A1"])

    response = client.put(
        f"/api/invoices/{sale['id']}",
        json=_invoice_payload(customer_id, "sales", product_id, 2, ["A1", "A2"]),
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "Serial A2 has already been sold" in detail
    assert other["invoice_number"] in detail

    # The rejected edit left nothing behind.
    unchanged = client.get(f"/api/invoices/{sale['id']}")
    assert _line_serials(unchanged.json()) == ["A1"]
    assert _serial_row(db_session, "A2").sales_invoice_id == other["id"]
    assert assert_serial_invariant(db_session, product_id) == 0


def test_editing_a_purchase_to_add_a_registered_serial_is_rejected(client, db_session):
    supplier_id = _create_ledger(client, name="Edit Pur Supplier")
    product_id = _create_product(client, db_session, sku="SER-EDIT-REG")

    first = _create_invoice(client, supplier_id, "purchase", product_id, 1, ["A1"])
    second = _create_invoice(client, supplier_id, "purchase", product_id, 1, ["A2"])

    response = client.put(
        f"/api/invoices/{second['id']}",
        json=_invoice_payload(supplier_id, "purchase", product_id, 2, ["A2", "A1"]),
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "Serial A1 is already registered to iPhone 15 128GB" in detail
    assert first["invoice_number"] in detail
    assert assert_serial_invariant(db_session, product_id) == 2


def test_editing_a_sale_can_move_a_unit_to_a_different_product(client, db_session):
    supplier_id = _create_ledger(client, name="Swap Supplier")
    customer_id = _create_ledger(client, name="Swap Customer", gst="27ABCDE9999F1Z5")
    phone_id = _create_product(client, db_session, sku="SER-SWAP-PHONE")
    tablet_id = _create_product(
        client, db_session, sku="SER-SWAP-TABLET", name="iPad Air"
    )

    _stock_of(client, supplier_id, phone_id, ["P1"])
    _stock_of(client, supplier_id, tablet_id, ["T1"])
    sale = _create_invoice(client, customer_id, "sales", phone_id, 1, ["P1"])
    assert assert_serial_invariant(db_session, phone_id) == 0

    edited = _update_invoice(
        client, sale["id"], customer_id, "sales", tablet_id, 1, ["T1"]
    )
    assert _line_serials(edited) == ["T1"]
    assert _serial_row(db_session, "P1").status == STATUS_IN_STOCK
    assert _serial_row(db_session, "P1").sales_invoice_id is None
    assert _serial_row(db_session, "T1").status == STATUS_SOLD
    assert assert_serial_invariant(db_session, phone_id) == 1
    assert assert_serial_invariant(db_session, tablet_id) == 0


# ---------------------------------------------------------------------------
# Tenant scoping of the read routes
# ---------------------------------------------------------------------------

def _other_company(db_session):
    from src.models.company import CompanyProfile

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


def test_scan_does_not_reach_across_companies(client, db_session):
    supplier_id = _create_ledger(client, name="Tenant Supplier")
    product_id = _create_product(client, db_session, sku="SER-TENANT")
    _stock_of(client, supplier_id, product_id, ["ONLY-IN-A"])

    other_id = _other_company(db_session)

    mine = client.get("/api/serials/scan", params={"code": "ONLY-IN-A"})
    assert mine.status_code == 200, mine.text

    theirs = client.get(
        "/api/serials/scan",
        params={"code": "ONLY-IN-A"},
        headers={"X-Company-Id": str(other_id)},
    )
    assert theirs.status_code == 404, theirs.text


def test_list_serials_does_not_reach_across_companies(client, db_session):
    supplier_id = _create_ledger(client, name="Tenant List Supplier")
    product_id = _create_product(client, db_session, sku="SER-TENANT-LIST")
    _stock_of(client, supplier_id, product_id, ["A1", "A2"])

    other_id = _other_company(db_session)

    mine = client.get("/api/serials/")
    assert mine.json()["total"] == 2

    theirs = client.get("/api/serials/", headers={"X-Company-Id": str(other_id)})
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["total"] == 0
    assert theirs.json()["items"] == []


def test_editing_a_sale_to_a_quantity_the_serials_do_not_cover_is_rejected(client, db_session):
    """A tracked line's quantity is derived from its serials, so raising the
    quantity alone must report the serial count — not the stock shortfall that
    follows from it."""
    supplier_id = _create_ledger(client, name="Qty Edit Supplier")
    customer_id = _create_ledger(client, name="Qty Edit Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-EDIT-QTY")

    _stock_of(client, supplier_id, product_id, ["A1"])
    sale = _create_invoice(client, customer_id, "sales", product_id, 1, ["A1"])

    response = client.put(
        f"/api/invoices/{sale['id']}",
        json=_invoice_payload(customer_id, "sales", product_id, 5, ["A1"]),
    )
    assert response.status_code == 400, response.text
    assert (
        "needs 5 serial numbers for quantity 5 (1 provided)"
        in response.json()["detail"]
    )
    assert assert_serial_invariant(db_session, product_id) == 0


def test_editing_a_sale_reports_the_serial_count_when_stock_is_ample(client, db_session):
    """The companion to the case above: with enough stock behind it, the
    inventory delta succeeds and validation reports the real problem.  The two
    together pin the bug to the ordering, not to the message itself."""
    supplier_id = _create_ledger(client, name="Ample Supplier")
    customer_id = _create_ledger(client, name="Ample Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-EDIT-AMPLE")

    _stock_of(
        client, supplier_id, product_id, ["A1", "A2", "A3", "A4", "A5"]
    )
    sale = _create_invoice(client, customer_id, "sales", product_id, 1, ["A1"])

    response = client.put(
        f"/api/invoices/{sale['id']}",
        json=_invoice_payload(customer_id, "sales", product_id, 5, ["A1"]),
    )
    assert response.status_code == 400, response.text
    assert (
        "needs 5 serial numbers for quantity 5 (1 provided)"
        in response.json()["detail"]
    )
    assert assert_serial_invariant(db_session, product_id) == 4


def test_creating_a_sale_reports_the_serial_problem_before_the_stock_shortfall(client, db_session):
    """The create path gets this right — validate_for_items runs before the
    availability check, so a bad IMEI reports itself rather than the shortfall
    it causes."""
    supplier_id = _create_ledger(client, name="Order Supplier")
    customer_id = _create_ledger(client, name="Order Customer", gst="27ABCDE9999F1Z5")
    product_id = _create_product(client, db_session, sku="SER-ORDER")

    _stock_of(client, supplier_id, product_id, ["A1"])

    response = client.post(
        "/api/invoices/",
        json=_invoice_payload(customer_id, "sales", product_id, 5, ["A1"]),
    )
    assert response.status_code == 400, response.text
    assert (
        "needs 5 serial numbers for quantity 5 (1 provided)"
        in response.json()["detail"]
    )
    assert assert_serial_invariant(db_session, product_id) == 1
