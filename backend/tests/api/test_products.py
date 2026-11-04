import pytest
from fastapi.testclient import TestClient

from app_main import app
from src.core.config import settings
from src.models.bom import BillOfMaterial
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.marketplace import MarketplaceListing, MarketplaceOrder, MarketplaceOrderItem, MarketplaceProductLink
from src.models.product import Product
from src.models.product_serial import ProductSerial
from src.models.production_transaction import ProductionTransaction
from src.models.user import User, UserRole


@pytest.fixture
def deletion_products(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "single_tenant")
    sqlite = db_session.get_bind().dialect.name == "sqlite"
    if sqlite:
        connection = db_session.connection()
        previous_foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    db_session.add(CompanyProfile(id=1, name="Deletion Test Co", address=""))
    db_session.add(User(id=1, email="test@example.com", full_name="Tester", hashed_password="x", role=UserRole.admin))
    db_session.commit()
    sequence = 0

    def make_product(name="Delete Test Product", **kwargs):
        nonlocal sequence
        sequence += 1
        product = Product(company_id=1, sku=f"DELETE-{sequence}", name=name, price=10, **kwargs)
        db_session.add(product)
        db_session.flush()
        db_session.add(Inventory(company_id=1, product_id=product.id, quantity=5))
        db_session.commit()
        return product

    try:
        yield make_product
    finally:
        db_session.rollback()
        if sqlite:
            connection = db_session.connection()
            setting = "ON" if previous_foreign_keys else "OFF"
            connection.exec_driver_sql(f"PRAGMA foreign_keys={setting}")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == previous_foreign_keys
            db_session.rollback()


def _product_reference(db_session, product, kind, make_product):
    if kind == "serial":
        product.track_serials = True
        db_session.query(Inventory).filter_by(product_id=product.id).one().quantity = 1
        reference = ProductSerial(company_id=1, product_id=product.id, serial_number="DELETE-SERIAL")
    elif kind == "listing":
        reference = MarketplaceListing(company_id=1, product_id=product.id, title=product.name)
    elif kind == "link":
        reference = MarketplaceProductLink(company_id=1, product_id=product.id, remote_listing_id="delete-listing")
    elif kind == "order_item":
        order = MarketplaceOrder(company_id=1, side="buy", remote_order_id="delete-order", state="posted")
        db_session.add(order)
        db_session.flush()
        reference = MarketplaceOrderItem(order_id=order.id, line_no=1, product_id=product.id,
                                         quantity=1, unit_price=10)
    elif kind == "bom":
        parent = make_product("Parent product", is_producable=True)
        reference = BillOfMaterial(company_id=1, product_id=parent.id, component_product_id=product.id, quantity_required=1)
    else:
        product.is_producable = True
        reference = ProductionTransaction(company_id=1, product_id=product.id, quantity_produced=1, user_id=1)
    db_session.add(reference)
    db_session.commit()
    return reference


@pytest.mark.parametrize("kind,reason", [
    ("serial", "serial"), ("listing", "marketplace"), ("link", "marketplace"),
    ("order_item", "marketplace orders"),
    ("bom", "bill of materials"), ("production", "production"),
])
@pytest.mark.parametrize("references_target", [True, False])
def test_delete_product_preserves_referenced_products_and_history(
    db_session, deletion_products, kind, reason, references_target,
):
    target = deletion_products()
    referenced = target if references_target else deletion_products("Other product")
    reference = _product_reference(db_session, referenced, kind, deletion_products)
    target_id, referenced_id, reference_id = target.id, referenced.id, reference.id
    original_quantity = db_session.query(Inventory).filter_by(product_id=target_id).one().quantity

    response = TestClient(app, raise_server_exceptions=False).delete(f"/api/products/{target_id}")

    assert response.status_code == (400 if references_target else 200), response.text
    if references_target:
        assert reason in response.json()["detail"].lower()
        if kind == "bom":
            assert "Parent product" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.get(type(reference), reference_id) is not None
    assert db_session.get(Product, referenced_id) is not None
    if references_target:
        assert db_session.query(Inventory).filter_by(product_id=target_id).one().quantity == original_quantity
    else:
        assert db_session.get(Product, target_id) is None
        assert db_session.query(Inventory).filter_by(product_id=target_id).first() is None


