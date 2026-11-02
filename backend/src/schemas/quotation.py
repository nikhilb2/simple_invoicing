from datetime import date, datetime
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from src.schemas.invoice import InvoiceCreate, _validate_discount_value
from src.schemas.ledger_address import ShippingAddressInline

DocumentType = Literal["quotation", "proforma"]
StoredStatus = Literal["open", "accepted", "declined", "converted", "cancelled"]
StatusFilter = Literal["open", "accepted", "declined", "converted", "cancelled", "expired"]
# Converted and cancelled are reached through their own actions, not this route.
SettableStatus = Literal["open", "accepted", "declined"]


class QuotationItemCreate(BaseModel):
    """A line that is priced but not fulfilled. Deliberately has no serial_numbers
    and no gst_rate: serials are picked at conversion, and tax follows the product."""

    product_id: int
    quantity: float = Field(allow_inf_nan=False)
    unit_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    description: str | None = None
    discount_type: Literal["percentage", "net"] | None = None
    discount_value: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("discount_value", mode="after")
    @classmethod
    def _check_discount_value(cls, value: float | None, info: ValidationInfo) -> float | None:
        return _validate_discount_value(value, info)


class QuotationFields(BaseModel):
    ledger_id: int
    quotation_date: date | None = None
    # Left out: 30 days from the quotation date on create, unchanged on edit.
    # Sent as null: never expires.
    valid_until: date | None = None
    reference_notes: str | None = None
    tax_inclusive: bool = False
    apply_round_off: bool = False
    discount_type: Literal["percentage", "net"] | None = None
    discount_value: float | None = Field(default=None, allow_inf_nan=False)
    shipping_address_same_as_billing: bool = True
    shipping_address_id: int | None = None
    new_shipping_address: ShippingAddressInline | None = None
    items: List[QuotationItemCreate]

    @field_validator("discount_value", mode="after")
    @classmethod
    def _check_discount_value(cls, value: float | None, info: ValidationInfo) -> float | None:
        return _validate_discount_value(value, info)

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


class QuotationConversionDraft(BaseModel):
    quotation_id: int
    quotation_number: str
    document_type: str
    # Ready to review in the composer, then post back to /convert. Leaves gst_rate
    # and hsn_sac unset, so both come from the product as it stands today.
    invoice: InvoiceCreate
    warnings: list[ConversionWarning] = Field(default_factory=list)
