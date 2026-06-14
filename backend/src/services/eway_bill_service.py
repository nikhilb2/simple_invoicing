"""
E-Way Bill (EWB) JSON generation service.

Generates GST/NIC portal-compliant E-Way Bill JSON from invoice data,
company profile, buyer data, and user-supplied transport details.

The output targets the NIC bulk-upload schema (version 1.0.1118) used by
https://ewaybillgst.gov.in — so codes (sub-supply, transaction, transport
mode) are emitted as the numeric values NIC expects, not human labels.
"""

import re
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.eway_bill import EwayBillTransporter
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.schemas.eway_bill import (
    EwayBillFormData,
    EwayBillValidationError,
    EwayBillPreCheckResult,
    EwayBillOutput,
)


# Indian state code mapping (first 2 digits of GSTIN)
STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh (pre-split)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory",
}

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
VEHICLE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{1,4}$")

# NIC sub-supply type codes (subSupplyType). The frontend sends these codes.
SUB_SUPPLY_CODES = {
    "1": "Supply",
    "2": "Import",
    "3": "Export",
    "4": "Job Work",
    "5": "For Own Use",
    "7": "Sales Return",
    "8": "Others",
    "10": "Line Sales",
    "12": "Exhibition or Fairs",
}
SUB_SUPPLY_OTHERS_CODE = "8"

# NIC transaction type codes (transactionType).
TRANSACTION_TYPE_CODES = {"1", "2", "3", "4"}

# NIC transport mode codes (transMode): 1=Road, 2=Rail, 3=Air, 4=Ship.
TRANSPORT_MODE_CODES = {"1", "2", "3", "4"}
ROAD_MODE = "1"

# GSTIN value used for unregistered (B2C) recipients on the NIC portal.
UNREGISTERED_GSTIN = "URP"


def extract_state_code(gstin: str | None) -> str:
    """Extract the 2-digit state code from a GSTIN."""
    if gstin and len(gstin) >= 2 and gstin[:2].isdigit():
        return gstin[:2]
    return "00"


def _money(val: float | Decimal | None) -> float:
    return round(float(val or 0), 2)


def _s(val: str | None) -> str:
    """Coerce a possibly-None DB value into a stripped string."""
    return (val or "").strip()


