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
from src.core.eway_bill_codes import NIC_JSON_VERSION, NIC_UQC_CODES, VEHICLE_REGEX
from src.core.validation import GSTIN_REGEX
from src.schemas.eway_bill import EwayBillFormData
from src.services.eway_bill_service import (
    pre_check,
    save_default_transporter,
    validate_form_against_invoice,
    validate_form_data,
    validate_invoice,
    generate_eway_bill_json,
    extract_state_code,
    _extract_pincode,
    _split_address,
    get_or_create_default_transporter,
    UNREGISTERED_GSTIN,
)
from src.services.uqc import HSN_UQC_BY_UNIT, hsn_uqc


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
    assert result.form_data.seller_trade_name == "Test Corp"  # the invoice's snapshot


def test_pre_check_no_buyer_gst_is_b2c(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """A buyer without a GSTIN is B2C — no error, but the state has to be asked for."""
    buyer.gst = None
    invoice.ledger_gst = None
    db_session.flush()

    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)

    assert result.errors == []
    assert result.form_data.buyer_gstin == ""
    assert {e.field for e in result.missing_fields} >= {"buyer_gstin", "buyer_state_code"}


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

    assert result.form_data.buyer_gstin == ""
    assert any(e.field == "buyer_pincode" for e in result.missing_fields)


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


def test_validate_negative_distance():
    errors = validate_form_data(_complete_form(distance_km=-5))
    assert any("distance" in e.field.lower() for e in errors)


def test_validate_vehicle_number_road_mode():
    errors = validate_form_data(_complete_form(transport_mode="1", vehicle_number="BADNUMBER"))
    assert any(e.field == "vehicle_number" for e in errors)


def test_validate_vehicle_empty_ok_for_non_road():
    errors = validate_form_data(_complete_form(
        transport_mode="2", vehicle_number="", transport_doc_no="RR123", transport_doc_date="2026-06-15",
    ))
    assert errors == []


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
    bill = generate_eway_bill_json(invoice, invoice_items, products_map, form)["billLists"][0]

    assert bill["docNo"] == "INV-001"
    assert bill["docType"] == "INV"
    assert bill["docDate"] == "14/06/2026"
    assert bill["transType"] == 1
    assert bill["subSupplyType"] == 1
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
    assert item["hsnCode"] == "85176290"
    assert item["itemNo"] == 1
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
    bill = generate_eway_bill_json(invoice, [item], products_map, form)["billLists"][0]

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
    bill = generate_eway_bill_json(invoice, invoice_items, products_map, form)["billLists"][0]
    assert bill["toGstin"] == UNREGISTERED_GSTIN


def test_generate_without_vehicle(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = _complete_form(transport_mode="2", vehicle_number="")
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, invoice_items, products_map, form)["billLists"][0]
    assert bill["transMode"] == 2
    assert bill["vehicleNo"] == ""
    assert bill["vehicleType"] == "R"


def test_generate_respects_transporter(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    form = _complete_form(transporter_name="Fast Logistics", transporter_gstin="07AAMPB1274B1Z8")
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, invoice_items, products_map, form)["billLists"][0]
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
    bill = generate_eway_bill_json(invoice, invoice_items, products_map, form)["billLists"][0]

    assert bill["totalValue"] == 5000.0
    assert bill["totInvValue"] == 5901.0
    assert bill["OthValue"] == 1.0
    # NIC reconciliation: totals add up
    recomputed = (
        bill["totalValue"] + bill["cgstValue"] + bill["sgstValue"]
        + bill["igstValue"] + bill["cessValue"] + bill["OthValue"]
    )
    assert round(recomputed, 2) == bill["totInvValue"]


def test_generate_large_invoice_no_cap(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    """No upper value restriction — large invoices generate fine."""
    invoice.taxable_amount = Decimal("5000000.00")
    invoice.total_amount = Decimal("5900000.00")
    db_session.flush()
    form = _complete_form()
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, invoice_items, products_map, form)["billLists"][0]
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
    # intrastate invoice, ₹1180 total < ₹50,000 local threshold
    products_map = {product_with_hsn.id: product_with_hsn}
    result = pre_check(invoice, company, buyer, invoice_items, products_map)
    assert result.threshold_warning is not None
    assert "does not exceed" in result.threshold_warning
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


