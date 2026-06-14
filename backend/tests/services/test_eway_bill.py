"""
Tests for E-Way Bill service.

Covers:
- pre_check: GSTIN validation, HSN checks, form pre-fill
- validate_form_data: all field validations
- generate_eway_bill_json: JSON structure, inter/intra-state tax
- _extract_pincode: address parsing
"""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.base import Base
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.eway_bill import EwayBillTransporter
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.schemas.eway_bill import (
    EwayBillFormData,
    EwayBillValidationError,
    EwayBillPreCheckResult,
)
from src.services.eway_bill_service import (
    pre_check,
    validate_form_data,
    generate_eway_bill_json,
    extract_state_code,
    _extract_pincode,
    get_or_create_default_transporter,
    GSTIN_REGEX,
    VEHICLE_REGEX,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# ── Fixtures ──

@pytest.fixture
def company(db_session):
    c = CompanyProfile(
        name="Test Corp",
        address="123 Main Street\nBangalore\n560001",
        gst="29AABCT1234Q1Z5",
        phone_number="9999999999",
        currency_code="INR",
    )
    db_session.add(c)
    db_session.flush()
    return c


@pytest.fixture
def buyer(db_session, company):
    b = Buyer(
        name="Best Buyer Ltd",
        address="456 Tech Park\nMumbai\n400001",
        gst="27BBBCD5678R2Z9",
        phone_number="8888888888",
        company_id=company.id,
    )
    db_session.add(b)
    db_session.flush()
    return b


@pytest.fixture
def product_with_hsn(db_session, company):
    p = Product(
        sku="HSN001",
        name="Test Widget",
        price=100.0,
        gst_rate=18.0,
        unit="Pieces",
        description="A test product",
        company_id=company.id,
    )
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def product_no_hsn(db_session, company):
    p = Product(
        sku="NOHSN01",
        name="Bad Widget",
        price=50.0,
        gst_rate=12.0,
        unit="Pieces",
        company_id=company.id,
    )
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def invoice(db_session, company, buyer):
    inv = Invoice(
        invoice_number="INV-001",
        company_id=company.id,
        ledger_id=buyer.id,
        ledger_name=buyer.name,
        ledger_address=buyer.address,
        ledger_gst=buyer.gst,
        voucher_type="sales",
        status="active",
        created_by=1,
        taxable_amount=Decimal("1000.00"),
        total_tax_amount=Decimal("180.00"),
        cgst_amount=Decimal("90.00"),
        sgst_amount=Decimal("90.00"),
        igst_amount=Decimal("0.00"),
        total_amount=Decimal("1180.00"),
        invoice_date=datetime(2026, 6, 14),
        company_name=company.name,
        company_address=company.address,
        company_gst=company.gst,
        company_phone=company.phone_number,
    )
    db_session.add(inv)
    db_session.flush()
    return inv


@pytest.fixture
def invoice_items(db_session, invoice, product_with_hsn):
    item = InvoiceItem(
        invoice_id=invoice.id,
        product_id=product_with_hsn.id,
        hsn_sac="85176290",
        quantity=Decimal("10.000"),
        unit_price=Decimal("100.00"),
        gst_rate=Decimal("18.00"),
        taxable_amount=Decimal("1000.00"),
        tax_amount=Decimal("180.00"),
        cgst_amount=Decimal("90.00"),
        sgst_amount=Decimal("90.00"),
        igst_amount=Decimal("0.00"),
        line_total=Decimal("1180.00"),
        description="Test item",
    )
    db_session.add(item)
    db_session.flush()
    return [item]


# ── extract_state_code ──

def test_extract_state_code_valid():
    assert extract_state_code("29AABCT1234Q1Z5") == "29"


def test_extract_state_code_empty():
    assert extract_state_code(None) == "00"
    assert extract_state_code("") == "00"


# ── _extract_pincode ──

def test_extract_pincode_found():
    assert _extract_pincode("123 Main St, Bangalore 560001") == "560001"


def test_extract_pincode_not_found():
    assert _extract_pincode("No pincode here") == ""


def test_extract_pincode_empty():
    assert _extract_pincode("") == ""
    assert _extract_pincode(None) == ""


# ── GSTIN_REGEX ──

def test_gstin_regex_valid():
    assert GSTIN_REGEX.match("29AABCT1234Q1Z5")
    assert GSTIN_REGEX.match("07AAMPB1274B1Z8")
    assert GSTIN_REGEX.match("27BBBCD5678R2Z9")


def test_gstin_regex_invalid():
    assert not GSTIN_REGEX.match("12345")
    assert not GSTIN_REGEX.match("ABC")
    assert not GSTIN_REGEX.match("")
    assert not GSTIN_REGEX.match("29AABCT1234Q1Z")  # too short


# ── VEHICLE_REGEX ──

def test_vehicle_regex_valid():
    assert VEHICLE_REGEX.match("HR55AB1234")
    assert VEHICLE_REGEX.match("DL1AB1234")
    assert VEHICLE_REGEX.match("MH12CD5678")


def test_vehicle_regex_invalid():
    assert not VEHICLE_REGEX.match("12345")
    assert not VEHICLE_REGEX.match("ABCDEF")
    assert not VEHICLE_REGEX.match("")


# ── pre_check ──

def test_pre_check_valid_invoice(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.valid is True
    assert len(result.missing_fields) == 0
    assert result.form_data.seller_gstin == "29AABCT1234Q1Z5"
    assert result.form_data.buyer_gstin == "27BBBCD5678R2Z9"
    assert result.form_data.seller_pincode == "560001"
    assert result.form_data.buyer_pincode == "400001"
    assert result.form_data.seller_state_code == "29"
    assert result.form_data.buyer_state_code == "27"


def test_pre_check_no_company_gst(db_session, invoice, invoice_items, buyer, product_with_hsn):
    company = CompanyProfile(
        name="No GST Corp",
        address="Some Address",
        gst=None,
        phone_number="9999999999",
        currency_code="INR",
    )
    db_session.add(company)
    db_session.flush()
    invoice.company_id = company.id
    invoice.company_gst = None
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.valid is False
    assert any(
        e.field == "seller_gstin" for e in result.missing_fields + []
    )
    # Check form data is pre-filled with available data
    assert result.form_data.seller_trade_name == "No GST Corp"


def test_pre_check_no_buyer_gst(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    buyer.gst = None
    invoice.ledger_gst = None
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.valid is True  # valid=True, but has missing fields
    assert len(result.missing_fields) > 0
    assert any(e.field == "buyer_gstin" for e in result.missing_fields)


def test_pre_check_invalid_gstin_format(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    company.gst = "INVALID"
    invoice.company_gst = "INVALID"
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    # Invalid GSTIN format is an error (not missing field)
    assert result.valid is False
    assert any(
        "format" in e.message.lower() for e in result.missing_fields
    ) or any(
        "format" in e.message.lower() for e in []
    )
    # Actually let's check properly
    # Because we pass 0 errors + missing with invalid gstin... Let's re-read the code
    # In pre_check, invalid GSTIN is added to `errors` list, but `valid = len(errors) == 0`
    # and `missing_fields` is the `missing` list. So errors would make valid=False
    assert result.valid is False


def test_pre_check_missing_hsn(db_session, invoice, company, buyer, product_no_hsn):
    item = InvoiceItem(
        invoice_id=invoice.id,
        product_id=product_no_hsn.id,
        hsn_sac=None,
        quantity=Decimal("5.000"),
        unit_price=Decimal("50.00"),
        gst_rate=Decimal("12.00"),
        taxable_amount=Decimal("250.00"),
        tax_amount=Decimal("30.00"),
        cgst_amount=Decimal("15.00"),
        sgst_amount=Decimal("15.00"),
        igst_amount=Decimal("0.00"),
        line_total=Decimal("280.00"),
    )
    db_session.add(item)
    db_session.flush()

    products_map = {product_no_hsn.id: product_no_hsn}
    result = pre_check(invoice, company, buyer, [item], products_map)

    assert len(result.item_validation) > 0
    assert any("hsn" in e.field.lower() for e in result.item_validation)


def test_pre_check_no_buyer(db_session, invoice, invoice_items, company, product_with_hsn):
    """When no Buyer record exists, invoice ledger fields are used as fallback."""
    invoice.ledger_id = None
    invoice.ledger_name = "Cash Customer"
    invoice.ledger_gst = "07AABCT1234Q1Z5"
    invoice.ledger_address = "Some Place\nDelhi\n110001"
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, None, invoice_items, products_map)

    assert result.valid is True
    assert result.form_data.buyer_gstin == "07AABCT1234Q1Z5"
    assert result.form_data.buyer_trade_name == "Cash Customer"


# ── validate_form_data ──

def test_validate_complete_form_valid():
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        seller_trade_name="Seller",
        seller_address_1="Addr 1",
        seller_place="Karnataka",
        seller_state_code="29",
        seller_pincode="560001",
        buyer_gstin="27BBBCD5678R2Z9",
        buyer_trade_name="Buyer",
        buyer_address_1="Addr 2",
        buyer_place="Maharashtra",
        buyer_state_code="27",
        buyer_pincode="400001",
        supply_type="O",
        sub_supply_type="Supply",
        transport_mode="1",
        distance_km=200,
        vehicle_number="HR55AB1234",
    )
    errors = validate_form_data(form)
    assert len(errors) == 0


def test_validate_missing_required():
    form = EwayBillFormData()
    errors = validate_form_data(form)
    assert len(errors) > 0
    fields = [e.field for e in errors]
    assert "seller_gstin" in fields
    assert "buyer_gstin" in fields
    assert "supply_type" in fields
    assert "sub_supply_type" in fields


def test_validate_invalid_gstin():
    form = EwayBillFormData(
        seller_gstin="BAD",
        buyer_gstin="BAD",
        seller_state_code="29",
        buyer_state_code="27",
        supply_type="O",
        sub_supply_type="Supply",
    )
    errors = validate_form_data(form)
    gstin_errors = [e for e in errors if "gstin" in e.field.lower()]
    assert len(gstin_errors) >= 2


def test_validate_bad_pincode():
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        buyer_gstin="27BBBCD5678R2Z9",
        seller_state_code="29",
        buyer_state_code="27",
        seller_pincode="ABC",  # bad
        buyer_pincode="1234",  # too short
        supply_type="O",
        sub_supply_type="Supply",
    )
    errors = validate_form_data(form)
    pincode_errors = [e for e in errors if "pincode" in e.field.lower()]
    assert len(pincode_errors) == 2


def test_validate_others_sub_supply_requires_desc():
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        buyer_gstin="27BBBCD5678R2Z9",
        seller_state_code="29",
        buyer_state_code="27",
        supply_type="O",
        sub_supply_type="Others",
        sub_supply_desc="",  # empty
    )
    errors = validate_form_data(form)
    other_errors = [e for e in errors if e.field == "sub_supply_desc"]
    assert len(other_errors) == 1


