"""
Tests for the E-Way Bill service.

Covers:
- pre_check: GSTIN validation, HSN checks, form pre-fill, B2C (null GSTIN), thresholds
- validate_form_data: all field validations
- generate_eway_bill_json: NIC-compliant JSON structure, inter/intra-state tax
- helpers: extract_state_code, _extract_pincode, default transporter
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
from src.schemas.eway_bill import EwayBillFormData
from src.services.eway_bill_service import (
    pre_check,
    validate_form_data,
    generate_eway_bill_json,
    extract_state_code,
    _extract_pincode,
    get_or_create_default_transporter,
    GSTIN_REGEX,
    VEHICLE_REGEX,
    UNREGISTERED_GSTIN,
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


def _make_invoice(db_session, company, buyer, *, igst=False):
    """Build an active sales invoice. igst=True makes it an interstate invoice."""
    inv = Invoice(
        invoice_number="INV-001",
        company_id=company.id,
        ledger_id=buyer.id if buyer else None,
        ledger_name=buyer.name if buyer else None,
        ledger_address=buyer.address if buyer else None,
        ledger_gst=buyer.gst if buyer else None,
        voucher_type="sales",
        status="active",
        created_by=1,
        taxable_amount=Decimal("1000.00"),
        total_tax_amount=Decimal("180.00"),
        cgst_amount=Decimal("0.00") if igst else Decimal("90.00"),
        sgst_amount=Decimal("0.00") if igst else Decimal("90.00"),
        igst_amount=Decimal("180.00") if igst else Decimal("0.00"),
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
def invoice(db_session, company, buyer):
    return _make_invoice(db_session, company, buyer)


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


# ── helpers ──

def test_extract_state_code_valid():
    assert extract_state_code("29AABCT1234Q1Z5") == "29"


def test_extract_state_code_empty():
    assert extract_state_code(None) == "00"
    assert extract_state_code("") == "00"
    assert extract_state_code("URP") == "00"


def test_extract_pincode_found():
    assert _extract_pincode("123 Main St, Bangalore 560001") == "560001"


def test_extract_pincode_not_found():
    assert _extract_pincode("No pincode here") == ""


def test_extract_pincode_empty():
    assert _extract_pincode("") == ""
    assert _extract_pincode(None) == ""


def test_gstin_regex():
    assert GSTIN_REGEX.match("29AABCT1234Q1Z5")
    assert GSTIN_REGEX.match("07AAMPB1274B1Z8")
    assert not GSTIN_REGEX.match("12345")
    assert not GSTIN_REGEX.match("")
    assert not GSTIN_REGEX.match("29AABCT1234Q1Z")  # too short


def test_vehicle_regex():
    assert VEHICLE_REGEX.match("HR55AB1234")
    assert VEHICLE_REGEX.match("MH12CD5678")
    assert not VEHICLE_REGEX.match("BADNUMBER")
    assert not VEHICLE_REGEX.match("")


# ── pre_check ──

def test_pre_check_valid_invoice(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.valid is True
    assert result.errors == []
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
    assert any(e.field == "seller_gstin" for e in result.errors)
    assert result.form_data.seller_trade_name == "No GST Corp"


def test_pre_check_no_buyer_gst_is_b2c(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """A buyer without a GSTIN is B2C — still valid, just flagged as missing/URP."""
    buyer.gst = None
    invoice.ledger_gst = None
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.valid is True  # not blocked
    assert result.form_data.buyer_gstin == ""
    assert any(e.field == "buyer_gstin" for e in result.missing_fields)


def test_pre_check_invalid_buyer_gstin_format(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    buyer.gst = "INVALID"
    invoice.ledger_gst = "INVALID"
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.valid is False
    assert any("format" in e.message.lower() and e.field == "buyer_gstin" for e in result.errors)


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


def test_pre_check_no_buyer_record_uses_ledger_snapshot(db_session, invoice, invoice_items, company, product_with_hsn):
    """When no Buyer record exists, the invoice ledger snapshot is used."""
    invoice.ledger_id = None
    invoice.ledger_name = "Cash Customer"
    invoice.ledger_gst = "07AAMPB1274B1Z8"
    invoice.ledger_address = "Some Place\nDelhi\n110001"
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, None, invoice_items, products_map)

    assert result.valid is True
    assert result.form_data.buyer_gstin == "07AAMPB1274B1Z8"
    assert result.form_data.buyer_trade_name == "Cash Customer"
    assert result.form_data.buyer_state_code == "07"


def test_pre_check_no_buyer_record_b2c_does_not_crash(db_session, invoice, invoice_items, company, product_with_hsn):
    """Regression: null buyer GSTIN must never raise (was a 500 in the old code)."""
    invoice.ledger_id = None
    invoice.ledger_name = "Walk-in"
    invoice.ledger_gst = None
    invoice.ledger_address = None
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, None, invoice_items, products_map)

    assert result.valid is True
    assert result.form_data.buyer_gstin == ""


# ── validate_form_data ──

def _complete_form(**overrides) -> EwayBillFormData:
    base = dict(
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
        transaction_type="1",
        sub_supply_type="1",
        transport_mode="1",
        distance_km=200,
        vehicle_number="HR55AB1234",
    )
    base.update(overrides)
    return EwayBillFormData(**base)


def test_validate_complete_form_valid():
    assert validate_form_data(_complete_form()) == []


def test_validate_empty_form_required_fields():
    errors = validate_form_data(EwayBillFormData())
    fields = [e.field for e in errors]
    assert "seller_gstin" in fields
    assert "seller_state_code" in fields
    assert "buyer_state_code" in fields
    # supply_type / sub_supply_type / transaction_type have valid defaults
    assert "supply_type" not in fields
    assert "sub_supply_type" not in fields


def test_validate_buyer_gstin_optional():
    """Empty buyer GSTIN is allowed (B2C/URP) and produces no error."""
    errors = validate_form_data(_complete_form(buyer_gstin=""))
    assert not any(e.field == "buyer_gstin" for e in errors)


def test_validate_invalid_gstin():
    errors = validate_form_data(_complete_form(seller_gstin="BAD", buyer_gstin="ALSOBAD"))
    gstin_errors = [e for e in errors if "gstin" in e.field.lower()]
    assert len(gstin_errors) == 2


def test_validate_bad_pincode():
    errors = validate_form_data(_complete_form(seller_pincode="ABC", buyer_pincode="1234"))
    pincode_errors = [e for e in errors if "pincode" in e.field.lower()]
    assert len(pincode_errors) == 2


def test_validate_others_sub_supply_requires_desc():
    errors = validate_form_data(_complete_form(sub_supply_type="8", sub_supply_desc=""))
    assert any(e.field == "sub_supply_desc" for e in errors)
    # with a description, no error
    assert not any(
        e.field == "sub_supply_desc"
        for e in validate_form_data(_complete_form(sub_supply_type="8", sub_supply_desc="Stock transfer"))
    )


def test_validate_negative_distance():
    errors = validate_form_data(_complete_form(distance_km=-5))
    assert any("distance" in e.field.lower() for e in errors)


def test_validate_vehicle_number_road_mode():
    errors = validate_form_data(_complete_form(transport_mode="1", vehicle_number="BADNUMBER"))
    assert any(e.field == "vehicle_number" for e in errors)


def test_validate_vehicle_empty_ok_for_non_road():
    errors = validate_form_data(_complete_form(transport_mode="2", vehicle_number=""))
    assert not any(e.field == "vehicle_number" for e in errors)


def test_validate_bad_sub_supply_code():
    errors = validate_form_data(_complete_form(sub_supply_type="Supply"))  # label, not code
    assert any(e.field == "sub_supply_type" for e in errors)


# ── generate_eway_bill_json ──

def test_generate_intrastate_json(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = _complete_form(
        buyer_gstin="29BBBCT5678R3Z1",
        buyer_state_code="29",
        buyer_pincode="570001",
        distance_km=150,
        vehicle_number="KA09AB1234",
    )
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, invoice_items, products_map, form)["billLists"][0]

    assert bill["docNo"] == "INV-001"
    assert bill["docType"] == "INV"
    assert bill["docDate"] == "14/06/2026"
    assert bill["transactionType"] == 1
    assert bill["subSupplyType"] == "1"
    assert bill["fromGstin"] == "29AABCT1234Q1Z5"
    assert bill["fromStateCode"] == 29
    assert bill["fromPincode"] == 560001
    assert bill["toGstin"] == "29BBBCT5678R3Z1"
    assert bill["toStateCode"] == 29

    # Intrastate invoice (igst=0) → CGST + SGST
    assert bill["cgstValue"] == 90.0
    assert bill["sgstValue"] == 90.0
    assert bill["igstValue"] == 0.0

    item = bill["itemList"][0]
    assert item["productName"] == "Test Widget"
    assert item["hsnCode"] == 85176290
    assert item["quantity"] == 10.0
    assert item["taxableAmount"] == 1000.0
    assert item["cgstRate"] == 9.0
    assert item["sgstRate"] == 9.0
    assert item["igstRate"] == 0


def test_generate_interstate_json(db_session, company, buyer, product_with_hsn):
    """Interstate is driven by the invoice's IGST amount, not form state codes."""
    invoice = _make_invoice(db_session, company, buyer, igst=True)
    item = InvoiceItem(
        invoice_id=invoice.id,
        product_id=product_with_hsn.id,
        hsn_sac="85176290",
        quantity=Decimal("10.000"),
        unit_price=Decimal("100.00"),
        gst_rate=Decimal("18.00"),
        taxable_amount=Decimal("1000.00"),
        tax_amount=Decimal("180.00"),
        cgst_amount=Decimal("0.00"),
        sgst_amount=Decimal("0.00"),
        igst_amount=Decimal("180.00"),
        line_total=Decimal("1180.00"),
    )
    db_session.add(item)
    db_session.flush()

    form = _complete_form(buyer_state_code="27", distance_km=500, vehicle_number="MH12AB5678")
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, [item], products_map, form)["billLists"][0]

    assert bill["cgstValue"] == 0.0
    assert bill["sgstValue"] == 0.0
    assert bill["igstValue"] == 180.0

    jitem = bill["itemList"][0]
    assert jitem["igstRate"] == 18.0
    assert jitem["cgstRate"] == 0
    assert jitem["sgstRate"] == 0