def pre_check(
    invoice: Invoice,
    company: CompanyProfile,
    buyer: Buyer | None,
    items: list[InvoiceItem],
    products_map: dict[int, Product],
) -> EwayBillPreCheckResult:
    """Check what data is available and what's missing before showing the form."""
    errors: list[EwayBillValidationError] = []
    missing: list[EwayBillValidationError] = []

    # ── Seller details (from company profile) ──
    seller_gstin = _s(company.gst)
    seller_trade_name = _s(company.name)
    seller_address = _s(company.address)
    seller_addr_parts = seller_address.split("\n")
    seller_address_1 = seller_addr_parts[0] if seller_addr_parts else ""
    seller_address_2 = "\n".join(seller_addr_parts[1:]) if len(seller_addr_parts) > 1 else ""
    seller_state_code = extract_state_code(seller_gstin)
    seller_place = STATE_CODES.get(seller_state_code, "")
    seller_pincode = _extract_pincode(seller_address)

    # ── Buyer details (from Buyer record, falling back to invoice ledger snapshot) ──
    buyer_gstin = _s(buyer.gst) if buyer else _s(invoice.ledger_gst)
    buyer_trade_name = _s(buyer.name) if buyer else _s(invoice.ledger_name)
    buyer_address = _s(buyer.address) if buyer else _s(invoice.ledger_address)
    buyer_addr_parts = buyer_address.split("\n")
    buyer_address_1 = buyer_addr_parts[0] if buyer_addr_parts else ""
    buyer_address_2 = "\n".join(buyer_addr_parts[1:]) if len(buyer_addr_parts) > 1 else ""
    buyer_state_code = extract_state_code(buyer_gstin)
    buyer_place = STATE_CODES.get(buyer_state_code, "")
    buyer_pincode = _extract_pincode(buyer_address)

    # ── E-Way Bill module enabled check ──
    eway_enabled = bool(getattr(company, "eway_enabled", True))
    if not eway_enabled:
        errors.append(EwayBillValidationError(
            field="eway_disabled",
            message="E-Way Bill generation is disabled in Company Settings.",
        ))

    # ── Seller GSTIN (mandatory) ──
    if not seller_gstin:
        errors.append(EwayBillValidationError(
            field="seller_gstin",
            message="Company GSTIN is not set. Please configure it in Company Settings.",
        ))
    elif not GSTIN_REGEX.match(seller_gstin):
        errors.append(EwayBillValidationError(
            field="seller_gstin",
            message="Company GSTIN format is invalid.",
        ))

    # ── Buyer GSTIN (optional — empty means B2C / unregistered → "URP") ──
    if not buyer_gstin:
        missing.append(EwayBillValidationError(
            field="buyer_gstin",
            message="Buyer GSTIN is not set. It will be treated as unregistered (URP). "
                    "Add the buyer's state code below.",
        ))
    elif not GSTIN_REGEX.match(buyer_gstin):
        errors.append(EwayBillValidationError(
            field="buyer_gstin",
            message="Buyer GSTIN format is invalid.",
        ))

    # ── HSN/SAC codes on all items (mandatory for EWB) ──
    item_errors: list[EwayBillValidationError] = []
    for inv_item in (items or []):
        product = products_map.get(inv_item.product_id)
        hsn = _s(inv_item.hsn_sac) or (_s(product.hsn_sac) if product else "")
        if not hsn:
            product_name = product.name if product else f"Product #{inv_item.product_id}"
            item_errors.append(EwayBillValidationError(
                field=f"item_{inv_item.id}_hsn",
                message=f"Item '{product_name}' is missing HSN/SAC code. Please add it in Products.",
            ))

    # ── Threshold evaluation (guidance only, never blocks) ──
    interstate = float(invoice.igst_amount or 0) > 0
    local_threshold = float(getattr(company, "eway_local_threshold", 100000) or 0)
    interstate_threshold = float(getattr(company, "eway_interstate_threshold", 50000) or 0)
    threshold_value = interstate_threshold if interstate else local_threshold
    invoice_value = _money(invoice.total_amount)

    threshold_warning: str | None = None
    if invoice_value < threshold_value:
        threshold_warning = (
            f"This invoice (₹{invoice_value:,.2f}) is below the configured "
            f"{'interstate' if interstate else 'local'} E-Way Bill threshold "
            f"(₹{threshold_value:,.2f}). Generate only if required."
        )

    valid = len(errors) == 0

    form_data = EwayBillFormData(
        seller_gstin=seller_gstin,
        seller_trade_name=seller_trade_name,
        seller_address_1=seller_address_1,
        seller_address_2=seller_address_2,
        seller_place=seller_place,
        seller_state_code=seller_state_code if seller_state_code != "00" else "",
        seller_pincode=seller_pincode,
        buyer_gstin=buyer_gstin,
        buyer_trade_name=buyer_trade_name,
        buyer_address_1=buyer_address_1,
        buyer_address_2=buyer_address_2,
        buyer_place=buyer_place,
        buyer_state_code=buyer_state_code if buyer_state_code != "00" else "",
        buyer_pincode=buyer_pincode,
    )

    return EwayBillPreCheckResult(
        valid=valid,
        errors=errors,
        missing_fields=missing,
        form_data=form_data,
        item_validation=item_errors,
        eway_enabled=eway_enabled,
        threshold_warning=threshold_warning,
        eway_local_threshold=local_threshold,
        eway_interstate_threshold=interstate_threshold,
    )


