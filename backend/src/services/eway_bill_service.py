"""
E-Way Bill (EWB) JSON generation service.

Builds the file for the bulk generation upload on the e-way bill portal from an
invoice's saved details and the transport details the user supplies. The format
and codes are in src/core/eway_bill_codes.py. A real upload has not been tested,
so a generated file is not proven to be accepted by the portal.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from src.core.eway_bill_codes import (
    AIR_MODE,
    DISALLOWED_TEXT_REGEX,
    DOC_NO_REGEX,
    INVOICE_SUB_SUPPLY_CODES,
    MAX_ADDRESS_LENGTH,
    MAX_DESC_LENGTH,
    MAX_DISTANCE_KM,
    MAX_ITEMS,
    MAX_NAME_LENGTH,
    MAX_PLACE_LENGTH,
    MAX_SAME_PIN_DISTANCE_KM,
    MAX_TRANSPORT_DOC_NO_LENGTH,
    NIC_JSON_VERSION,
    NIC_UQC_CODES,
    OTHER_COUNTRY_STATE_CODES,
    RAIL_MODE,
    ROAD_MODE,
    SHIP_MODE,
    SUB_SUPPLY_EXPORT,
    TRANSACTION_BILL_FROM_DISPATCH_FROM,
    TRANSACTION_BILL_TO_SHIP_TO,
    TRANSACTION_REGULAR,
    TRANSACTION_TYPE_CODES,
    TRANSPORT_MODE_CODES,
    TRANSPORTER_ID_REGEX,
    VEHICLE_REGEX,
    VEHICLE_TYPE_CODES,
    VEHICLE_TYPE_ODC,
)
from src.core.validation import GSTIN_REGEX, HSN_SAC_REGEX
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.eway_bill import EwayBillTransporter
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.schemas.eway_bill import (
    EwayBillFormData,
    EwayBillOutput,
    EwayBillPreCheckResult,
    EwayBillValidationError,
)
from src.services.uqc import uqc_for_unit


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

# GSTIN value used for unregistered (B2C) recipients on the NIC portal.
UNREGISTERED_GSTIN = "URP"

# fromPincode and toPincode are integers from 100000 to 999999, so a PIN cannot
# start with a zero. Addresses often write one as "560 029".
_ADDRESS_PINCODE_REGEX = re.compile(r"(?<!\d)([1-9]\d{2})\s?(\d{3})(?!\d)")
_PINCODE_REGEX = re.compile(r"^[1-9]\d{5}$")


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


def _nic_text(val: str | None, limit: int | None = None) -> str:
    """A value the portal will take: single line, only the characters NIC allows."""
    # Item descriptions are free text and routinely hold newlines and serial number
    # lists, and addresses hold brackets and colons. Dropping a character from the
    # file is better than the portal refusing the whole upload over it.
    text = DISALLOWED_TEXT_REGEX.sub("", " ".join((val or "").split()))
    text = " ".join(text.split())
    return text[:limit].strip() if limit else text


def _extract_pincode(address: str | None) -> str:
    """Extract a 6-digit PIN code from an address, preferring the last one written."""
    matches = _ADDRESS_PINCODE_REGEX.findall(address or "")
    return "".join(matches[-1]) if matches else ""


def _split_address(address: str) -> tuple[str, str]:
    """Split free-text address into the two lines NIC has room for."""
    lines = [" ".join(line.split()) for line in address.splitlines() if line.strip()]
    if not lines:
        return "", ""
    first, rest = lines[0], ", ".join(lines[1:])
    if len(first) > MAX_ADDRESS_LENGTH:
        cut = first.rfind(" ", 0, MAX_ADDRESS_LENGTH + 1)
        cut = cut if cut > 0 else MAX_ADDRESS_LENGTH
        rest = f"{first[cut:].strip()}, {rest}" if rest else first[cut:].strip()
        first = first[:cut].strip()
    return first, rest


def _item_hsn(item: InvoiceItem, product: Product | None) -> str:
    return _s(item.hsn_sac) or (_s(product.hsn_sac) if product else "")


def validate_invoice(
    invoice: Invoice,
    items: list[InvoiceItem],
    products_map: dict[int, Product],
) -> list[EwayBillValidationError]:
    """What is wrong with the invoice itself, which no form input can fix."""
    errors: list[EwayBillValidationError] = []

    doc_no = _s(invoice.invoice_number) or str(invoice.id)
    if not DOC_NO_REGEX.match(doc_no):
        errors.append(EwayBillValidationError(
            field="invoice_number",
            message=f"Invoice number '{doc_no}' can't be used: the portal allows at most 16 "
                    "characters, and only letters, numbers, / - and .",
        ))

    if len(items or []) > MAX_ITEMS:
        errors.append(EwayBillValidationError(
            field="invoice_items",
            message=f"This invoice has {len(items)} items. The portal allows at most {MAX_ITEMS} per E-Way Bill.",
        ))

    # HSN is mandatory on every item, and at least one has to be goods: the portal
    # refuses a bill with only SAC (service) codes.
    goods_found = False
    for inv_item in (items or []):
        product = products_map.get(inv_item.product_id)
        hsn = _item_hsn(inv_item, product)
        product_name = product.name if product else f"Product #{inv_item.product_id}"
        if not hsn:
            errors.append(EwayBillValidationError(
                field=f"item_{inv_item.id}_hsn",
                message=f"Item '{product_name}' is missing HSN/SAC code. Please add it in Products.",
            ))
        elif not HSN_SAC_REGEX.fullmatch(hsn):
            errors.append(EwayBillValidationError(
                field=f"item_{inv_item.id}_hsn",
                message=f"Item '{product_name}' has HSN/SAC code '{hsn}'. It must be 4, 6 or 8 digits.",
            ))
        goods_found = goods_found or (bool(hsn) and not hsn.startswith("99"))

    if items and not goods_found:
        errors.append(EwayBillValidationError(
            field="invoice_items",
            message="An E-Way Bill needs at least one item of goods. This invoice only has services (SAC codes).",
        ))

    return errors


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

    # ── Seller and buyer: what the invoice saved, so the bill matches the invoice
    # even if the master record changed later. Invoices older than the snapshot
    # columns have them blank, which is when the live record is used. A buyer's
    # GSTIN is the exception: a snapshot with a name and no GSTIN means the buyer
    # was unregistered when invoiced, and the bill must say so even if they have
    # registered since. A seller can't be unregistered on an e-way bill.
    seller_gstin = _s(invoice.company_gst) or _s(company.gst)
    seller_trade_name = _s(invoice.company_name) or _s(company.name)
    seller_address = _s(invoice.company_address) or _s(company.address)
    seller_address_1, seller_address_2 = _split_address(seller_address)
    seller_state_code = extract_state_code(seller_gstin)
    seller_place = STATE_CODES.get(seller_state_code, "")
    seller_pincode = _extract_pincode(seller_address)

    live_buyer_gst = _s(buyer.gst) if buyer else ""
    buyer_gstin = _s(invoice.ledger_gst) if _s(invoice.ledger_name) else live_buyer_gst
    buyer_trade_name = _s(invoice.ledger_name) or (_s(buyer.name) if buyer else "")
    buyer_address = _s(invoice.ledger_address) or (_s(buyer.address) if buyer else "")
    buyer_state_code = extract_state_code(buyer_gstin)
    buyer_state_code = buyer_state_code if buyer_state_code != "00" else ""

    # ── Delivery: goods going somewhere other than the billing address are a Bill
    # To - Ship To movement, where the address fields carry the Ship To party.
    shipping_address = _s(invoice.shipping_address)
    ships_elsewhere = bool(shipping_address) and " ".join(shipping_address.split()) != " ".join(buyer_address.split())
    delivery_address = shipping_address if ships_elsewhere else buyer_address
    buyer_address_1, buyer_address_2 = _split_address(delivery_address)
    buyer_pincode = _extract_pincode(delivery_address)
    # Only a billing address is known to be in the buyer's GST state.
    buyer_place = "" if ships_elsewhere else STATE_CODES.get(buyer_state_code, "")

    # ── Seller GSTIN (mandatory) ──
    if not seller_gstin:
        errors.append(EwayBillValidationError(
            field="seller_gstin",
            message="Company GSTIN is not set. Enter it here, and add it in Company Settings for future invoices.",
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
            message="Buyer has no GSTIN, so the bill will treat them as unregistered (URP).",
        ))
    elif not GSTIN_REGEX.match(buyer_gstin):
        errors.append(EwayBillValidationError(
            field="buyer_gstin",
            message="Buyer GSTIN format is invalid.",
        ))

    # ── Fields the portal requires that can only come from free-text addresses ──
    if not seller_pincode:
        missing.append(EwayBillValidationError(
            field="seller_pincode",
            message="No PIN code found in the company address. Enter the 6-digit PIN code.",
        ))
    if not buyer_pincode:
        where = "shipping address" if ships_elsewhere else "buyer address"
        missing.append(EwayBillValidationError(
            field="buyer_pincode",
            message=f"No PIN code found in the {where}. Enter the 6-digit PIN code.",
        ))
    if not buyer_state_code:
        missing.append(EwayBillValidationError(
            field="buyer_state_code",
            message="Buyer has no GSTIN to read a state from. Enter the 2-digit state code.",
        ))
    if ships_elsewhere:
        missing.append(EwayBillValidationError(
            field="ship_to_state_code",
            message="Filled from the invoice's shipping address. Check the delivery state, and change "
                    "the transaction type to Regular if the goods stay with the buyer in the same state.",
        ))

    item_errors = validate_invoice(invoice, items, products_map)

    # ── Threshold evaluation (guidance only, never blocks) ──
    interstate = float(invoice.igst_amount or 0) > 0
    local_threshold = float(company.eway_local_threshold or 0)
    interstate_threshold = float(company.eway_interstate_threshold or 0)
    threshold_value = interstate_threshold if interstate else local_threshold
    invoice_value = _money(invoice.total_amount)

    threshold_warning: str | None = None
    # Rule 138(1) applies to a consignment "exceeding" the limit.
    if invoice_value <= threshold_value:
        threshold_warning = (
            f"This invoice (₹{invoice_value:,.2f}) does not exceed the configured "
            f"{'interstate' if interstate else 'local'} E-Way Bill threshold "
            f"(₹{threshold_value:,.2f}). Generate only if required."
        )

    blocking_missing = {"seller_pincode", "buyer_pincode", "buyer_state_code"}
    valid = not errors and not item_errors and not any(m.field in blocking_missing for m in missing)

    form_data = EwayBillFormData(
        seller_gstin=seller_gstin,
        seller_trade_name=seller_trade_name,
        seller_address_1=seller_address_1,
        seller_address_2=seller_address_2,
        seller_place=seller_place,
        seller_state_code=seller_state_code if seller_state_code != "00" else "",
        seller_pincode=seller_pincode,
        dispatch_state_code=seller_state_code if seller_state_code != "00" else "",
        buyer_gstin=buyer_gstin,
        buyer_trade_name=buyer_trade_name,
        buyer_address_1=buyer_address_1,
        buyer_address_2=buyer_address_2,
        buyer_place=buyer_place,
        buyer_state_code=buyer_state_code,
        buyer_pincode=buyer_pincode,
        ship_to_state_code=buyer_state_code,
        transaction_type=TRANSACTION_BILL_TO_SHIP_TO if ships_elsewhere else TRANSACTION_REGULAR,
    )

    return EwayBillPreCheckResult(
        valid=valid,
        errors=errors,
        missing_fields=missing,
        form_data=form_data,
        item_validation=item_errors,
        threshold_warning=threshold_warning,
        eway_local_threshold=local_threshold,
        eway_interstate_threshold=interstate_threshold,
    )


def _valid_state_code(val: str) -> bool:
    return val in STATE_CODES or val in OTHER_COUNTRY_STATE_CODES


def _clean_vehicle_number(val: str | None) -> str:
    # NIC asks for it "without any spaces", and people write KA 12 KA 1234.
    return "".join(_s(val).split()).upper()


def _parse_doc_date(val: str | None) -> date | None:
    try:
        return date.fromisoformat(_s(val))
    except ValueError:
        return None


def validate_form_data(form: EwayBillFormData) -> list[EwayBillValidationError]:
    """Validate the complete form data before generating JSON."""
    errors: list[EwayBillValidationError] = []

    def add(field: str, message: str) -> None:
        errors.append(EwayBillValidationError(field=field, message=message))

    # Seller GSTIN — required and well-formed.
    seller_gstin = _s(form.seller_gstin).upper()
    if not seller_gstin:
        add("seller_gstin", "Seller GSTIN is required.")
    elif not GSTIN_REGEX.match(seller_gstin):
        add("seller_gstin", "Seller GSTIN format is invalid. It should look like 27ABCDE1234F1Z0.")

    # Buyer GSTIN — optional (empty or URP = unregistered), but if present must be valid.
    buyer_gstin = _s(form.buyer_gstin).upper()
    if buyer_gstin and buyer_gstin != UNREGISTERED_GSTIN and not GSTIN_REGEX.match(buyer_gstin):
        add("buyer_gstin", "Buyer GSTIN format is invalid. It should look like 27ABCDE1234F1Z0, or leave it blank for an unregistered buyer.")

    # State codes — both required (used for addressing and intra/inter-state nature).
    for field, label in [("seller_state_code", "Seller state code"), ("buyer_state_code", "Buyer state code")]:
        val = _s(getattr(form, field))
        if not val:
            add(field, f"{label} is required.")
        elif not _valid_state_code(val):
            add(field, f"{label} must be a valid 2-digit GST state code, such as 27.")
    for field, label in [("dispatch_state_code", "Dispatch state code"), ("ship_to_state_code", "Ship-to state code")]:
        val = _s(getattr(form, field))
        if val and not _valid_state_code(val):
            add(field, f"{label} must be a valid 2-digit GST state code, such as 27.")

    # PIN codes — the portal requires both, and blank must never become 0 in the file.
    for field, label in [("seller_pincode", "Seller PIN code"), ("buyer_pincode", "Buyer PIN code")]:
        val = _s(getattr(form, field))
        if not val:
            add(field, f"{label} is required.")
        elif not _PINCODE_REGEX.match(val):
            add(field, f"{label} must be 6 digits and can't start with 0.")

    # Text limits. Characters the portal refuses are dropped when the file is built.
    for field, label, limit in [
        ("seller_trade_name", "Seller trade name", MAX_NAME_LENGTH),
        ("seller_address_1", "Seller address line 1", MAX_ADDRESS_LENGTH),
        ("seller_address_2", "Seller address line 2", MAX_ADDRESS_LENGTH),
        ("seller_place", "Seller place", MAX_PLACE_LENGTH),
        ("buyer_trade_name", "Buyer trade name", MAX_NAME_LENGTH),
        ("buyer_address_1", "Buyer address line 1", MAX_ADDRESS_LENGTH),
        ("buyer_address_2", "Buyer address line 2", MAX_ADDRESS_LENGTH),
        ("buyer_place", "Buyer place", MAX_PLACE_LENGTH),
        ("transporter_name", "Transporter name", MAX_NAME_LENGTH),
    ]:
        if len(_s(getattr(form, field))) > limit:
            add(field, f"{label} can be at most {limit} characters.")

    # Supply details. The file is always a Tax Invoice for an outward supply, and
    # NIC only allows these sub-supply types on one.
    if form.supply_type != "O":
        add("supply_type", "Supply type must be Outward for a sales invoice.")
    if form.transaction_type not in TRANSACTION_TYPE_CODES:
        add("transaction_type", "Transaction type is required.")
    if form.sub_supply_type not in INVOICE_SUB_SUPPLY_CODES:
        allowed = ", ".join(INVOICE_SUB_SUPPLY_CODES.values())
        add("sub_supply_type", f"Sub-supply type must be one of {allowed} for a tax invoice.")

    # What each transaction type requires of the states, from NIC's preparation tool.
    seller_state = _s(form.seller_state_code)
    buyer_state = _s(form.buyer_state_code)
    dispatch_state = _s(form.dispatch_state_code) or seller_state
    ship_to_state = _s(form.ship_to_state_code) or buyer_state
    export = form.sub_supply_type == SUB_SUPPLY_EXPORT
    if not export and form.transaction_type in (TRANSACTION_REGULAR, TRANSACTION_BILL_FROM_DISPATCH_FROM) and buyer_state and ship_to_state != buyer_state:
        add("ship_to_state_code", "Ship-to state must match the buyer's state unless the transaction type is Bill To - Ship To or Combination.")
    if form.transaction_type in (TRANSACTION_REGULAR, TRANSACTION_BILL_TO_SHIP_TO) and seller_state and dispatch_state != seller_state:
        add("dispatch_state_code", "Dispatch state must match the seller's state unless the transaction type is Bill From - Dispatch From or Combination.")

    # NIC's rules for an export: an unregistered buyer in "Other Country".
    if export:
        if buyer_gstin and buyer_gstin != UNREGISTERED_GSTIN:
            add("buyer_gstin", "An export must have no buyer GSTIN (unregistered).")
        if buyer_state not in OTHER_COUNTRY_STATE_CODES:
            add("buyer_state_code", "An export must have buyer state code 99 (Other Country).")

    # Transport.
    transporter_id = _s(form.transporter_gstin).upper()
    if transporter_id and not TRANSPORTER_ID_REGEX.match(transporter_id):
        add("transporter_gstin", "Transporter GSTIN must be a 15-character GSTIN or TRANSIN.")

    vehicle_number = _clean_vehicle_number(form.vehicle_number)
    if vehicle_number and not VEHICLE_REGEX.match(vehicle_number):
        add("vehicle_number", "Vehicle number format is invalid. Use a format like KA12AB1234, with no spaces.")
    if form.vehicle_type not in VEHICLE_TYPE_CODES:
        add("vehicle_type", "Vehicle type must be Regular or Over Dimensional.")

    if form.transport_mode not in TRANSPORT_MODE_CODES:
        add("transport_mode", "Transport mode must be Road, Rail, Air or Ship.")
    elif form.transport_mode == ROAD_MODE:
        # A bill with no vehicle is a Part A slip, which NIC only allows with a transporter.
        if not vehicle_number and not transporter_id:
            add("vehicle_number", "Enter a vehicle number or a transporter GSTIN for transport by road.")
    else:
        # NIC's two documents disagree on whether Ship needs these. The newer calls
        # them optional and the API documentation calls them a must, and supplying
        # them satisfies both.
        doc_no = _s(form.transport_doc_no)
        if not doc_no:
            add("transport_doc_no", "Transport document number is required for transport by rail, air or ship.")
        elif len(doc_no) > MAX_TRANSPORT_DOC_NO_LENGTH or not DOC_NO_REGEX.match(doc_no):
            add("transport_doc_no", f"Transport document number can be at most {MAX_TRANSPORT_DOC_NO_LENGTH} characters: letters, numbers, / - and .")
        if not _s(form.transport_doc_date):
            add("transport_doc_date", "Transport document date is required for transport by rail, air or ship.")
        if form.transport_mode in (RAIL_MODE, AIR_MODE) and form.vehicle_type == VEHICLE_TYPE_ODC:
            add("vehicle_type", "Vehicle type must be Regular for transport by rail or air.")
        if form.transport_mode == SHIP_MODE and form.vehicle_type == VEHICLE_TYPE_ODC and not vehicle_number:
            add("vehicle_number", "Vehicle number is required for Over Dimensional cargo by ship.")
    if _s(form.transport_doc_date) and not _parse_doc_date(form.transport_doc_date):
        add("transport_doc_date", "Transport document date is not a valid date.")

    if form.distance_km is not None:
        if form.distance_km < 0:
            add("distance_km", "Distance cannot be negative.")
        elif form.distance_km > MAX_DISTANCE_KM:
            add("distance_km", f"Distance can be at most {MAX_DISTANCE_KM} km.")
        elif _s(form.seller_pincode) and _s(form.seller_pincode) == _s(form.buyer_pincode) and form.distance_km > MAX_SAME_PIN_DISTANCE_KM:
            add("distance_km", f"Distance can be at most {MAX_SAME_PIN_DISTANCE_KM} km when both PIN codes are the same.")

    return errors


def validate_form_against_invoice(form: EwayBillFormData, invoice: Invoice) -> list[EwayBillValidationError]:
    """What the form can't say on its own: whether it agrees with the invoice it bills."""
    errors: list[EwayBillValidationError] = []

    # The portal wants CGST+SGST within a state and IGST across states, and the
    # tax is whatever the invoice computed, so the states have to agree with it.
    seller_state = _s(form.seller_state_code)
    buyer_state = _s(form.buyer_state_code)
    if seller_state and buyer_state:
        if float(invoice.igst_amount or 0) > 0 and seller_state == buyer_state:
            errors.append(EwayBillValidationError(
                field="buyer_state_code",
                message="This invoice charges IGST, but the seller and buyer state codes are the same. "
                        "IGST needs two different states.",
            ))
        if float(invoice.cgst_amount or 0) > 0 and seller_state != buyer_state:
            errors.append(EwayBillValidationError(
                field="buyer_state_code",
                message="This invoice charges CGST and SGST, but the seller and buyer state codes differ. "
                        "CGST and SGST need the same state.",
            ))

    doc_date = _parse_doc_date(form.transport_doc_date)
    invoice_date = invoice.invoice_date.date() if hasattr(invoice.invoice_date, "date") else invoice.invoice_date
    if doc_date and invoice_date and doc_date < invoice_date:
        errors.append(EwayBillValidationError(
            field="transport_doc_date",
            message="Transport document date can't be before the invoice date.",
        ))

    return errors