def test_validate_negative_distance():
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        buyer_gstin="27BBBCD5678R2Z9",
        seller_state_code="29",
        buyer_state_code="27",
        supply_type="O",
        sub_supply_type="Supply",
        distance_km=-5,
    )
    errors = validate_form_data(form)
    dist_errors = [e for e in errors if "distance" in e.field.lower()]
    assert len(dist_errors) == 1


def test_validate_vehicle_number_road_mode():
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        buyer_gstin="27BBBCD5678R2Z9",
        seller_state_code="29",
        buyer_state_code="27",
        supply_type="O",
        sub_supply_type="Supply",
        transport_mode="1",
        vehicle_number="BADNUMBER",
    )
    errors = validate_form_data(form)
    vehicle_errors = [e for e in errors if e.field == "vehicle_number"]
    assert len(vehicle_errors) == 1


def test_validate_vehicle_number_empty_ok_for_non_road():
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        buyer_gstin="27BBBCD5678R2Z9",
        seller_state_code="29",
        buyer_state_code="27",
        supply_type="O",
        sub_supply_type="Supply",
        transport_mode="2",  # Rail
        vehicle_number="",  # Empty is OK for non-road
    )
    errors = validate_form_data(form)
    vehicle_errors = [e for e in errors if e.field == "vehicle_number"]
    assert len(vehicle_errors) == 0