def test_generate_b2c_uses_urp(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = _complete_form(buyer_gstin="")
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, invoice_items, products_map, form)["billLists"][0]
    assert bill["toGstin"] == UNREGISTERED_GSTIN


def test_generate_others_sub_supply_desc_emitted(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = _complete_form(sub_supply_type="8", sub_supply_desc="Stock transfer")
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, invoice_items, products_map, form)["billLists"][0]
    assert bill["subSupplyType"] == "8"
    assert bill["subSupplyDesc"] == "Stock transfer"


def test_generate_non_others_omits_desc(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = _complete_form(sub_supply_type="1", sub_supply_desc="ignored")
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, invoice_items, products_map, form)["billLists"][0]
    assert bill["subSupplyDesc"] == ""


def test_generate_without_vehicle(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = _complete_form(transport_mode="2", vehicle_number="")
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, invoice_items, products_map, form)["billLists"][0]
    assert bill["transMode"] == 2
    assert bill["vehicleNo"] == ""
    assert bill["vehicleType"] == "R"


def test_generate_respects_transporter(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = _complete_form(transporter_name="Fast Logistics", transporter_gstin="07AAMPB1274B1Z8")
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, invoice_items, products_map, form)["billLists"][0]
    assert bill["transporterName"] == "Fast Logistics"
    assert bill["transporterId"] == "07AAMPB1274B1Z8"