def _qty_unit(product: Product | None) -> str:
    """The unit code for an item: a unit that already is a NIC code, or the shared mapping."""
    unit = _s(product.unit) if product else ""
    return unit.upper() if unit.upper() in NIC_UQC_CODES else uqc_for_unit(unit)


def generate_eway_bill_json(
    invoice: Invoice,
    items: list[InvoiceItem],
    products_map: dict[int, Product],
    form: EwayBillFormData,
) -> dict:
    """Build the NIC bulk upload JSON (returns a dict).

    The key names and types follow what NIC's preparation tool writes. Callers
    validate the form first: a blank PIN code here would be a file the portal refuses.
    """
    # The tax nature is whatever the invoice actually computed at creation time,
    # not a re-derivation from form state codes — this keeps item rates and the
    # bill-level CGST/SGST/IGST values internally consistent.
    interstate = float(invoice.igst_amount or 0) > 0

    # ── Item list ──
    bill_items = []
    main_hsn = ""
    main_hsn_value = -1.0
    for number, inv_item in enumerate(items or [], start=1):
        product = products_map.get(inv_item.product_id)
        hsn = _item_hsn(inv_item, product)
        gst_rate = float(inv_item.gst_rate or 0)
        half_rate = round(gst_rate / 2, 3)
        taxable = _money(inv_item.taxable_amount)

        # mainHsnCode names the bill's goods, so a service line can't be it.
        if not hsn.startswith("99") and taxable > main_hsn_value:
            main_hsn, main_hsn_value = hsn, taxable

        product_name = product.name if product else ""
        description = _s(inv_item.description) or (_s(product.description) if product else "") or product_name
        bill_items.append({
            "itemNo": number,
            "productName": _nic_text(product_name, MAX_DESC_LENGTH),
            "productDesc": _nic_text(description, MAX_DESC_LENGTH),
            # A string in NIC's schema, which is what keeps a leading zero (0401).
            "hsnCode": hsn,
            "quantity": float(inv_item.quantity or 0),
            "qtyUnit": _qty_unit(product),
            "taxableAmount": taxable,
            "sgstRate": 0 if interstate else half_rate,
            "cgstRate": 0 if interstate else half_rate,
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

    transport_doc_date = _parse_doc_date(form.transport_doc_date)

    # ── Recipient GSTIN: unregistered buyers go in as "URP" ──
    buyer_gstin = _s(form.buyer_gstin).upper() or UNREGISTERED_GSTIN
    seller_gstin = _s(form.seller_gstin).upper()

    seller_state = int(form.seller_state_code)
    buyer_state = int(form.buyer_state_code)
    dispatch_state = int(_s(form.dispatch_state_code) or form.seller_state_code)
    ship_to_state = int(_s(form.ship_to_state_code) or form.buyer_state_code)

    # ── Money totals (OthValue balances rounding so totInvValue reconciles) ──
    taxable = _money(invoice.taxable_amount)
    cgst = _money(invoice.cgst_amount)
    sgst = _money(invoice.sgst_amount)
    igst = _money(invoice.igst_amount)
    tot_inv = _money(invoice.total_amount)
    other_value = round(tot_inv - (taxable + cgst + sgst + igst), 2)

    bill_entry = {
        "userGstin": seller_gstin,
        "supplyType": "O",
        "subSupplyType": int(form.sub_supply_type),
        "subSupplyDesc": "",
        "docType": "INV",
        "docNo": _s(invoice.invoice_number) or str(invoice.id),
        "docDate": doc_date,
        "transType": int(form.transaction_type),
        # Bill From: GSTIN, name, state. Dispatch From: address, place, PIN, actual state.
        "fromGstin": seller_gstin,
        "fromTrdName": _nic_text(form.seller_trade_name, MAX_NAME_LENGTH),
        "fromAddr1": _nic_text(form.seller_address_1, MAX_ADDRESS_LENGTH),
        "fromAddr2": _nic_text(form.seller_address_2, MAX_ADDRESS_LENGTH),
        "fromPlace": _nic_text(form.seller_place, MAX_PLACE_LENGTH),
        "fromPincode": int(form.seller_pincode),
        "fromStateCode": seller_state,
        "actualFromStateCode": dispatch_state,
        # Bill To: GSTIN, name, state. Ship To: address, place, PIN, actual state.
        "toGstin": buyer_gstin,
        "toTrdName": _nic_text(form.buyer_trade_name, MAX_NAME_LENGTH),
        "toAddr1": _nic_text(form.buyer_address_1, MAX_ADDRESS_LENGTH),
        "toAddr2": _nic_text(form.buyer_address_2, MAX_ADDRESS_LENGTH),
        "toPlace": _nic_text(form.buyer_place, MAX_PLACE_LENGTH),
        "toPincode": int(form.buyer_pincode),
        "toStateCode": buyer_state,
        "actualToStateCode": ship_to_state,
        "totalValue": taxable,
        "cgstValue": cgst,
        "sgstValue": sgst,
        "igstValue": igst,
        "cessValue": 0,
        "TotNonAdvolVal": 0,
        "OthValue": other_value,
        "totInvValue": tot_inv,
        "transMode": int(form.transport_mode),
        # Blank is sent as 0, which NIC documents as "work it out from the two PIN
        # codes". Where it has no distance for them, the bill is still generated
        # with an alert and the distance is the generator's responsibility.
        "transDistance": form.distance_km or 0,
        "transporterName": _nic_text(form.transporter_name, MAX_NAME_LENGTH),
        "transporterId": _s(form.transporter_gstin).upper(),
        "transDocNo": _s(form.transport_doc_no),
        "transDocDate": transport_doc_date.strftime("%d/%m/%Y") if transport_doc_date else "",
        "vehicleNo": _clean_vehicle_number(form.vehicle_number),
        "vehicleType": form.vehicle_type,
        "mainHsnCode": main_hsn,
        "itemList": bill_items,
    }

    output = EwayBillOutput(version=NIC_JSON_VERSION, bill_lists=[bill_entry])
    return output.model_dump(by_alias=True)


def clear_default_transporter(db: Session, company_id: int, keep_id: int | None = None) -> None:
    """Unset the company's default transporter, so setting a new one leaves exactly one."""
    query = db.query(EwayBillTransporter).filter(
        EwayBillTransporter.company_id == company_id,
        EwayBillTransporter.is_default.is_(True),
    )
    if keep_id is not None:
        query = query.filter(EwayBillTransporter.id != keep_id)
    query.update({"is_default": False}, synchronize_session="fetch")


def save_default_transporter(db: Session, company_id: int, form: EwayBillFormData) -> EwayBillTransporter:
    """Save the form's transporter as the company's default. The caller commits."""
    name = _s(form.transporter_name)
    transporter = (
        db.query(EwayBillTransporter)
        .filter(
            EwayBillTransporter.company_id == company_id,
            EwayBillTransporter.transporter_name == name,
        )
        .first()
    )
    if transporter is None:
        transporter = EwayBillTransporter(company_id=company_id, transporter_name=name)
        db.add(transporter)
        db.flush()

    clear_default_transporter(db, company_id, keep_id=transporter.id)
    transporter.transporter_gstin = _s(form.transporter_gstin).upper()
    transporter.transport_mode = form.transport_mode or ROAD_MODE
    transporter.vehicle_type = form.vehicle_type or "R"
    transporter.is_default = True
    return transporter


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