@pytest.mark.parametrize("status", ["sold", "void"])
def test_delete_product_keeps_historical_serial_rows(db_session, deletion_products, status):
    product = deletion_products()
    serial = _product_reference(db_session, product, "serial", deletion_products)
    serial.status = status
    db_session.query(Inventory).filter_by(product_id=product.id).one().quantity = 0
    db_session.commit()
    product_id, serial_id = product.id, serial.id

    response = TestClient(app, raise_server_exceptions=False).delete(f"/api/products/{product_id}")

    assert response.status_code == 400, response.text
    assert "serial" in response.json()["detail"].lower()
    db_session.expire_all()
    assert db_session.get(ProductSerial, serial_id).status == status
    assert db_session.get(Product, product_id) is not None


def test_delete_product_with_only_its_own_bom_removes_the_recipe(db_session, deletion_products):
    parent = deletion_products("Finished product", is_producable=True)
    component = deletion_products("Component")
    recipe = BillOfMaterial(company_id=1, product_id=parent.id, component_product_id=component.id, quantity_required=1)
    db_session.add(recipe)
    db_session.commit()
    parent_id, component_id, recipe_id = parent.id, component.id, recipe.id

    response = TestClient(app, raise_server_exceptions=False).delete(f"/api/products/{parent_id}")

    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert db_session.get(Product, parent_id) is None
    assert db_session.get(BillOfMaterial, recipe_id) is None
    assert db_session.get(Product, component_id) is not None


def test_delete_product_without_references_still_deletes(db_session, deletion_products):
    product_id = deletion_products().id

    response = TestClient(app, raise_server_exceptions=False).delete(f"/api/products/{product_id}")

    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert db_session.get(Product, product_id) is None


def test_delete_product_in_another_company_stays_not_found(db_session, deletion_products):
    deletion_products()
    db_session.add(CompanyProfile(id=2, name="Other Company", address=""))
    db_session.flush()
    foreign = Product(company_id=2, sku="FOREIGN-DELETE", name="Other private product", price=10, track_serials=True)
    db_session.add(foreign)
    db_session.flush()
    db_session.add(ProductSerial(company_id=2, product_id=foreign.id, serial_number="FOREIGN-SERIAL"))
    db_session.commit()
    product_id = foreign.id

    response = TestClient(app, raise_server_exceptions=False).delete(f"/api/products/{product_id}")

    assert response.status_code == 404, response.text
    assert "Other private product" not in response.text
    db_session.expire_all()
    assert db_session.get(Product, product_id) is not None


def test_delete_product_names_all_parent_recipes_without_removing_them(db_session, deletion_products):
    component = deletion_products("Shared component")
    parents = [deletion_products(name, is_producable=True) for name in ("Chair", "Table")]
    recipes = [BillOfMaterial(
        company_id=1, product_id=parent.id, component_product_id=component.id, quantity_required=1,
    ) for parent in parents]
    db_session.add_all(recipes)
    db_session.commit()
    component_id = component.id
    recipe_ids = [recipe.id for recipe in recipes]

    response = TestClient(app, raise_server_exceptions=False).delete(f"/api/products/{component_id}")

    assert response.status_code == 400, response.text
    assert "Chair" in response.json()["detail"]
    assert "Table" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.get(Product, component_id) is not None
    assert all(db_session.get(BillOfMaterial, recipe_id) is not None for recipe_id in recipe_ids)


