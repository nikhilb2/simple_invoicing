"""
E-Way Bill (EWB) JSON generation service.

Generates GST/NIC portal-compliant E-Way Bill JSON from invoice data,
company profile, buyer data, and user-supplied transport details.
"""

import json
import re
from datetime import datetime
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


def extract_state_code(gstin: str | None) -> str:
    """Extract the 2-digit state code from a GSTIN."""
    if gstin and len(gstin) >= 2:
        return gstin[:2]
    return "00"


def _money(val: float | Decimal) -> float:
    return round(float(val), 2)


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

    # Build pre-filled form data from existing data
    seller_gstin = company.gst or ""
    seller_trade_name = company.name or ""
    seller_addr_parts = (company.address or "").split("\n")
    seller_address_1 = seller_addr_parts[0] if seller_addr_parts else ""
    seller_address_2 = "\n".join(seller_addr_parts[1:]) if len(seller_addr_parts) > 1 else ""

    seller_state_code = extract_state_code(seller_gstin)
    seller_place = STATE_CODES.get(seller_state_code, "")

    # Parse pincode from address
    seller_pincode = _extract_pincode(company.address or "")
    buyer_pincode = _extract_pincode(buyer.address if buyer else "")
    buyer_gstin = buyer.gst if buyer else (invoice.ledger_gst or "")
    buyer_trade_name = buyer.name if buyer else (invoice.ledger_name or "")
    buyer_addr_parts = (buyer.address if buyer else (invoice.ledger_address or "")).split("\n")
    buyer_address_1 = buyer_addr_parts[0] if buyer_addr_parts else ""
    buyer_address_2 = "\n".join(buyer_addr_parts[1:]) if len(buyer_addr_parts) > 1 else ""
    buyer_state_code = extract_state_code(buyer_gstin)
    buyer_place = STATE_CODES.get(buyer_state_code, "")

    # Validate seller GSTIN
    if not seller_gstin:
        errors.append(EwayBillValidationError(field="seller_gstin", message="Company GSTIN is not set. Please configure it in Company Settings."))
    elif not GSTIN_REGEX.match(seller_gstin):
        errors.append(EwayBillValidationError(field="seller_gstin", message="Company GSTIN format is invalid."))

    # Validate buyer GSTIN (mandatory for EWB)
    if not buyer_gstin:
        missing.append(EwayBillValidationError(field="buyer_gstin", message="Buyer GSTIN is required for E-Way Bill."))
    elif not GSTIN_REGEX.match(buyer_gstin):
        errors.append(EwayBillValidationError(field="buyer_gstin", message="Buyer GSTIN format is invalid."))

    # Check HSN codes on all items
    item_errors: list[EwayBillValidationError] = []
    for inv_item in (items or []):
        hsn = inv_item.hsn_sac or (products_map.get(inv_item.product_id).hsn_sac if products_map.get(inv_item.product_id) else None)
        if not hsn or not hsn.strip():
            product_name = products_map.get(inv_item.product_id).name if products_map.get(inv_item.product_id) else f"Product #{inv_item.product_id}"
            item_errors.append(EwayBillValidationError(
                field=f"item_{inv_item.id}_hsn",
                message=f"Item '{product_name}' is missing HSN/SAC code. Please add it in Products."
            ))

    valid = len(errors) == 0

    form_data = EwayBillFormData(
        seller_gstin=seller_gstin,
        seller_trade_name=seller_trade_name,
        seller_address_1=seller_address_1,
        seller_address_2=seller_address_2,
        seller_place=seller_place,
        seller_state_code=seller_state_code,
        seller_pincode=seller_pincode,
        buyer_gstin=buyer_gstin,
        buyer_trade_name=buyer_trade_name,
        buyer_address_1=buyer_address_1,
        buyer_address_2=buyer_address_2,
        buyer_place=buyer_place,
        buyer_state_code=buyer_state_code,
        buyer_pincode=buyer_pincode,
    )

    return EwayBillPreCheckResult(
        valid=valid,
        missing_fields=missing,
        form_data=form_data,
        item_validation=item_errors,
    )


def validate_form_data(form: EwayBillFormData) -> list[EwayBillValidationError]:
    """Validate the complete form data before generating JSON."""
    errors: list[EwayBillValidationError] = []

    # GSTIN validation
    for field, label in [("seller_gstin", "Seller GSTIN"), ("buyer_gstin", "Buyer GSTIN")]:
        val = getattr(form, field, "")
        if not val:
            errors.append(EwayBillValidationError(field=field, message=f"{label} is required."))
        elif not GSTIN_REGEX.match(val):
            errors.append(EwayBillValidationError(field=field, message=f"{label} format is invalid."))

    # State codes
    for field, label in [("seller_state_code", "Seller State Code"), ("buyer_state_code", "Buyer State Code")]:
        val = getattr(form, field, "")
        if not val or val == "00":
            errors.append(EwayBillValidationError(field=field, message=f"{label} is required and must be a valid 2-digit code."))

    # Pincodes
    for field, label in [("seller_pincode", "Seller Pincode"), ("buyer_pincode", "Buyer Pincode")]:
        val = getattr(form, field, "")
        if val and not re.match(r"^\d{6}$", val):
            errors.append(EwayBillValidationError(field=field, message=f"{label} must be a 6-digit number."))

    # Supply details
    if not form.supply_type:
        errors.append(EwayBillValidationError(field="supply_type", message="Supply type is required."))
    if not form.sub_supply_type:
        errors.append(EwayBillValidationError(field="sub_supply_type", message="Sub-supply type is required."))

    # Transport
    if form.transport_mode == "1" and form.vehicle_number:
        if not VEHICLE_REGEX.match(form.vehicle_number.upper()):
            errors.append(EwayBillValidationError(field="vehicle_number", message="Vehicle number format is invalid (e.g., HR55AB1234)."))

    if form.distance_km is not None and form.distance_km <= 0:
        errors.append(EwayBillValidationError(field="distance_km", message="Distance must be a positive number."))

    return errors


