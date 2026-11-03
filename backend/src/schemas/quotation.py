from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from src.schemas.invoice import InvoiceCreate, _validate_discount_value
from src.schemas.ledger_address import ShippingAddressInline

DocumentType = Literal["quotation", "proforma"]
StoredStatus = Literal["open", "accepted", "declined", "converted", "cancelled"]
StatusFilter = Literal["open", "accepted", "declined", "converted", "cancelled", "expired"]
# Converted and cancelled are reached through their own actions, not this route.
SettableStatus = Literal["open", "accepted", "declined"]

# Exclusive limits from the columns: money is NUMERIC(10, 2), quantity NUMERIC(12, 3).
# Computed totals have to fit the same money columns; the service checks those.
MONEY_LIMIT = 100_000_000
QUANTITY_LIMIT = 1_000_000_000
# Nobody means a date outside this, and a far one overflows date arithmetic.
EARLIEST_DOCUMENT_DATE = date(2000, 1, 1)
LATEST_DOCUMENT_DATE = date(2099, 12, 31)


def _check_places(value: float | None, places: int) -> float | None:
    """Refuse a figure more precise than its column.

    Totals are worked out from the value as sent and the value is stored rounded, so a
    price of 33.333 would be quoted at one total and convert at another.
    """
    if value is not None and -Decimal(str(value)).normalize().as_tuple().exponent > places:
        raise ValueError(f"must have at most {places} decimal places")
    return value


class QuotationItemCreate(BaseModel):
    """A line that is priced but not fulfilled. Deliberately has no serial_numbers
    and no gst_rate: serials are picked at conversion, and tax follows the product."""

    product_id: int
    quantity: float = Field(lt=QUANTITY_LIMIT, allow_inf_nan=False)
    unit_price: float | None = Field(default=None, ge=0, lt=MONEY_LIMIT, allow_inf_nan=False)
    description: str | None = None
    discount_type: Literal["percentage", "net"] | None = None
    discount_value: float | None = Field(default=None, lt=MONEY_LIMIT, allow_inf_nan=False)

    @field_validator("discount_value", mode="after")
    @classmethod
    def _check_discount_value(cls, value: float | None, info: ValidationInfo) -> float | None:
        return _check_places(_validate_discount_value(value, info), 2)

    @field_validator("unit_price", mode="after")
    @classmethod
    def _check_unit_price(cls, value: float | None) -> float | None:
        return _check_places(value, 2)

    @field_validator("quantity", mode="after")
    @classmethod
    def _check_quantity(cls, value: float) -> float:
        return _check_places(value, 3)


class QuotationFields(BaseModel):
    ledger_id: int
    quotation_date: date | None = Field(default=None, ge=EARLIEST_DOCUMENT_DATE, le=LATEST_DOCUMENT_DATE)
    # Left out: 30 days from the quotation date on create, unchanged on edit.
    # Sent as null: never expires.
    valid_until: date | None = Field(default=None, ge=EARLIEST_DOCUMENT_DATE, le=LATEST_DOCUMENT_DATE)
    reference_notes: str | None = None
    tax_inclusive: bool = False
    apply_round_off: bool = False
    discount_type: Literal["percentage", "net"] | None = None
    discount_value: float | None = Field(default=None, lt=MONEY_LIMIT, allow_inf_nan=False)
    shipping_address_same_as_billing: bool = True
    shipping_address_id: int | None = None
    new_shipping_address: ShippingAddressInline | None = None
    items: List[QuotationItemCreate]

    @field_validator("discount_value", mode="after")
    @classmethod
    def _check_discount_value(cls, value: float | None, info: ValidationInfo) -> float | None:
        return _check_places(_validate_discount_value(value, info), 2)

    @model_validator(mode="after")
    def _check_validity(self):
        if self.valid_until and self.quotation_date and self.valid_until < self.quotation_date:
            raise ValueError("valid_until must be on or after quotation_date")
        return self


class QuotationCreate(QuotationFields):
    document_type: DocumentType = "quotation"


class QuotationUpdate(QuotationFields):
    # A proforma cannot become a quotation: the type decides the number series.
    # Forbidding extras makes sending document_type an error rather than a no-op.
    model_config = ConfigDict(extra="forbid")


class QuotationStatusUpdate(BaseModel):
    status: SettableStatus
    note: str | None = None


class QuotationItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str | None = None
    hsn_sac: str | None = None
    quantity: float
    unit_price: float
    gst_rate: float
    taxable_amount: float
    tax_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    line_total: float
    description: str | None = None
    discount_type: str | None = None
    discount_value: float | None = None


class LinkedInvoiceOut(BaseModel):
    """An invoice created from this quotation. Cancelled ones stay as history."""

    id: int
    invoice_number: str | None = None
    status: str


class QuotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_type: str
    quotation_number: str
    # What is stored: open, accepted, declined, converted or cancelled.
    status: str
    is_expired: bool = False
    # What to show: the stored status, or "expired" once the validity date has passed.
    display_status: str = "open"
    quotation_date: date
    valid_until: date | None = None
    financial_year_id: int | None = None
    ledger_id: int
    ledger_name: str | None = None
    ledger_address: str | None = None
    ledger_gst: str | None = None
    ledger_phone: str | None = None
    company_name: str | None = None
    company_gst: str | None = None
    company_currency_code: str | None = None
    shipping_address: str | None = None
    shipping_address_label: str | None = None
    shipping_address_id: int | None = None
    reference_notes: str | None = None
    tax_inclusive: bool = False
    apply_round_off: bool = False
    round_off_amount: float = 0
    discount_type: str | None = None
    discount_value: float | None = None
    taxable_amount: float
    total_tax_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    total_amount: float
    status_note: str | None = None
    accepted_at: datetime | None = None
    declined_at: datetime | None = None
    converted_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    items: list[QuotationItemOut] = Field(default_factory=list)
    # The one live invoice, if any, then every invoice ever created from this.
    converted_invoice_id: int | None = None
    converted_invoice_number: str | None = None
    invoices: list[LinkedInvoiceOut] = Field(default_factory=list)


class PaginatedQuotationOut(BaseModel):
    items: list[QuotationOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    # Per display status, across the filters other than status itself.
    status_counts: dict[str, int] = Field(default_factory=dict)


class ConversionWarning(BaseModel):
    code: str
    message: str


class QuotationConvert(InvoiceCreate):
    """What /convert takes: the invoice, and which version of the quotation it came from.

    The draft fills in the version, so posting a draft back is checked for staleness.
    Left out, nothing is checked: that caller wrote the invoice itself, whatever the
    quotation says by now, and it still has to be a quotation that can convert.
    """

    quotation_updated_at: datetime | None = None


class QuotationConversionDraft(BaseModel):
    quotation_id: int
    quotation_number: str
    document_type: str
    # Ready to review in the composer, then post back to /convert. Leaves gst_rate
    # and hsn_sac unset, so both come from the product as it stands today.
    invoice: QuotationConvert
    warnings: list[ConversionWarning] = Field(default_factory=list)