def validate_form_data(form: EwayBillFormData) -> list[EwayBillValidationError]:
    """Validate the complete form data before generating JSON."""
    errors: list[EwayBillValidationError] = []

    # Seller GSTIN — required and well-formed.
    seller_gstin = _s(form.seller_gstin)
    if not seller_gstin:
        errors.append(EwayBillValidationError(field="seller_gstin", message="Seller GSTIN is required."))
    elif not GSTIN_REGEX.match(seller_gstin):
        errors.append(EwayBillValidationError(field="seller_gstin", message="Seller GSTIN format is invalid."))

    # Buyer GSTIN — optional (empty = unregistered/URP), but if present must be valid.
    buyer_gstin = _s(form.buyer_gstin)
    if buyer_gstin and not GSTIN_REGEX.match(buyer_gstin):
        errors.append(EwayBillValidationError(field="buyer_gstin", message="Buyer GSTIN format is invalid."))

    # State codes — both required (used for addressing and intra/inter-state nature).
    for field, label in [("seller_state_code", "Seller State Code"), ("buyer_state_code", "Buyer State Code")]:
        val = _s(getattr(form, field, ""))
        if not val or val == "00" or not re.match(r"^\d{2}$", val):
            errors.append(EwayBillValidationError(
                field=field,
                message=f"{label} is required and must be a valid 2-digit code.",
            ))

    # Pincodes — optional but must be 6 digits when present.
    for field, label in [("seller_pincode", "Seller Pincode"), ("buyer_pincode", "Buyer Pincode")]:
        val = _s(getattr(form, field, ""))
        if val and not re.match(r"^\d{6}$", val):
            errors.append(EwayBillValidationError(field=field, message=f"{label} must be a 6-digit number."))

    # Supply details.
    if form.supply_type not in ("O", "I"):
        errors.append(EwayBillValidationError(field="supply_type", message="Supply type must be Outward (O) or Inward (I)."))
    if form.transaction_type not in TRANSACTION_TYPE_CODES:
        errors.append(EwayBillValidationError(field="transaction_type", message="Transaction type is required."))
    if form.sub_supply_type not in SUB_SUPPLY_CODES:
        errors.append(EwayBillValidationError(field="sub_supply_type", message="Sub-supply type is required."))
    if form.sub_supply_type == SUB_SUPPLY_OTHERS_CODE and not _s(form.sub_supply_desc):
        errors.append(EwayBillValidationError(
            field="sub_supply_desc",
            message="Sub-supply description is required when 'Others' is selected.",
        ))

    # Transport.
    if form.transport_mode not in TRANSPORT_MODE_CODES:
        errors.append(EwayBillValidationError(field="transport_mode", message="Transport mode is invalid."))
    vehicle_number = _s(form.vehicle_number)
    if form.transport_mode == ROAD_MODE and vehicle_number:
        if not VEHICLE_REGEX.match(vehicle_number.upper()):
            errors.append(EwayBillValidationError(
                field="vehicle_number",
                message="Vehicle number format is invalid (e.g., HR55AB1234).",
            ))

    if form.distance_km is not None and form.distance_km < 0:
        errors.append(EwayBillValidationError(field="distance_km", message="Distance cannot be negative."))

    return errors


