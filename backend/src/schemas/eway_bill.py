from pydantic import BaseModel, Field, field_validator

from src.core.eway_bill_codes import (
    NIC_JSON_VERSION,
    TRANSPORT_MODE_CODES,
    TRANSPORTER_ID_REGEX,
    VEHICLE_TYPE_CODES,
)


def _check_transporter_id(value: str | None) -> str | None:
    value = (value or "").strip().upper()
    if value and not TRANSPORTER_ID_REGEX.match(value):
        raise ValueError("Transporter GSTIN must be a 15-character GSTIN or TRANSIN.")
    return value or None


def _check_transport_mode(value: str | None) -> str | None:
    if value is not None and value not in TRANSPORT_MODE_CODES:
        raise ValueError("Transport mode must be Road, Rail, Air or Ship.")
    return value


def _check_vehicle_type(value: str | None) -> str | None:
    if value is not None and value not in VEHICLE_TYPE_CODES:
        raise ValueError("Vehicle type must be Regular (R) or Over Dimensional (O).")
    return value


class TransporterProfileCreate(BaseModel):
    transporter_name: str = Field(min_length=1, max_length=100)
    transporter_gstin: str | None = None
    transport_mode: str = "1"
    vehicle_type: str = "R"
    is_default: bool = False

    check_transporter_gstin = field_validator("transporter_gstin")(_check_transporter_id)
    check_transport_mode = field_validator("transport_mode")(_check_transport_mode)
    check_vehicle_type = field_validator("vehicle_type")(_check_vehicle_type)


class TransporterProfileUpdate(BaseModel):
    transporter_name: str | None = Field(default=None, min_length=1, max_length=100)
    transporter_gstin: str | None = None
    transport_mode: str | None = None
    vehicle_type: str | None = None
    is_default: bool | None = None

    check_transporter_gstin = field_validator("transporter_gstin")(_check_transporter_id)
    check_transport_mode = field_validator("transport_mode")(_check_transport_mode)
    check_vehicle_type = field_validator("vehicle_type")(_check_vehicle_type)


class TransporterProfileOut(BaseModel):
    id: int
    company_id: int
    transporter_name: str
    transporter_gstin: str | None = None
    transport_mode: str
    vehicle_type: str
    is_default: bool

    class Config:
        from_attributes = True


class EwayBillFormData(BaseModel):
    """Fields the user needs to fill in when generating an E-Way Bill."""

    # Seller details (pre-filled from the invoice). The address, place and PIN are
    # where the goods leave from, so they are the Dispatch From party on type 3 or 4.
    seller_gstin: str = ""
    seller_trade_name: str = ""
    seller_address_1: str = ""
    seller_address_2: str = ""
    seller_place: str = ""
    seller_state_code: str = ""
    seller_pincode: str = ""
    # actualFromStateCode. Blank means the same as seller_state_code.
    dispatch_state_code: str = ""

    # Buyer details (pre-filled from the invoice). GSTIN, name and state are the
    # Bill To party. The address, place and PIN are where the goods are delivered,
    # so they are the Ship To party when the invoice has a shipping address.
    buyer_gstin: str = ""
    buyer_trade_name: str = ""
    buyer_address_1: str = ""
    buyer_address_2: str = ""
    buyer_place: str = ""
    buyer_state_code: str = ""
    buyer_pincode: str = ""
    # actualToStateCode. Blank means the same as buyer_state_code.
    ship_to_state_code: str = ""

    # Supply details
    supply_type: str = "O"  # O = Outward. These routes only serve sales invoices.
    transaction_type: str = "1"  # 1=Regular, 2=Bill To-Ship To, 3=Bill From-Dispatch From, 4=Combination
    sub_supply_type: str = "1"  # NIC numeric code (1=Supply, 3=Export, 9=SKD/CKD/Lots)

    # Transport details
    transport_mode: str = "1"  # 1=Road, 2=Rail, 3=Air, 4=Ship
    vehicle_number: str = ""
    distance_km: int | None = None
    transporter_gstin: str = ""
    transporter_name: str = ""
    vehicle_type: str = "R"
    transport_doc_no: str = ""  # RR, airway bill or bill of lading number
    transport_doc_date: str = ""  # YYYY-MM-DD, as a date input sends it

    # Transporter save option
    save_transporter: bool = False


class EwayBillOutput(BaseModel):
    """The generated E-Way Bill JSON response."""
    version: str = NIC_JSON_VERSION
    bill_lists: list[dict] = Field(default_factory=list, alias="billLists")

    class Config:
        populate_by_name = True


class EwayBillValidationError(BaseModel):
    field: str
    message: str


class EwayBillPreCheckResult(BaseModel):
    """Result of checking what data is available vs missing."""
    valid: bool
    # errors and missing_fields can be fixed in the form; item_validation cannot,
    # because the invoice itself (or its products) has to change.
    errors: list[EwayBillValidationError] = []
    missing_fields: list[EwayBillValidationError]
    form_data: EwayBillFormData
    item_validation: list[EwayBillValidationError]
    threshold_warning: str | None = None
    eway_local_threshold: float = 50000
    eway_interstate_threshold: float = 50000
