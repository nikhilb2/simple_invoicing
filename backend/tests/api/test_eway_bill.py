"""
API-level tests for E-Way Bill routes.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi.testclient import TestClient
from app_main import app
from src.api.deps import get_current_user, get_active_company
from src.db.base import Base
from src.db.session import get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.eway_bill import EwayBillTransporter
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.user import User, UserRole


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def company(db):
    c = CompanyProfile(
        name="API Corp",
        address="123 API Road\nBangalore\n560001",
        gst="29AABCT1234Q1Z5",
        phone_number="9999999999",
        currency_code="INR",
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def client(db, company):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return User(
            id=1,
            email="test@example.com",
            role=UserRole.admin,
        )

    def override_get_active_company():
        return company

    # Snapshot the global overrides (set in conftest) so we restore them and don't
    # leak our per-test overrides into other test modules.
    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_active_company] = override_get_active_company

    yield TestClient(app)

    app.dependency_overrides = saved_overrides


@pytest.fixture
def buyer_with_gst(db, company):
    b = Buyer(
        name="GST Buyer",
        address="456 Buyer Lane\nMumbai\n400001",
        gst="27BBBCD5678R2Z9",
        phone_number="8888888888",
        company_id=company.id,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def product(db, company):
    p = Product(
        sku="EWB001",
        name="E-Way Product",
        price=100.0,
        gst_rate=18.0,
        unit="Pieces",
        description="Test product",
        company_id=company.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def invoice(db, company, buyer_with_gst, product):
    inv = Invoice(
        invoice_number="EWB-API-001",
        company_id=company.id,
        ledger_id=buyer_with_gst.id,
        ledger_name=buyer_with_gst.name,
        ledger_address=buyer_with_gst.address,
        ledger_gst=buyer_with_gst.gst,
        voucher_type="sales",
        status="active",
        created_by=1,
        taxable_amount=1000.00,
        cgst_amount=0.00,
        sgst_amount=0.00,
        igst_amount=180.00,
        total_amount=1180.00,
        company_name=company.name,
        company_address=company.address,
        company_gst=company.gst,
    )
    db.add(inv)
    db.flush()

    item = InvoiceItem(
        invoice_id=inv.id,
        product_id=product.id,
        hsn_sac="85176290",
        quantity=10.0,
        unit_price=100.00,
        gst_rate=18.0,
        taxable_amount=1000.00,
        tax_amount=180.00,
        cgst_amount=0.00,
        sgst_amount=0.00,
        igst_amount=180.00,
        line_total=1180.00,
    )
    db.add(item)
    db.flush()

    return inv


# ── Pre-check endpoint ──

def test_precheck_returns_200(client, invoice):
    resp = client.get(f"/api/invoices/{invoice.id}/eway-bill/precheck")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["form_data"]["seller_gstin"] == "29AABCT1234Q1Z5"
    assert data["form_data"]["buyer_gstin"] == "27BBBCD5678R2Z9"


def test_precheck_404_nonexistent(client):
    resp = client.get("/api/invoices/99999/eway-bill/precheck")
    assert resp.status_code == 404


def test_precheck_auto_fills_default_transporter(client, db, company, invoice):
    t = EwayBillTransporter(
        company_id=company.id,
        transporter_name="API Transporter",
        transporter_gstin="07TRNSP1234Q1Z5",
        transport_mode="1",
        vehicle_type="R",
        is_default=True,
    )
    db.add(t)
    db.flush()

    resp = client.get(f"/api/invoices/{invoice.id}/eway-bill/precheck")
    assert resp.status_code == 200
    data = resp.json()
    assert data["form_data"]["transporter_name"] == "API Transporter"


# ── Generate endpoint ──

def test_generate_json_200(client, invoice):
    form = {
        "seller_gstin": "29AABCT1234Q1Z5",
        "seller_trade_name": "API Corp",
        "seller_address_1": "123 API Road",
        "seller_place": "Karnataka",
        "seller_state_code": "29",
        "seller_pincode": "560001",
        "buyer_gstin": "27BBBCD5678R2Z9",
        "buyer_trade_name": "GST Buyer",
        "buyer_address_1": "456 Buyer Lane",
        "buyer_place": "Maharashtra",
        "buyer_state_code": "27",
        "buyer_pincode": "400001",
        "supply_type": "O",
        "sub_supply_type": "1",
        "transport_mode": "1",
        "distance_km": 100,
        "vehicle_number": "HR55AB1234",
    }
    resp = client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=form)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert 'attachment' in resp.headers.get("content-disposition", "")


def test_generate_json_422_validation_error(client, invoice):
    """Missing required fields should return 422."""
    form = {
        "seller_gstin": "",
        "seller_state_code": "",
        "buyer_gstin": "",
        "buyer_state_code": "",
        "supply_type": "",
        "sub_supply_type": "",
    }
    resp = client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=form)
    assert resp.status_code == 422


def test_generate_full_json_structure(client, invoice):
    form = {
        "seller_gstin": "29AABCT1234Q1Z5",
        "seller_trade_name": "API Corp",
        "seller_address_1": "123 API Road",
        "seller_address_2": "Bangalore",
        "seller_place": "Karnataka",
        "seller_state_code": "29",
        "seller_pincode": "560001",
        "buyer_gstin": "27BBBCD5678R2Z9",
        "buyer_trade_name": "GST Buyer",
        "buyer_address_1": "456 Buyer Lane",
        "buyer_address_2": "Mumbai",
        "buyer_place": "Maharashtra",
        "buyer_state_code": "27",
        "buyer_pincode": "400001",
        "supply_type": "O",
        "sub_supply_type": "1",
        "transport_mode": "1",
        "distance_km": 100,
        "vehicle_number": "HR55AB1234",
        "transporter_name": "Test Transport",
        "transporter_gstin": "07TRNSP1234Q1Z5",
        "vehicle_type": "R",
        "save_transporter": False,
    }
    resp = client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=form)
    assert resp.status_code == 200

    # Parse the JSON response body
    import json
    data = resp.json()

    assert data["version"] == "1.0.0621"
    assert len(data["billLists"]) == 1
    bill = data["billLists"][0]

    assert bill["docNo"] == "EWB-API-001"
    assert bill["docType"] == "INV"
    assert bill["fromGstin"] == "29AABCT1234Q1Z5"
    assert bill["toGstin"] == "27BBBCD5678R2Z9"
    assert bill["fromStateCode"] == 29
    assert bill["toStateCode"] == 27
    assert bill["fromPincode"] == 560001
    assert bill["toPincode"] == 400001
    assert bill["transMode"] == 1
    assert bill["transDistance"] == 100
    assert bill["vehicleNo"] == "HR55AB1234"
    assert bill["transporterName"] == "Test Transport"
    assert bill["transporterId"] == "07TRNSP1234Q1Z5"
    assert len(bill["itemList"]) == 1


def test_generate_saves_transporter(client, db, company, invoice):
    form = {
        "seller_gstin": "29AABCT1234Q1Z5",
        "seller_trade_name": "API Corp",
        "seller_address_1": "123 API Road",
        "seller_place": "Karnataka",
        "seller_state_code": "29",
        "seller_pincode": "560001",
        "buyer_gstin": "27BBBCD5678R2Z9",
        "buyer_trade_name": "GST Buyer",
        "buyer_address_1": "456 Buyer Lane",
        "buyer_place": "Maharashtra",
        "buyer_state_code": "27",
        "buyer_pincode": "400001",
        "supply_type": "O",
        "sub_supply_type": "1",
        "transport_mode": "1",
        "distance_km": 100,
        "transporter_name": "Saved Transporter",
        "transporter_gstin": "07SAVED1111Q1Z5",
        "vehicle_number": "HR55AB1234",
        "save_transporter": True,
    }
    resp = client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=form)
    assert resp.status_code == 200

    # Verify transporter was saved
    transporter = (
        db.query(EwayBillTransporter)
        .filter(
            EwayBillTransporter.company_id == company.id,
            EwayBillTransporter.transporter_name == "Saved Transporter",
        )
        .first()
    )
    assert transporter is not None
    assert transporter.transporter_gstin == "07SAVED1111Q1Z5"
    assert transporter.is_default is True


# ── Transporter CRUD endpoints ──

def test_list_transporters_empty(client):
    resp = client.get("/api/eway-bill/transporters")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_transporters(client, db, company):
    t1 = EwayBillTransporter(
        company_id=company.id,
        transporter_name="ABC Logistics",
        transport_mode="1",
        vehicle_type="R",
        is_default=True,
    )
    t2 = EwayBillTransporter(
        company_id=company.id,
        transporter_name="XYZ Cargo",
        transport_mode="3",
        vehicle_type="R",
        is_default=False,
    )
    db.add_all([t1, t2])
    db.flush()

    resp = client.get("/api/eway-bill/transporters")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # Default first
    assert data[0]["transporter_name"] == "ABC Logistics"


def test_create_transporter(client, db, company):
    resp = client.post("/api/eway-bill/transporters", json={
        "transporter_name": "New Transport",
        "transporter_gstin": "07NEWTP1234Q1Z5",
        "transport_mode": "1",
        "vehicle_type": "R",
        "is_default": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["transporter_name"] == "New Transport"
    assert data["is_default"] is True


def test_update_transporter(client, db, company):
    t = EwayBillTransporter(
        company_id=company.id,
        transporter_name="Old Name",
        transport_mode="1",
        vehicle_type="R",
    )
    db.add(t)
    db.flush()

    resp = client.put(f"/api/eway-bill/transporters/{t.id}", json={
        "transporter_name": "Updated Name",
        "transport_mode": "2",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["transporter_name"] == "Updated Name"
    assert data["transport_mode"] == "2"


def test_delete_transporter(client, db, company):
    t = EwayBillTransporter(
        company_id=company.id,
        transporter_name="To Delete",
        transport_mode="1",
        vehicle_type="R",
    )
    db.add(t)
    db.flush()

    resp = client.delete(f"/api/eway-bill/transporters/{t.id}")
    assert resp.status_code == 200

    # Verify gone
    resp2 = client.get("/api/eway-bill/transporters")
    assert len(resp2.json()) == 0


# ── Settings endpoint ──

def test_eway_bill_settings_defaults(client):
    """Settings endpoint should return default values."""
    resp = client.get("/api/eway-bill/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["eway_enabled"] is True
    assert data["eway_local_threshold"] == 50000
    assert data["eway_interstate_threshold"] == 50000
    assert data["eway_always_show_button"] is True


# ── Shared eligibility checks ──

def _valid_form(**overrides) -> dict:
    form = {
        "seller_gstin": "29AABCT1234Q1Z5",
        "seller_trade_name": "API Corp",
        "seller_address_1": "123 API Road",
        "seller_place": "Karnataka",
        "seller_state_code": "29",
        "seller_pincode": "560001",
        "buyer_gstin": "27BBBCD5678R2Z9",
        "buyer_trade_name": "GST Buyer",
        "buyer_address_1": "456 Buyer Lane",
        "buyer_place": "Maharashtra",
        "buyer_state_code": "27",
        "buyer_pincode": "400001",
        "distance_km": 100,
        "vehicle_number": "HR55AB1234",
    }
    form.update(overrides)
    return form


def _routes(client, invoice_id):
    return {
        "precheck": lambda: client.get(f"/api/invoices/{invoice_id}/eway-bill/precheck"),
        "generate": lambda: client.post(f"/api/invoices/{invoice_id}/eway-bill/generate", json=_valid_form()),
    }


@pytest.mark.parametrize("route", ["precheck", "generate"])
def test_both_routes_refuse_a_purchase_invoice(client, db, invoice, route):
    invoice.voucher_type = "purchase"
    db.flush()
    resp = _routes(client, invoice.id)[route]()
    assert resp.status_code == 400
    assert resp.json()["detail"] == "E-Way Bill is only available for Sales invoices."


@pytest.mark.parametrize("route", ["precheck", "generate"])
def test_both_routes_refuse_a_cancelled_invoice(client, db, invoice, route):
    invoice.status = "cancelled"
    db.flush()
    resp = _routes(client, invoice.id)[route]()
    assert resp.status_code == 400
    assert "active invoices" in resp.json()["detail"]


@pytest.mark.parametrize("route", ["precheck", "generate"])
def test_both_routes_stop_when_eway_bills_are_turned_off(client, db, company, invoice, route):
    company.eway_enabled = False
    db.flush()
    resp = _routes(client, invoice.id)[route]()
    assert resp.status_code == 400
    assert "turned off" in resp.json()["detail"]


@pytest.mark.parametrize("route", ["precheck", "generate"])
def test_both_routes_404_an_invoice_of_another_company(client, db, invoice, route):
    other = CompanyProfile(name="Other", address="x", gst="", phone_number="1", currency_code="INR")
    db.add(other)
    db.flush()
    invoice.company_id = other.id
    db.flush()
    resp = _routes(client, invoice.id)[route]()
    assert resp.status_code == 404
    assert resp.json()["detail"] == f"Invoice {invoice.id} not found"


# ── Error responses the form reads ──

def test_generate_422_names_each_field_with_a_plain_message(client, invoice):
    resp = client.post(
        f"/api/invoices/{invoice.id}/eway-bill/generate",
        json=_valid_form(seller_gstin="BAD", seller_pincode="", buyer_pincode="12"),
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["message"] == "Some E-Way Bill details need fixing."
    by_field = {e["field"]: e["message"] for e in detail["errors"]}
    assert set(by_field) == {"seller_gstin", "seller_pincode", "buyer_pincode"}
    assert by_field["seller_pincode"] == "Seller PIN code is required."
    assert by_field["buyer_pincode"] == "Buyer PIN code must be 6 digits and can't start with 0."


def test_generate_refuses_blank_pins_rather_than_writing_zero(client, invoice):
    resp = client.post(
        f"/api/invoices/{invoice.id}/eway-bill/generate",
        json=_valid_form(seller_pincode="", buyer_pincode=""),
    )
    assert resp.status_code == 422


def test_generate_refuses_a_missing_hsn(client, db, invoice):
    invoice.items[0].hsn_sac = None
    db.flush()
    resp = client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=_valid_form())
    assert resp.status_code == 422
    assert "missing HSN/SAC" in resp.json()["detail"]["errors"][0]["message"]


def test_generate_fastapi_validation_is_a_detail_list(client, invoice):
    resp = client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=_valid_form(distance_km=1.5))
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"] == ["body", "distance_km"]


def test_generate_500_does_not_leak_the_exception(client, invoice, monkeypatch, caplog):
    import src.api.routes.eway_bill as routes

    def boom(*args, **kwargs):
        raise RuntimeError("SECRET-DB-DETAIL")

    monkeypatch.setattr(routes, "generate_eway_bill_json", boom)
    resp = client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=_valid_form())
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to generate E-Way Bill JSON"
    assert "SECRET-DB-DETAIL" not in resp.text
    assert "SECRET-DB-DETAIL" in caplog.text  # logged for whoever is debugging it


def test_generate_writes_a_valid_unit_code(client, invoice):
    resp = client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=_valid_form())
    assert resp.status_code == 200
    # The fixture's product uses the default unit, Pieces, which used to come out as PIE.
    assert resp.json()["billLists"][0]["itemList"][0]["qtyUnit"] == "NOS"


# ── Default transporter ──

def test_generate_saving_over_an_existing_transporter_clears_the_old_default(client, db, company, invoice):
    db.add_all([
        EwayBillTransporter(company_id=company.id, transporter_name="Old Default", is_default=True),
        EwayBillTransporter(company_id=company.id, transporter_name="Existing", is_default=False),
    ])
    db.flush()

    resp = client.post(
        f"/api/invoices/{invoice.id}/eway-bill/generate",
        json=_valid_form(transporter_name="Existing", save_transporter=True),
    )
    assert resp.status_code == 200

    db.expire_all()
    defaults = db.query(EwayBillTransporter).filter_by(company_id=company.id, is_default=True).all()
    assert [t.transporter_name for t in defaults] == ["Existing"]


def test_update_transporter_clears_the_old_default(client, db, company):
    old_default = EwayBillTransporter(company_id=company.id, transporter_name="Old Default", is_default=True)
    other = EwayBillTransporter(company_id=company.id, transporter_name="Other", is_default=False)
    db.add_all([old_default, other])
    db.flush()

    resp = client.put(f"/api/eway-bill/transporters/{other.id}", json={"is_default": True})
    assert resp.status_code == 200

    db.expire_all()
    assert old_default.is_default is False
    assert other.is_default is True


def test_transporter_input_is_validated(client):
    resp = client.post("/api/eway-bill/transporters", json={"transporter_name": "T", "transporter_gstin": "TOO-SHORT"})
    assert resp.status_code == 422
    resp = client.post("/api/eway-bill/transporters", json={"transporter_name": "T", "transport_mode": "9"})
    assert resp.status_code == 422
    resp = client.post("/api/eway-bill/transporters", json={"transporter_name": ""})
    assert resp.status_code == 422


# ── Permissions ──

@pytest.fixture
def as_role(client):
    def switch(role):
        app.dependency_overrides[get_current_user] = lambda: User(id=1, email="t@example.com", role=role)
    return switch


def _stored_transporter(db, company, **kwargs):
    transporter = EwayBillTransporter(company_id=company.id, transporter_name="Stored", **kwargs)
    db.add(transporter)
    db.flush()
    return transporter


@pytest.mark.parametrize("role, allowed", [
    (UserRole.admin, True),
    (UserRole.manager, True),
    (UserRole.staff, False),
])
def test_transporter_writes_need_admin_or_manager(client, db, company, as_role, role, allowed):
    as_role(role)
    transporter = _stored_transporter(db, company)

    created = client.post("/api/eway-bill/transporters", json={"transporter_name": "New"})
    updated = client.put(f"/api/eway-bill/transporters/{transporter.id}", json={"transporter_name": "Renamed"})
    deleted = client.delete(f"/api/eway-bill/transporters/{transporter.id}")

    for resp in (created, updated, deleted):
        assert resp.status_code == (200 if allowed else 403)


def test_staff_can_generate_and_read_but_not_save_a_transporter(client, db, company, invoice, as_role):
    as_role(UserRole.staff)
    _stored_transporter(db, company)

    assert client.get(f"/api/invoices/{invoice.id}/eway-bill/precheck").status_code == 200
    assert client.get("/api/eway-bill/transporters").status_code == 200
    assert client.post(f"/api/invoices/{invoice.id}/eway-bill/generate", json=_valid_form()).status_code == 200

    resp = client.post(
        f"/api/invoices/{invoice.id}/eway-bill/generate",
        json=_valid_form(transporter_name="Sneaky", save_transporter=True),
    )
    assert resp.status_code == 403
    assert "admin or manager" in resp.json()["detail"]
    assert db.query(EwayBillTransporter).filter_by(transporter_name="Sneaky").first() is None


# ── Ship-to, end to end ──

def test_precheck_fills_delivery_from_the_shipping_address(client, db, invoice):
    invoice.shipping_address = "Warehouse 9\nPune\n411001"
    db.flush()
    data = client.get(f"/api/invoices/{invoice.id}/eway-bill/precheck").json()
    assert data["form_data"]["transaction_type"] == "2"
    assert data["form_data"]["buyer_address_1"] == "Warehouse 9"
    assert data["form_data"]["buyer_pincode"] == "411001"
    assert data["form_data"]["buyer_trade_name"] == "GST Buyer"


# ── Tenant scoping ──

def test_another_companys_transporter_is_out_of_reach(client, db):
    other = CompanyProfile(name="Other", address="x", gst="", phone_number="1", currency_code="INR")
    db.add(other)
    db.flush()
    theirs = EwayBillTransporter(company_id=other.id, transporter_name="Theirs", is_default=True)
    db.add(theirs)
    db.flush()

    assert client.get("/api/eway-bill/transporters").json() == []
    assert client.put(f"/api/eway-bill/transporters/{theirs.id}", json={"transporter_name": "Mine"}).status_code == 404
    assert client.delete(f"/api/eway-bill/transporters/{theirs.id}").status_code == 404
    assert theirs.transporter_name == "Theirs"


def test_setting_a_default_leaves_another_companys_default_alone(client, db):
    other = CompanyProfile(name="Other", address="x", gst="", phone_number="1", currency_code="INR")
    db.add(other)
    db.flush()
    theirs = EwayBillTransporter(company_id=other.id, transporter_name="Theirs", is_default=True)
    db.add(theirs)
    db.flush()

    assert client.post("/api/eway-bill/transporters", json={"transporter_name": "Mine", "is_default": True}).status_code == 200

    db.expire_all()
    assert theirs.is_default is True