def test_threshold_exactly_at_the_limit_warns_because_rule_138_says_exceeding(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    company.eway_local_threshold = 1180
    db_session.flush()
    result = pre_check(invoice, company, buyer, invoice_items, {product_with_hsn.id: product_with_hsn})
    assert result.threshold_warning is not None


def test_default_thresholds_follow_rule_138():
    from src.models.company import CompanyProfile as Model

    assert float(Model.__table__.c.eway_local_threshold.default.arg) == 50000
    assert float(Model.__table__.c.eway_interstate_threshold.default.arg) == 50000


# ── unit codes ──

@pytest.mark.parametrize("unit, expected", [
    ("Pieces", "NOS"),  # the default unit, which used to come out as PIE
    ("pcs", "PCS"),
    ("Kg", "KGS"),
    ("Litre", "LTR"),
    ("Dozen", "DOZ"),
    ("Hours", "NOS"),  # unmapped falls back
    ("CTN", "CTN"),  # already a NIC code, and not in the GSTR-1 mapping
    (None, "NOS"),
])
def test_generate_maps_units_to_nic_codes(db_session, invoice, invoice_items, company, product_with_hsn, unit, expected):
    product_with_hsn.unit = unit
    products_map = {product_with_hsn.id: product_with_hsn}
    bill = generate_eway_bill_json(invoice, invoice_items, products_map, _complete_form())["billLists"][0]
    assert bill["itemList"][0]["qtyUnit"] == expected
    assert bill["itemList"][0]["qtyUnit"] in NIC_UQC_CODES


def test_every_mapped_unit_is_a_valid_nic_code():
    assert set(HSN_UQC_BY_UNIT.values()) <= NIC_UQC_CODES


def test_service_lines_get_a_nic_code_not_the_gstr1_na(db_session, invoice, company, product_with_hsn):
    """GSTR-1 says NA for services. NA is not on NIC's list, so it must stay out of the bill."""
    item = _item(invoice, product_with_hsn, hsn="998313")
    goods = _item(invoice, product_with_hsn, hsn="85176290")
    db_session.add_all([item, goods])
    db_session.flush()
    bill = generate_eway_bill_json(invoice, [item, goods], {product_with_hsn.id: product_with_hsn}, _complete_form())["billLists"][0]
    assert all(line["qtyUnit"] in NIC_UQC_CODES for line in bill["itemList"])
    assert hsn_uqc("998313", "Pieces") == "NA"  # GSTR-1 unchanged


def _item(invoice, product, *, hsn="85176290", taxable="1000.00"):
    return InvoiceItem(
        invoice_id=invoice.id,
        product_id=product.id,
        hsn_sac=hsn,
        quantity=Decimal("1.000"),
        unit_price=Decimal(taxable),
        gst_rate=Decimal("18.00"),
        taxable_amount=Decimal(taxable),
        tax_amount=Decimal("0.00"),
        cgst_amount=Decimal("0.00"),
        sgst_amount=Decimal("0.00"),
        igst_amount=Decimal("0.00"),
        line_total=Decimal(taxable),
    )


# ── PIN codes ──

@pytest.mark.parametrize("field", ["seller_pincode", "buyer_pincode"])
@pytest.mark.parametrize("value", ["", "   ", "12345", "1234567", "012345", "ABCDEF"])
def test_validate_rejects_bad_pins(field, value):
    errors = validate_form_data(_complete_form(**{field: value}))
    assert [e.field for e in errors] == [field]
    assert "PIN code" in errors[0].message


def test_pre_check_flags_missing_pins(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    invoice.company_address = "Some Road, Bengaluru"
    invoice.ledger_address = "Some Lane, Mumbai"
    db_session.flush()
    result = pre_check(invoice, company, buyer, invoice_items, {product_with_hsn.id: product_with_hsn})
    assert result.valid is False
    assert result.form_data.seller_pincode == ""
    messages = {e.field: e.message for e in result.missing_fields}
    assert "company address" in messages["seller_pincode"]
    assert "buyer address" in messages["buyer_pincode"]


def test_extract_pincode_forms():
    assert _extract_pincode("Unit 5, Bannerghatta Road, Bengaluru 560 029") == "560029"
    assert _extract_pincode("Plot 123456, Sector 4, Noida 201301") == "201301"  # the last one written
    assert _extract_pincode("Phone 9876543210") == ""  # a phone number is not a PIN
    assert _extract_pincode("Old PIN 012345") == ""  # NIC's minimum is 100000


def test_split_address():
    assert _split_address("Line one\nLine two\nLine three") == ("Line one", "Line two, Line three")
    long_line = "x" * 80 + " " + "y" * 80
    first, rest = _split_address(long_line)
    assert len(first) <= 120
    assert rest == "y" * 80


# ── the NIC format ──

def test_generated_bill_matches_nic_key_names_and_types(db_session, invoice, invoice_items, product_with_hsn):
    """Pins the bulk file to what NIC's preparation tool writes. The API payload differs."""
    data = generate_eway_bill_json(invoice, invoice_items, {product_with_hsn.id: product_with_hsn}, _complete_form())
    assert data["version"] == NIC_JSON_VERSION
    bill = data["billLists"][0]
    assert set(bill) == {
        "userGstin", "supplyType", "subSupplyType", "subSupplyDesc", "docType", "docNo", "docDate",
        "transType", "fromGstin", "fromTrdName", "fromAddr1", "fromAddr2", "fromPlace", "fromPincode",
        "fromStateCode", "actualFromStateCode", "toGstin", "toTrdName", "toAddr1", "toAddr2", "toPlace",
        "toPincode", "toStateCode", "actualToStateCode", "totalValue", "cgstValue", "sgstValue", "igstValue",
        "cessValue", "TotNonAdvolVal", "OthValue", "totInvValue", "transMode", "transDistance",
        "transporterName", "transporterId", "transDocNo", "transDocDate", "vehicleNo", "vehicleType",
        "mainHsnCode", "itemList",
    }
    assert set(bill["itemList"][0]) == {
        "itemNo", "productName", "productDesc", "hsnCode", "quantity", "qtyUnit", "taxableAmount",
        "sgstRate", "cgstRate", "igstRate", "cessRate", "cessNonAdvol",
    }
    for key in ("subSupplyType", "transType", "fromPincode", "toPincode", "fromStateCode", "toStateCode",
                "actualFromStateCode", "actualToStateCode", "transMode", "transDistance"):
        assert isinstance(bill[key], int), key
    for key in ("supplyType", "subSupplyDesc", "docNo", "mainHsnCode", "transDocNo"):
        assert isinstance(bill[key], str), key
    assert isinstance(bill["itemList"][0]["hsnCode"], str)


def test_hsn_with_a_leading_zero_survives(db_session, invoice, product_with_hsn):
    item = _item(invoice, product_with_hsn, hsn="0401")
    db_session.add(item)
    db_session.flush()
    bill = generate_eway_bill_json(invoice, [item], {product_with_hsn.id: product_with_hsn}, _complete_form())["billLists"][0]
    assert bill["itemList"][0]["hsnCode"] == "0401"
    assert bill["mainHsnCode"] == "0401"


def test_main_hsn_is_the_largest_goods_line(db_session, invoice, product_with_hsn):
    lines = [
        _item(invoice, product_with_hsn, hsn="998313", taxable="9000.00"),  # services can't be it
        _item(invoice, product_with_hsn, hsn="85176290", taxable="500.00"),
        _item(invoice, product_with_hsn, hsn="84713010", taxable="800.00"),
    ]
    db_session.add_all(lines)
    db_session.flush()
    bill = generate_eway_bill_json(invoice, lines, {product_with_hsn.id: product_with_hsn}, _complete_form())["billLists"][0]
    assert bill["mainHsnCode"] == "84713010"
    assert [line["itemNo"] for line in bill["itemList"]] == [1, 2, 3]


def test_blank_distance_is_sent_as_zero(db_session, invoice, invoice_items, product_with_hsn):
    form = _complete_form(distance_km=None)
    assert validate_form_data(form) == []
    bill = generate_eway_bill_json(invoice, invoice_items, {product_with_hsn.id: product_with_hsn}, form)["billLists"][0]
    assert bill["transDistance"] == 0


def test_text_is_reduced_to_what_nic_allows(db_session, invoice, product_with_hsn):
    item = _item(invoice, product_with_hsn)
    item.description = "Widget (blue)\nSerials: A1, A2 " + "x" * 200
    db_session.add(item)
    db_session.flush()
    form = _complete_form(seller_address_1="Plot #5, (Rear) Block-B: Ground / Floor & Annex.")
    bill = generate_eway_bill_json(invoice, [item], {product_with_hsn.id: product_with_hsn}, form)["billLists"][0]
    assert bill["fromAddr1"] == "Plot #5, Rear Block-B Ground / Floor & Annex."
    desc = bill["itemList"][0]["productDesc"]
    assert desc.startswith("Widget blue Serials A1, A2 ")
    assert len(desc) <= 100


@pytest.mark.parametrize("number", [
    "KA12AB1234", "AB121234", "AB12A1234", "ABC1234", "AB123A1234", "AB12ABC1234",
    "DFAB1234", "TM1234567", "BP1234567", "NP1234567",
])
def test_vehicle_formats_on_nics_list_are_valid(number):
    assert VEHICLE_REGEX.match(number)
    assert validate_form_data(_complete_form(vehicle_number=number)) == []


def test_vehicle_number_spaces_are_removed(db_session, invoice, invoice_items, product_with_hsn):
    form = _complete_form(vehicle_number="ka 12 ab 1234")
    assert validate_form_data(form) == []
    bill = generate_eway_bill_json(invoice, invoice_items, {product_with_hsn.id: product_with_hsn}, form)["billLists"][0]
    assert bill["vehicleNo"] == "KA12AB1234"


def test_road_needs_a_vehicle_or_a_transporter():
    errors = validate_form_data(_complete_form(vehicle_number="", transporter_gstin=""))
    assert [e.field for e in errors] == ["vehicle_number"]
    assert validate_form_data(_complete_form(vehicle_number="", transporter_gstin="07AAMPB1274B1Z8")) == []


@pytest.mark.parametrize("mode", ["2", "3", "4"])
def test_rail_air_ship_need_a_transport_document(mode):
    fields = [e.field for e in validate_form_data(_complete_form(transport_mode=mode, vehicle_number=""))]
    assert fields == ["transport_doc_no", "transport_doc_date"]


def test_transport_document_is_written_in_nics_date_format(db_session, invoice, invoice_items, product_with_hsn):
    form = _complete_form(transport_mode="2", vehicle_number="", transport_doc_no="RR-1", transport_doc_date="2026-06-20")
    bill = generate_eway_bill_json(invoice, invoice_items, {product_with_hsn.id: product_with_hsn}, form)["billLists"][0]
    assert bill["transDocNo"] == "RR-1"
    assert bill["transDocDate"] == "20/06/2026"


def test_transport_document_cannot_predate_the_invoice(invoice):
    form = _complete_form(transport_mode="2", transport_doc_no="RR-1", transport_doc_date="2026-06-13")
    assert "transport_doc_date" in [e.field for e in validate_form_against_invoice(form, invoice)]


def test_rail_and_air_must_be_regular_vehicles():
    form = _complete_form(transport_mode="3", vehicle_number="", vehicle_type="O", transport_doc_no="A1", transport_doc_date="2026-06-20")
    assert [e.field for e in validate_form_data(form)] == ["vehicle_type"]


def test_distance_limits():
    assert [e.field for e in validate_form_data(_complete_form(distance_km=4001))] == ["distance_km"]
    assert validate_form_data(_complete_form(distance_km=4000)) == []
    same_pin = dict(seller_pincode="560001", buyer_pincode="560001")
    assert [e.field for e in validate_form_data(_complete_form(distance_km=101, **same_pin))] == ["distance_km"]
    assert validate_form_data(_complete_form(distance_km=100, **same_pin)) == []


@pytest.mark.parametrize("code", ["2", "4", "5", "6", "7", "8", "10", "11", "12"])
def test_sub_supply_types_nic_does_not_allow_on_a_tax_invoice(code):
    assert [e.field for e in validate_form_data(_complete_form(sub_supply_type=code))] == ["sub_supply_type"]


@pytest.mark.parametrize("code", ["1", "9"])
def test_sub_supply_types_nic_allows_on_a_tax_invoice(code):
    assert validate_form_data(_complete_form(sub_supply_type=code)) == []


def test_export_needs_an_unregistered_buyer_in_other_country():
    errors = validate_form_data(_complete_form(sub_supply_type="3"))
    assert {e.field for e in errors} == {"buyer_gstin", "buyer_state_code"}
    assert validate_form_data(_complete_form(
        sub_supply_type="3", buyer_gstin="", buyer_state_code="99", ship_to_state_code="27",
    )) == []


def test_tax_must_agree_with_the_states(db_session, company, buyer):
    igst_invoice = _make_invoice(db_session, company, buyer, igst=True)
    same_state = _complete_form(buyer_state_code="29", buyer_gstin="29BBBCT5678R3Z1")
    assert [e.field for e in validate_form_against_invoice(same_state, igst_invoice)] == ["buyer_state_code"]
    assert validate_form_against_invoice(_complete_form(), igst_invoice) == []


def test_only_services_is_refused(db_session, invoice, product_with_hsn):
    item = _item(invoice, product_with_hsn, hsn="998313")
    db_session.add(item)
    db_session.flush()
    errors = validate_invoice(invoice, [item], {product_with_hsn.id: product_with_hsn})
    assert [e.field for e in errors] == ["invoice_items"]


def test_hsn_must_be_four_six_or_eight_digits(db_session, invoice, product_with_hsn):
    item = _item(invoice, product_with_hsn, hsn="12345")
    db_session.add(item)
    db_session.flush()
    errors = validate_invoice(invoice, [item], {product_with_hsn.id: product_with_hsn})
    assert errors and "4, 6 or 8 digits" in errors[0].message


def test_long_invoice_number_is_refused(invoice, invoice_items, product_with_hsn):
    invoice.invoice_number = "INV-2026-27-000000001"
    errors = validate_invoice(invoice, invoice_items, {product_with_hsn.id: product_with_hsn})
    assert [e.field for e in errors] == ["invoice_number"]
    invoice.invoice_number = "INV/26.27-00001"
    assert validate_invoice(invoice, invoice_items, {product_with_hsn.id: product_with_hsn}) == []


# ── the invoice's saved details ──

def test_pre_check_prefers_the_invoice_over_changed_master_records(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    company.name = "Renamed Corp"
    company.gst = "07AAMPB1274B1Z8"
    company.address = "New Office\nDelhi\n110001"
    buyer.name = "Renamed Buyer"
    buyer.gst = "07BBBCD5678R2Z9"
    buyer.address = "New Warehouse\nDelhi\n110002"
    invoice.company_name = "Test Corp"
    invoice.company_gst = "29AABCT1234Q1Z5"
    invoice.company_address = "123 Main Street\nBangalore\n560001"
    invoice.ledger_name = "Best Buyer Ltd"
    invoice.ledger_gst = "27BBBCD5678R2Z9"
    invoice.ledger_address = "456 Tech Park\nMumbai\n400001"
    db_session.flush()

    form = pre_check(invoice, company, buyer, invoice_items, {product_with_hsn.id: product_with_hsn}).form_data

    assert (form.seller_trade_name, form.seller_gstin, form.seller_pincode) == ("Test Corp", "29AABCT1234Q1Z5", "560001")
    assert (form.buyer_trade_name, form.buyer_gstin, form.buyer_pincode) == ("Best Buyer Ltd", "27BBBCD5678R2Z9", "400001")
    assert form.seller_state_code == "29"
    assert form.buyer_state_code == "27"


def test_pre_check_falls_back_when_the_snapshot_is_blank(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    for attr in ("company_name", "company_gst", "company_address", "ledger_name", "ledger_gst", "ledger_address"):
        setattr(invoice, attr, None)
    db_session.flush()

    form = pre_check(invoice, company, buyer, invoice_items, {product_with_hsn.id: product_with_hsn}).form_data

    assert (form.seller_trade_name, form.seller_gstin) == (company.name, company.gst)
    assert (form.buyer_trade_name, form.buyer_gstin) == (buyer.name, buyer.gst)
    assert form.buyer_address_1 == "456 Tech Park"


def test_a_buyer_who_registered_later_stays_unregistered_on_the_bill(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    invoice.ledger_name = "Best Buyer Ltd"
    invoice.ledger_gst = None
    buyer.gst = "27BBBCD5678R2Z9"
    db_session.flush()
    form = pre_check(invoice, company, buyer, invoice_items, {product_with_hsn.id: product_with_hsn}).form_data
    assert form.buyer_gstin == ""


# ── ship-to ──

def test_shipping_address_becomes_a_bill_to_ship_to(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    invoice.shipping_address = "Warehouse 9\nPune\n411001"
    db_session.flush()
    result = pre_check(invoice, company, buyer, invoice_items, {product_with_hsn.id: product_with_hsn})
    form = result.form_data

    assert form.transaction_type == "2"
    assert (form.buyer_address_1, form.buyer_address_2) == ("Warehouse 9", "Pune, 411001")
    assert form.buyer_pincode == "411001"
    # The Bill To party is still the buyer.
    assert form.buyer_trade_name == "Best Buyer Ltd"
    assert form.buyer_gstin == "27BBBCD5678R2Z9"
    assert form.buyer_state_code == "27"
    assert form.ship_to_state_code == "27"
    assert any(e.field == "ship_to_state_code" for e in result.missing_fields)


def test_shipping_address_without_a_pin_does_not_borrow_the_billing_pin(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    invoice.shipping_address = "Warehouse 9, Pune"
    db_session.flush()
    result = pre_check(invoice, company, buyer, invoice_items, {product_with_hsn.id: product_with_hsn})
    assert result.form_data.buyer_pincode == ""
    assert any(e.field == "buyer_pincode" and "shipping address" in e.message for e in result.missing_fields)


def test_shipping_address_same_as_billing_stays_regular(db_session, invoice, invoice_items, company, buyer, product_with_hsn):
    invoice.shipping_address = "456 Tech Park \n Mumbai\n400001"
    db_session.flush()
    form = pre_check(invoice, company, buyer, invoice_items, {product_with_hsn.id: product_with_hsn}).form_data
    assert form.transaction_type == "1"


def test_ship_to_party_goes_where_nic_says(db_session, invoice, invoice_items, product_with_hsn):
    """Bill To: toGstin, toTrdName, toStateCode. Ship To: address, place, PIN, actualToStateCode."""
    form = _complete_form(
        transaction_type="2",
        buyer_gstin="27BBBCD5678R2Z9", buyer_trade_name="Bill To Ltd", buyer_state_code="27",
        buyer_address_1="Ship Street", buyer_place="Surat", buyer_pincode="395003", ship_to_state_code="24",
    )
    assert validate_form_data(form) == []
    bill = generate_eway_bill_json(invoice, invoice_items, {product_with_hsn.id: product_with_hsn}, form)["billLists"][0]
    assert (bill["toGstin"], bill["toTrdName"], bill["toStateCode"]) == ("27BBBCD5678R2Z9", "Bill To Ltd", 27)
    assert (bill["toAddr1"], bill["toPlace"], bill["toPincode"], bill["actualToStateCode"]) == ("Ship Street", "Surat", 395003, 24)
    assert bill["transType"] == 2


def test_dispatch_from_party_goes_where_nic_says(db_session, invoice, invoice_items, product_with_hsn):
    form = _complete_form(transaction_type="3", seller_state_code="29", dispatch_state_code="33")
    assert validate_form_data(form) == []
    bill = generate_eway_bill_json(invoice, invoice_items, {product_with_hsn.id: product_with_hsn}, form)["billLists"][0]
    assert (bill["fromStateCode"], bill["actualFromStateCode"], bill["transType"]) == (29, 33, 3)


def test_regular_transaction_needs_matching_states():
    errors = validate_form_data(_complete_form(transaction_type="1", ship_to_state_code="24"))
    assert [e.field for e in errors] == ["ship_to_state_code"]
    errors = validate_form_data(_complete_form(transaction_type="1", dispatch_state_code="33"))
    assert [e.field for e in errors] == ["dispatch_state_code"]


def test_blank_actual_states_mean_same_as_bill_states(db_session, invoice, invoice_items, product_with_hsn):
    bill = generate_eway_bill_json(invoice, invoice_items, {product_with_hsn.id: product_with_hsn}, _complete_form())["billLists"][0]
    assert bill["actualFromStateCode"] == bill["fromStateCode"] == 29
    assert bill["actualToStateCode"] == bill["toStateCode"] == 27


# ── saving a transporter ──

def _transporter(db_session, company, name, **kwargs):
    t = EwayBillTransporter(company_id=company.id, transporter_name=name, **kwargs)
    db_session.add(t)
    db_session.flush()
    return t


def test_saving_over_an_existing_transporter_clears_the_previous_default(db_session, company):
    old_default = _transporter(db_session, company, "Old Default", is_default=True)
    existing = _transporter(db_session, company, "Existing", is_default=False)

    save_default_transporter(db_session, company.id, _complete_form(transporter_name="Existing", transporter_gstin="07AAMPB1274B1Z8"))
    db_session.flush()
    db_session.expire_all()

    assert existing.is_default is True
    assert existing.transporter_gstin == "07AAMPB1274B1Z8"
    assert old_default.is_default is False
    assert db_session.query(EwayBillTransporter).filter_by(company_id=company.id, is_default=True).count() == 1


def test_saving_a_new_transporter_clears_the_previous_default(db_session, company):
    old_default = _transporter(db_session, company, "Old Default", is_default=True)

    created = save_default_transporter(db_session, company.id, _complete_form(transporter_name="Brand New"))
    db_session.flush()
    db_session.expire_all()

    assert created.is_default is True
    assert old_default.is_default is False
    assert db_session.query(EwayBillTransporter).filter_by(company_id=company.id).count() == 2


def test_saving_a_transporter_leaves_other_companies_alone(db_session, company):
    other = CompanyProfile(name="Other", address="x", gst="", phone_number="1", currency_code="INR")
    db_session.add(other)
    db_session.flush()
    theirs = _transporter(db_session, other, "Theirs", is_default=True)

    save_default_transporter(db_session, company.id, _complete_form(transporter_name="Mine"))
    db_session.flush()
    db_session.expire_all()

    assert theirs.is_default is True


# ── schema ──

def test_transporter_foreign_key_cascades_like_its_migration():
    foreign_key = next(iter(EwayBillTransporter.__table__.c.company_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"


def test_thresholds_are_typed_like_the_other_money_columns():
    from sqlalchemy import Numeric

    for column in ("eway_local_threshold", "eway_interstate_threshold"):
        assert isinstance(CompanyProfile.__table__.c[column].type, Numeric), column
        assert CompanyProfile.__table__.c[column].server_default is not None, column
