from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator


class TransporterProfileCreate(BaseModel):
    transporter_name: str
    transporter_gstin: str | None = None
    transport_mode: str = "1"
    vehicle_type: str = "R"
    is_default: bool = False


class TransporterProfileUpdate(BaseModel):
    transporter_name: str | None = None
    transporter_gstin: str | None = None
    transport_mode: str | None = None
    vehicle_type: str | None = None
    is_default: bool | None = None


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

    # Seller details (pre-filled from company)
    seller_gstin: str = ""
    seller_trade_name: str = ""
    seller_address_1: str = ""
    seller_address_2: str = ""
    seller_place: str = ""
    seller_state_code: str = ""
    seller_pincode: str = ""

    # Buyer details (pre-filled from invoice ledger)
    buyer_gstin: str = ""
    buyer_trade_name: str = ""
    buyer_address_1: str = ""
    buyer_address_2: str = ""
    buyer_place: str = ""
    buyer_state_code: str = ""
    buyer_pincode: str = ""

    # Supply details
    supply_type: str = "O"  # O = Outward
    sub_supply_type: str = "Supply"
    sub_supply_desc: str = ""

    # Transport details
    transport_mode: str = "1"  # 1=Road
    vehicle_number: str = ""
    distance_km: int | None = None
    transporter_gstin: str = ""
    transporter_name: str = ""
    vehicle_type: str = "R"

    # Transporter save option
    save_transporter: bool = False


class EwayBillItem(BaseModel):
    product_name: str
    product_desc: str = ""
    hsn_code: str
    quantity: float
    qty_unit: str = "NOS"
    taxable_amount: float
    cgst_rate: float = 0
    sgst_rate: float = 0
    igst_rate: float = 0
    cess_rate: float = 0


class EwayBillOutput(BaseModel):
    """The generated E-Way Bill JSON response."""
    version: str = "1.0.1118"
    bill_lists: list[dict] = Field(default_factory=list, alias="billLists")

    class Config:
        populate_by_name = True


class EwayBillValidationError(BaseModel):
    field: str
    message: str


class EwayBillPreCheckResult(BaseModel):
    """Result of checking what data is available vs missing."""
    valid: bool
    missing_fields: list[EwayBillValidationError]
    form_data: EwayBillFormData
    item_validation: list[EwayBillValidationError]


class EwayBillTransporterSelectOut(BaseModel):
    transporters: list[TransporterProfileOut]
    default: TransporterProfileOut | None = None
