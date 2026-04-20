from unittest.mock import patch

from src.models.inventory import Inventory


def _create_ledger(client, name: str, gst: str):
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


def _create_product(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "UPD-INV-001",
            "name": "Inventory Update Product",
            "description": "",
            "hsn_sac": "9988",
            "price": 100,
            "gst_rate": 18,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_invoice(client, ledger_id: int, voucher_type: str, product_id: int, quantity: int):
    response = client.post(
        "/api/invoices/",
        json={
            "ledger_id": ledger_id,
            "voucher_type": voucher_type,
            "tax_inclusive": False,
            "apply_round_off": False,
            "items": [{"product_id": product_id, "quantity": quantity, "unit_price": 100}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_update_purchase_invoice_succeeds_when_current_inventory_is_zero(client, db_session):
    invoice_numbers = iter(["PUR-000001", "SAL-000001"])
    with patch(
        "src.api.routes.invoices._generate_next_number",
        side_effect=lambda *args, **kwargs: next(invoice_numbers),
    ):
        purchase_ledger_id = _create_ledger(client, name="Purchase Ledger", gst="27ABCDE1234F1Z5")
        sales_ledger_id = _create_ledger(client, name="Sales Ledger", gst="27ABCDE9999F1Z5")
        product_id = _create_product(client)

        purchase_invoice = _create_invoice(
            client,
            ledger_id=purchase_ledger_id,
            voucher_type="purchase",
            product_id=product_id,
            quantity=10,
        )

        _create_invoice(
            client,
            ledger_id=sales_ledger_id,
            voucher_type="sales",
            product_id=product_id,
            quantity=10,
        )

        inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
        assert inventory is not None
        assert inventory.quantity == 0

        update_response = client.put(
            f"/api/invoices/{purchase_invoice['id']}",
            json={
                "ledger_id": purchase_ledger_id,
                "voucher_type": "purchase",
                "tax_inclusive": False,
                "apply_round_off": False,
                "items": [{"product_id": product_id, "quantity": 12, "unit_price": 100}],
            },
        )

        assert update_response.status_code == 200, update_response.text

        db_session.expire_all()
        updated_inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
        assert updated_inventory is not None
        assert updated_inventory.quantity == 2