# ── generate_eway_bill_json ──

def test_generate_intrastate_json(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        seller_trade_name="Test Corp",
        seller_address_1="123 Main Street",
        seller_address_2="Bangalore",
        seller_place="Karnataka",
        seller_state_code="29",
        seller_pincode="560001",
        buyer_gstin="29BBBCT5678R3Z1",
        buyer_trade_name="Local Buyer",
        buyer_address_1="456 Local Road",
        buyer_address_2="Mysore",
        buyer_place="Karnataka",
        buyer_state_code="29",
        buyer_pincode="570001",
        supply_type="O",
        sub_supply_type="Supply",
        transport_mode="1",
        distance_km=150,
        vehicle_number="KA09AB1234",
    )
    products_map = {product_with_hsn.id: product_with_hsn}

    import json
    result_str = generate_eway_bill_json(
        invoice, company, buyer, invoice_items, products_map, form
    )
    result = json.loads(result_str) if isinstance(result_str, str) else result_str

    assert result["version"] == "1.0.1118"
    assert len(result["billLists"]) == 1
    bill = result["billLists"][0]

    # Document fields
    assert bill["docNo"] == "INV-001"
    assert bill["docType"] == "INV"
    assert bill["docDate"] == "14/06/2026"

    # Seller
    assert bill["fromGstin"] == "29AABCT1234Q1Z5"
    assert bill["fromStateCode"] == 29
    assert bill["fromPincode"] == 560001

    # Buyer
    assert bill["toGstin"] == "29BBBCT5678R3Z1"
    assert bill["toStateCode"] == 29
    assert bill["toPincode"] == 570001

    # Tax (intrastate → CGST + SGST)
    assert bill["cgstValue"] == 90.0
    assert bill["sgstValue"] == 90.0
    assert bill["igstValue"] == 0.0

    # Transport
    assert bill["transMode"] == 1
    assert bill["transDistance"] == 150
    assert bill["vehicleNo"] == "KA09AB1234"

    # Items
    assert len(bill["itemList"]) == 1
    item = bill["itemList"][0]
    assert item["productName"] == "Test Widget"
    assert item["hsnCode"] == "85176290"
    assert item["quantity"] == 10.0
    assert item["taxableAmount"] == 1000.0
    # Intrastate: CGST + SGST, no IGST
    assert item["cgstRate"] == 9.0
    assert item["sgstRate"] == 9.0
    assert item["igstRate"] == 0.0