def test_generate_total_value_reconciles(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """totalValue = taxable; totInvValue = total; otherValue balances rounding."""
    invoice.taxable_amount = Decimal("5000.00")
    invoice.cgst_amount = Decimal("450.00")
    invoice.sgst_amount = Decimal("450.00")
    invoice.igst_amount = Decimal("0.00")
    invoice.total_amount = Decimal("5901.00")  # ₹1 round-off
    db_session.flush()

    form = _complete_form()
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, invoice_items, products_map, form)["billLists"][0]

    assert bill["totalValue"] == 5000.0
    assert bill["totInvValue"] == 5901.0
    assert bill["otherValue"] == 1.0
    # NIC reconciliation: totals add up
    recomputed = (
        bill["totalValue"] + bill["cgstValue"] + bill["sgstValue"]
        + bill["igstValue"] + bill["cessValue"] + bill["otherValue"]
    )
    assert round(recomputed, 2) == bill["totInvValue"]


def test_generate_large_invoice_no_cap(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """No upper value restriction — large invoices generate fine."""
    invoice.taxable_amount = Decimal("5000000.00")
    invoice.total_amount = Decimal("5900000.00")
    db_session.flush()
    form = _complete_form()
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, company, buyer, invoice_items, products_map, form)["billLists"][0]
    assert bill["totalValue"] == 5000000.0


# ── default transporter ──

def test_get_default_transporter_none_when_empty(db_session, company):
    assert get_or_create_default_transporter(db_session, company.id) is None


def test_get_default_transporter_returns_default(db_session, company):
    t = EwayBillTransporter(
        company_id=company.id,
        transporter_name="Default Transporter",
        transporter_gstin="07AAMPB1274B1Z8",
        transport_mode="1",
        vehicle_type="R",
        is_default=True,
    )
    db_session.add(t)
    db_session.flush()

    result = get_or_create_default_transporter(db_session, company.id)
    assert result is not None
    assert result.transporter_name == "Default Transporter"


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
    assert get_or_create_default_transporter(db_session, company.id) is None


# ── thresholds (guidance only, never blocks) ──

def test_threshold_warning_below(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    # intrastate invoice, ₹1180 total < ₹1,00,000 local threshold
    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)
    assert result.threshold_warning is not None
    assert "below" in result.threshold_warning.lower()
    assert result.valid is True  # warning never blocks


def test_threshold_no_warning_above(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    invoice.total_amount = Decimal("200000.00")
    db_session.flush()
    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)
    assert result.threshold_warning is None


def test_threshold_custom_values(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    company.eway_local_threshold = 500
    company.eway_interstate_threshold = 500
    invoice.total_amount = Decimal("1180.00")
    db_session.flush()
    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)
    assert result.eway_local_threshold == 500
    assert result.threshold_warning is None  # 1180 > 500


def test_pre_check_eway_disabled(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    company.eway_enabled = False
    db_session.flush()
    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)
    assert result.eway_enabled is False
    assert result.valid is False
    assert any(e.field == "eway_disabled" for e in result.errors)