def generate_eway_bill_json(
    invoice: Invoice,
    company: CompanyProfile,
    buyer: Buyer | None,
    items: list[InvoiceItem],
    products_map: dict[int, Product],
    form: EwayBillFormData,
) -> dict:
    """Build the NIC-compliant E-Way Bill JSON (returns a dict)."""
    # The tax nature is whatever the invoice actually computed at creation time,
    # not a re-derivation from form state codes — this keeps item rates and the
    # bill-level CGST/SGST/IGST values internally consistent.
    interstate = float(invoice.igst_amount or 0) > 0

    # ── Item list ──
    bill_items = []
    for inv_item in (items or []):
        product = products_map.get(inv_item.product_id)
        hsn = _s(inv_item.hsn_sac) or (_s(product.hsn_sac) if product else "")
        gst_rate = float(inv_item.gst_rate or 0)
        half_rate = round(gst_rate / 2, 3)

        bill_items.append({
            "productName": (product.name if product else "") or "",
            "productDesc": _s(inv_item.description) or (_s(product.description) if product else "") or (product.name if product else ""),
            "hsnCode": int(hsn) if hsn.isdigit() else hsn,
            "quantity": float(inv_item.quantity or 0),
            "qtyUnit": (product.unit if product and product.unit else "NOS").upper()[:3],
            "taxableAmount": _money(inv_item.taxable_amount),
            "cgstRate": 0 if interstate else half_rate,
            "sgstRate": 0 if interstate else half_rate,
            "igstRate": gst_rate if interstate else 0,
            "cessRate": 0,
            "cessNonAdvol": 0,
        })

    # ── Document date (NIC wants DD/MM/YYYY) ──
    inv_date = invoice.invoice_date
    if hasattr(inv_date, "strftime"):
        doc_date = inv_date.strftime("%d/%m/%Y")
    else:
        doc_date = str(inv_date)[:10]

    # ── Recipient GSTIN: unregistered buyers go in as "URP" ──
    buyer_gstin = _s(form.buyer_gstin) or UNREGISTERED_GSTIN

    seller_state = int(form.seller_state_code) if _s(form.seller_state_code).isdigit() else 0
    buyer_state = int(form.buyer_state_code) if _s(form.buyer_state_code).isdigit() else 0

    # ── Money totals (otherValue balances rounding so totInvValue reconciles) ──
    taxable = _money(invoice.taxable_amount)
    cgst = _money(invoice.cgst_amount)
    sgst = _money(invoice.sgst_amount)
    igst = _money(invoice.igst_amount)
    tot_inv = _money(invoice.total_amount)
    other_value = round(tot_inv - (taxable + cgst + sgst + igst), 2)

    sub_supply_desc = _s(form.sub_supply_desc) if form.sub_supply_type == SUB_SUPPLY_OTHERS_CODE else ""

    bill_entry = {
        "userGstin": _s(form.seller_gstin),
        "supplyType": form.supply_type or "O",
        "subSupplyType": form.sub_supply_type or "1",
        "subSupplyDesc": sub_supply_desc,
        "docType": "INV",
        "docNo": invoice.invoice_number or str(invoice.id),
        "docDate": doc_date,
        "transactionType": int(form.transaction_type) if _s(form.transaction_type).isdigit() else 1,
        "fromGstin": _s(form.seller_gstin),
        "fromTrdName": _s(form.seller_trade_name),
        "fromAddr1": _s(form.seller_address_1),
        "fromAddr2": _s(form.seller_address_2),
        "fromPlace": _s(form.seller_place),
        "fromPincode": int(form.seller_pincode) if _s(form.seller_pincode).isdigit() else 0,
        "actFromStateCode": seller_state,
        "fromStateCode": seller_state,
        "toGstin": buyer_gstin,
        "toTrdName": _s(form.buyer_trade_name),
        "toAddr1": _s(form.buyer_address_1),
        "toAddr2": _s(form.buyer_address_2),
        "toPlace": _s(form.buyer_place),
        "toPincode": int(form.buyer_pincode) if _s(form.buyer_pincode).isdigit() else 0,
        "actToStateCode": buyer_state,
        "toStateCode": buyer_state,
        "totalValue": taxable,
        "cgstValue": cgst,
        "sgstValue": sgst,
        "igstValue": igst,
        "cessValue": 0,
        "TotNonAdvolVal": 0,
        "otherValue": other_value,
        "totInvValue": tot_inv,
        "transMode": int(form.transport_mode) if _s(form.transport_mode).isdigit() else 1,
        "transDistance": form.distance_km or 0,
        "transporterName": _s(form.transporter_name),
        "transporterId": _s(form.transporter_gstin),
        "transDocNo": "",
        "transDocDate": "",
        "vehicleNo": _s(form.vehicle_number).upper(),
        "vehicleType": form.vehicle_type or "R",
        "itemList": bill_items,
    }

    output = EwayBillOutput(version="1.0.1118", bill_lists=[bill_entry])
    return output.model_dump(by_alias=True)


def _extract_pincode(address: str | None) -> str:
    """Extract a 6-digit pincode from an address string."""
    if not address:
        return ""
    match = re.search(r"\b(\d{6})\b", address)
    return match.group(1) if match else ""


def get_or_create_default_transporter(db: Session, company_id: int) -> Optional[EwayBillTransporter]:
    """Get the default transporter for a company, or None."""
    return (
        db.query(EwayBillTransporter)
        .filter(
            EwayBillTransporter.company_id == company_id,
            EwayBillTransporter.is_default.is_(True),
        )
        .first()
    )