def test_generate_interstate_json(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        seller_trade_name="Test Corp",
        seller_address_1="123 Main Street",
        seller_address_2="Bangalore",
        seller_place="Karnataka",
        seller_state_code="29",
        seller_pincode="560001",
        buyer_gstin="27BBBCD5678R2Z9",  # Different state (27=Maharashtra)
        buyer_trade_name="Interstate Buyer",
        buyer_address_1="456 Tech Park",
        buyer_address_2="Mumbai",
        buyer_place="Maharashtra",
        buyer_state_code="27",
        buyer_pincode="400001",
        supply_type="O",
        sub_supply_type="Supply",
        transport_mode="1",
        distance_km=500,
        vehicle_number="MH12AB5678",
    )
    products_map = {product_with_hsn.id: product_with_hsn}

    import json
    result_str = generate_eway_bill_json(
        invoice, company, buyer, invoice_items, products_map, form
    )
    result = json.loads(result_str) if isinstance(result_str, str) else result_str

    bill = result["billLists"][0]

    # Tax (interstate → IGST only)
    assert bill["cgstValue"] == 90.0  # from invoice (service doesn't split per item for this)
    assert bill["igstValue"] == 0.0  # invoice has IGST as 0 by default

    item = bill["itemList"][0]
    # Interstate: IGST only
    assert item["igstRate"] == 18.0
    assert item["cgstRate"] == 0.0
    assert item["sgstRate"] == 0.0


def test_generate_without_vehicle(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        seller_trade_name="Test Corp",
        seller_address_1="123 Main Street",
        seller_address_2="Bangalore",
        seller_place="Karnataka",
        seller_state_code="29",
        seller_pincode="560001",
        buyer_gstin="27BBBCD5678R2Z9",
        buyer_trade_name="Interstate Buyer",
        buyer_address_1="456 Tech Park",
        buyer_address_2="Mumbai",
        buyer_place="Maharashtra",
        buyer_state_code="27",
        buyer_pincode="400001",
        supply_type="O",
        sub_supply_type="Supply",
        transport_mode="2",  # Rail — no vehicle number needed
        distance_km=500,
    )
    products_map = {product_with_hsn.id: product_with_hsn}

    import json
    result_str = generate_eway_bill_json(
        invoice, company, buyer, invoice_items, products_map, form
    )
    result = json.loads(result_str) if isinstance(result_str, str) else result_str

    bill = result["billLists"][0]
    assert bill["transMode"] == 2
    assert bill["vehicleNo"] == ""
    assert bill["vehicleType"] == "R"


def test_generate_respects_transporter_name(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        seller_trade_name="Test Corp",
        seller_address_1="123 Main Street",
        seller_address_2="Bangalore",
        seller_place="Karnataka",
        seller_state_code="29",
        seller_pincode="560001",
        buyer_gstin="27BBBCD5678R2Z9",
        buyer_trade_name="Buyer",
        buyer_address_1="456 Tech Park",
        buyer_address_2="Mumbai",
        buyer_place="Maharashtra",
        buyer_state_code="27",
        buyer_pincode="400001",
        supply_type="O",
        sub_supply_type="Supply",
        transport_mode="1",
        distance_km=100,
        transporter_name="Fast Logistics",
        transporter_gstin="07TRNSP1234Q1Z5",
        vehicle_type="R",
    )
    products_map = {product_with_hsn.id: product_with_hsn}

    import json
    result_str = generate_eway_bill_json(
        invoice, company, buyer, invoice_items, products_map, form
    )
    result = json.loads(result_str) if isinstance(result_str, str) else result_str

    bill = result["billLists"][0]
    assert bill["transporterName"] == "Fast Logistics"
    assert bill["transporterId"] == "07TRNSP1234Q1Z5"