def test_create_product(client):
    response = client.post("/api/products/", json={
        "sku": "SKU01",
        "name": "Test",
        "price": 10,
        "gst_rate": 18
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["unit"] == "Pieces"
    assert payload["allow_decimal"] is False
 

def test_duplicate_sku(client):
    data = {
        "sku": "DUP1",
        "name": "Test",
        "price": 10,
        "gst_rate": 18
    }

    client.post("/api/products/", json=data)
    response = client.post("/api/products/", json=data)

    assert response.status_code == 400

# Returns 400 when GST value is wrong for higher and lower ends
def test_invalid_gst(client):
    response = client.post('/api/products/', json={
        "sku": "PRO100",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": 110
    })

    assert response.status_code == 400

    response = client.post('/api/products/', json={
        "sku": "PRO101",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": -10
    })

    assert response.status_code == 400


def test_create_product_rejects_nan_gst_rate(client):
    response = client.post(
        "/api/products/",
        content='{"sku": "PRO102", "name": "TestProduct", "price": 100, "gst_rate": NaN}',
        headers={"Content-Type": "application/json"},
    )
    # Non-finite numbers fail request validation (422), not the later gst_rate range check.
    assert response.status_code == 422
    assert "detail" in response.json()

    listing = client.get("/api/products/")
    assert listing.status_code == 200
    assert all(item["sku"] != "PRO102" for item in listing.json()["items"])


def test_update_product_rejects_nan_gst_rate(client):
    created = client.post("/api/products/", json={
        "sku": "PRO103",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": 18,
    })
    assert created.status_code == 200
    product_id = created.json()["id"]

    response = client.put(
        f"/api/products/{product_id}",
        content='{"sku": "PRO103", "name": "TestProduct", "price": 100, "gst_rate": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "detail" in response.json()

    current = client.get(f"/api/products/{product_id}")
    assert current.status_code == 200
    assert current.json()["gst_rate"] == 18


def test_update_product_with_inventory_rejects_nan_gst_rate(client):
    created = client.post("/api/products/", json={
        "sku": "PRO104",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": 5,
        "initial_quantity": 2,
    })
    assert created.status_code == 200
    product_id = created.json()["id"]

    response = client.put(
        f"/api/products/{product_id}/with-inventory",
        content='{"gst_rate": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "detail" in response.json()

    current = client.get(f"/api/products/{product_id}")
    assert current.status_code == 200
    assert current.json()["gst_rate"] == 5


@pytest.mark.parametrize("overrides", [
    {"price": -1},
    {"purchase_price": -1},
    {"reorder_level": -1},
    {"initial_quantity": -1},
    {"production_cost": -1},
    {"name": "   "},
    {"sku": "   "},
])
def test_create_product_rejects_negative_values_and_blank_names(client, overrides):
    payload = {
        "sku": "NEG100",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": 18,
    }
    payload.update(overrides)

    response = client.post('/api/products/', json=payload)

    assert response.status_code == 422


def test_create_product_accepts_zero_price_and_zero_purchase_price(client):
    response = client.post('/api/products/', json={
        "sku": "FREE100",
        "name": "FreeItem",
        "price": 0,
        "purchase_price": 0,
        "gst_rate": 18,
    })

    assert response.status_code == 200


def test_update_product_rejects_negative_price_and_blank_name(client):
    create_response = client.post('/api/products/', json={
        "sku": "EDIT100",
        "name": "Editable",
        "price": 100,
        "gst_rate": 18,
    })
    assert create_response.status_code == 200
    product_id = create_response.json()["id"]

    base = {
        "sku": "EDIT100",
        "name": "Editable",
        "price": 100,
        "gst_rate": 18,
    }

    response = client.put(f"/api/products/{product_id}", json={**base, "price": -1})
    assert response.status_code == 422

    response = client.put(f"/api/products/{product_id}", json={**base, "name": "   "})
    assert response.status_code == 422


def test_update_product_with_inventory_rejects_negative_prices_and_blank_name(client):
    create_response = client.post('/api/products/', json={
        "sku": "EDIT200",
        "name": "EditableTwo",
        "price": 100,
        "gst_rate": 18,
    })
    assert create_response.status_code == 200
    product_id = create_response.json()["id"]
    url = f"/api/products/{product_id}/with-inventory"

    assert client.put(url, json={"selling_price": -1}).status_code == 422
    assert client.put(url, json={"purchase_price": -1}).status_code == 422
    assert client.put(url, json={"reorder_level": -1}).status_code == 422
    assert client.put(url, json={"name": "   "}).status_code == 422

# Creates a test product and tries to get the data back.
def test_get_products(client):
    client.post('/api/products/', json={
        "sku": "PRO123",
        "name": "TestProduct",
        "price": 100,
        "gst_rate": 5
    })

    response = client.get("/api/products/")

    assert response.status_code == 200

def test_search_products(client):
    client.post("/api/products/", json={
        "sku": "S1",
        "name": "Apple",
        "price": 10,
        "gst_rate": 5
    })

    response = client.get("/api/products/?search=Apple")

    assert response.status_code == 200


def test_create_untracked_product_skips_inventory(client, db_session):
    response = client.post(
        "/api/products/",
        json={
            "sku": "SERV001",
            "name": "Service Charge",
            "price": 250,
            "gst_rate": 18,
            "maintain_inventory": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["maintain_inventory"] is False

    from src.models.inventory import Inventory

    inventory = db_session.query(Inventory).filter(Inventory.product_id == payload["id"]).first()
    assert inventory is None


def test_create_untracked_product_rejects_initial_quantity(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "SERV002",
            "name": "Service Charge",
            "price": 100,
            "gst_rate": 18,
            "maintain_inventory": False,
            "initial_quantity": 10,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Initial quantity is only allowed when maintain inventory is enabled"


def test_toggle_untracked_product_on_creates_inventory_row(client, db_session):
    create_response = client.post(
        "/api/products/",
        json={
            "sku": "SERV003",
            "name": "AMC Plan",
            "price": 499,
            "gst_rate": 18,
            "maintain_inventory": False,
        },
    )
    assert create_response.status_code == 200
    product_id = create_response.json()["id"]

    update_response = client.put(
        f"/api/products/{product_id}",
        json={
            "sku": "SERV003",
            "name": "AMC Plan",
            "price": 499,
            "gst_rate": 18,
            "maintain_inventory": True,
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["maintain_inventory"] is True

    from src.models.inventory import Inventory

    inventory = db_session.query(Inventory).filter(Inventory.product_id == product_id).first()
    assert inventory is not None
    assert inventory.quantity == 0


def test_create_product_with_custom_unit_and_allow_decimal(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "UNITKG1",
            "name": "Fine Flour",
            "price": 45,
            "gst_rate": 5,
            "unit": "Kg",
            "allow_decimal": True,
            "maintain_inventory": True,
            "initial_quantity": 2.75,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["unit"] == "Kg"
    assert payload["allow_decimal"] is True


def test_reject_fractional_initial_quantity_when_decimal_disabled(client):
    response = client.post(
        "/api/products/",
        json={
            "sku": "WHOLEONLY1",
            "name": "Whole Unit Item",
            "price": 30,
            "gst_rate": 5,
            "unit": "Pieces",
            "allow_decimal": False,
            "maintain_inventory": True,
            "initial_quantity": 1.25,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Initial quantity must be a whole number for this product"

UNKNOWN_HSN = {"sku": "HSN1", "name": "CPU", "price": 10, "gst_rate": 18, "hsn_sac": "84733000"}


def test_saving_a_product_warns_about_an_hsn_gst_does_not_list_but_still_saves(client):
    created = client.post("/api/products/", json=UNKNOWN_HSN)

    assert created.status_code == 200
    assert created.json()["hsn_sac"] == "84733000"
    assert "84733000 is not on GST's list" in created.json()["hsn_warning"]

    corrected = client.put(f"/api/products/{created.json()['id']}", json={**UNKNOWN_HSN, "hsn_sac": "84733020"})
    assert corrected.status_code == 200
    assert corrected.json()["hsn_warning"] is None


def test_a_product_with_no_hsn_has_no_warning(client):
    created = client.post("/api/products/", json={**UNKNOWN_HSN, "hsn_sac": None})

    assert created.json()["hsn_warning"] is None


def test_the_with_inventory_update_warns_too(client):
    created = client.post("/api/products/", json={**UNKNOWN_HSN, "hsn_sac": "84733020"}).json()

    updated = client.put(f"/api/products/{created['id']}/with-inventory", json={"hsn_sac": "84733000"})

    assert updated.status_code == 200
    assert "84733000" in updated.json()["hsn_warning"]


def test_csv_import_saves_the_row_and_reports_an_hsn_gst_does_not_list(client):
    csv_content = (
        "Item Name,Item Code,Selling Price,Current Stock,Tax,HSN Code\n"
        "Good,IMP1,10,1,18,84733020\n"
        "Bad,IMP2,10,1,18,84733000\n"
        "Blank,IMP3,10,1,18,\n"
    )

    res = client.post("/api/products/import-csv", files={"file": ("p.csv", csv_content.encode(), "text/csv")})

    data = res.json()
    assert data["created"] == 3
    assert [e["row"] for e in data["errors"]] == [3]
    assert "IMP2 was saved" in data["errors"][0]["message"]
