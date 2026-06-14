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

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_active_company] = override_get_active_company

    yield TestClient(app)

    app.dependency_overrides.clear()


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
        cgst_amount=90.00,
        sgst_amount=90.00,
        igst_amount=0.00,
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
        cgst_amount=90.00,
        sgst_amount=90.00,
        igst_amount=0.00,
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
        "sub_supply_type": "Supply",
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
        "sub_supply_type": "Supply",
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

    assert data["version"] == "1.0.1118"
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
        "sub_supply_type": "Supply",
        "transport_mode": "1",
        "distance_km": 100,
        "transporter_name": "Saved Transporter",
        "transporter_gstin": "07SAVED1111Q1Z5",
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