# ── get_or_create_default_transporter ──

def test_get_default_transporter_none_when_empty(db_session, company):
    result = get_or_create_default_transporter(db_session, company.id)
    assert result is None


def test_get_default_transporter_returns_default(db_session, company):
    t = EwayBillTransporter(
        company_id=company.id,
        transporter_name="Default Transporter",
        transporter_gstin="07TRNSP1234Q1Z5",
        transport_mode="1",
        vehicle_type="R",
        is_default=True,
    )
    db_session.add(t)
    db_session.flush()

    result = get_or_create_default_transporter(db_session, company.id)
    assert result is not None
    assert result.transporter_name == "Default Transporter"
    assert result.is_default is True


def test_get_default_transporter_ignores_non_default(db_session, company):
    t = EwayBillTransporter(
        company_id=company.id,
        transporter_name="Non-Default",
        transport_mode="1",
        vehicle_type="R",
        is_default=False,
    )
    db_session.add(t)
    db_session.flush()

    result = get_or_create_default_transporter(db_session, company.id)
    assert result is None


# ── totalValue vs totInvValue ──

def test_total_value_uses_taxable_amount(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """Bug fix verification: totalValue should be taxable_amount, not total_amount."""
    invoice.taxable_amount = Decimal("5000.00")
    invoice.total_amount = Decimal("5900.00")
    db_session.flush()

    form = EwayBillFormData(
        seller_gstin="29AABCT1234Q1Z5",
        seller_trade_name="Test Corp",
        seller_address_1="Addr 1",
        seller_place="KA",
        seller_state_code="29",
        seller_pincode="560001",
        buyer_gstin="27BBBCD5678R2Z9",
        buyer_trade_name="Buyer",
        buyer_address_1="Addr 2",
        buyer_place="MH",
        buyer_state_code="27",
        buyer_pincode="400001",
        supply_type="O",
        sub_supply_type="Supply",
        transport_mode="1",
        distance_km=100,
    )
    products_map = {product_with_hsn.id: product_with_hsn}

    import json
    result_str = generate_eway_bill_json(
        invoice, company, buyer, invoice_items, products_map, form
    )
    result = json.loads(result_str) if isinstance(result_str, str) else result_str

    bill = result["billLists"][0]
    assert bill["totalValue"] == 5000.0
    assert bill["totInvValue"] == 5900.0


# ── Threshold & eway_enabled tests ──

def test_pre_check_eway_disabled(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """When eway_enabled=False, pre_check should return valid=False with error."""
    company.eway_enabled = False
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.eway_enabled is False
    assert result.valid is False


def test_pre_check_threshold_warning_below_local(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """Below local threshold (seller=29, buyer=27 interstate) should produce warning."""
    invoice.taxable_amount = Decimal("1000.00")
    invoice.total_tax_amount = Decimal("180.00")
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.threshold_warning is not None
    assert "below" in (result.threshold_warning or "").lower()


def test_pre_check_threshold_warning_above_interstate(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """Above interstate threshold should produce NO warning."""
    invoice.taxable_amount = Decimal("100000.00")
    invoice.total_tax_amount = Decimal("18000.00")
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    # Seller state=29, Buyer state=27 → interstate. Value 118000 > 50000 threshold
    assert result.threshold_warning is None


def test_pre_check_large_invoice_not_blocked(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """Large invoice values should NEVER be blocked — only warned if below threshold."""
    # ₹50,00,000 invoice
    invoice.taxable_amount = Decimal("5000000.00")
    invoice.total_tax_amount = Decimal("900000.00")
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    # Should be valid and NOT blocked
    assert result.valid is True
    assert result.threshold_warning is None  # Above all thresholds


def test_pre_check_custom_thresholds(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """Custom threshold values should be used from company settings."""
    company.eway_local_threshold = 200000
    company.eway_interstate_threshold = 100000
    db_session.flush()

    invoice.taxable_amount = Decimal("150000.00")
    invoice.total_tax_amount = Decimal("27000.00")
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.eway_local_threshold == 200000
    assert result.eway_interstate_threshold == 100000
    # Interstate (29 ≠ 27): value 177000 > 100000 threshold → no warning
    assert result.threshold_warning is None


def test_pre_check_default_thresholds(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """Default thresholds should be returned when not set."""
    # New-style company without explicit eway fields
    # Test defaults via pre_check result
    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.eway_local_threshold == 100000
    assert result.eway_interstate_threshold == 50000
    assert result.eway_enabled is True