def generate_eway_bill_json(
    invoice: Invoice,
    company: CompanyProfile,
    buyer: Buyer | None,
    items: list[InvoiceItem],
    products_map: dict[int, Product],
    form: EwayBillFormData,
) -> str:
    """Generate the NIC-compliant E-Way Bill JSON string."""
    # Validate transport mode
    transport_mode_map = {"1": "1", "2": "2", "3": "3", "4": "4"}
    trans_mode = transport_mode_map.get(form.transport_mode, "1")

    # Build item list for JSON
    bill_items = []
    for inv_item in (items or []):
        product = products_map.get(inv_item.product_id)
        hsn = inv_item.hsn_sac or (product.hsn_sac if product else "")
        gst_rate = float(inv_item.gst_rate or 0)
        half_rate = gst_rate / 2

        # Determine if IGST or CGST+SGST
        interstate = extract_state_code(form.seller_gstin) != extract_state_code(form.buyer_gstin)

        bill_items.append({
            "productName": product.name if product else "",
            "productDesc": inv_item.description or (product.description if product else "") or "",
            "hsnCode": hsn,
            "quantity": float(inv_item.quantity or 0),
            "qtyUnit": product.unit if product and product.unit else "NOS",
            "taxableAmount": _money(inv_item.taxable_amount or 0),
            "cgstRate": 0 if interstate else half_rate,
            "sgstRate": 0 if interstate else half_rate,
            "igstRate": gst_rate if interstate else 0,
            "cessRate": 0,
        })

    # Determine document type
    doc_type = "INV"
    if invoice.voucher_type == "purchase":
        doc_type = "INV"  # Still INV for purchases

    # Format invoice date
    inv_date = invoice.invoice_date
    if isinstance(inv_date, datetime):
        doc_date = inv_date.strftime("%d/%m/%Y")
    else:
        doc_date = inv_date.strftime("%d/%m/%Y") if hasattr(inv_date, "strftime") else str(inv_date)[:10]

    # Build the single bill entry
    bill_entry = {
        "userGstin": form.seller_gstin,
        "supplyType": form.supply_type,
        "subSupplyType": form.sub_supply_type,
        "docType": doc_type,
        "docNo": invoice.invoice_number or str(invoice.id),
        "docDate": doc_date,
        "fromGstin": form.seller_gstin,
        "fromTrdName": form.seller_trade_name,
        "fromAddr1": form.seller_address_1,
        "fromAddr2": form.seller_address_2,
        "fromPlace": form.seller_place,
        "fromPincode": int(form.seller_pincode) if form.seller_pincode.isdigit() else 0,
        "actFromStateCode": int(form.seller_state_code) if form.seller_state_code.isdigit() else 0,
        "fromStateCode": int(form.seller_state_code) if form.seller_state_code.isdigit() else 0,
        "toGstin": form.buyer_gstin,
        "toTrdName": form.buyer_trade_name,
        "toAddr1": form.buyer_address_1,
        "toAddr2": form.buyer_address_2,
        "toPlace": form.buyer_place,
        "toPincode": int(form.buyer_pincode) if form.buyer_pincode.isdigit() else 0,
        "actToStateCode": int(form.buyer_state_code) if form.buyer_state_code.isdigit() else 0,
        "toStateCode": int(form.buyer_state_code) if form.buyer_state_code.isdigit() else 0,
        "totalValue": _money(invoice.total_amount or 0),
        "cgstValue": _money(invoice.cgst_amount or 0),
        "sgstValue": _money(invoice.sgst_amount or 0),
        "igstValue": _money(invoice.igst_amount or 0),
        "cessValue": 0,
        "totInvValue": _money(invoice.total_amount or 0),
        "transMode": int(trans_mode),
        "transDistance": form.distance_km or 0,
        "transporterName": form.transporter_name or "",
        "transporterId": form.transporter_gstin or "",
        "vehicleNo": form.vehicle_number or "",
        "vehicleType": form.vehicle_type or "R",
        "itemList": bill_items,
    }

    output = EwayBillOutput(version="1.0.1118", billLists=[bill_entry])
    return output.model_dump(by_alias=True, exclude_none=True)


def _extract_pincode(address: str) -> str:
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
            EwayBillTransporter.is_default == True,
        )
        .first()
    )
