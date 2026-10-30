from datetime import date, datetime
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from typing import List, Literal, Optional
from src.schemas.ledger import LedgerOut
from src.schemas.ledger_address import ShippingAddressInline
from src.core.validation import normalize_hsn_sac


def _validate_discount_value(
    value: float | None, info: ValidationInfo
) -> float | None:
    """Reject negative discounts, and percentage discounts over 100.

    The sibling ``discount_type`` field is declared before ``discount_value``
    in both models below, so it is already present in ``info.data``.
    A net discount has no percentage cap: the processor clamps it to the
    line or invoice total, so a large flat discount stays valid.
    """
    if value is None:
        return value
    if value < 0:
        raise ValueError("discount_value must be greater than or equal to 0")
    if info.data.get("discount_type") == "percentage" and value > 100:
        raise ValueError(
            "discount_value must be less than or equal to 100 "
            "when discount_type is percentage"
        )
    return value


class InvoiceItemCreate(BaseModel):
    product_id: int
    quantity: float
    unit_price: float | None = Field(default=None, ge=0)
    description: str | None = None
    discount_type: Literal["percentage", "net"] | None = None
    discount_value: float | None = None

    @field_validator("discount_value", mode="after")
    @classmethod
    def _check_discount_value(
        cls, value: float | None, info: ValidationInfo
    ) -> float | None:
        return _validate_discount_value(value, info)
    # Per-line overrides of the product master. Marketplace purchases must book the
    # SELLER's rate and HSN — if the buyer's local product carries a different rate,
    # the two legally-linked invoices would disagree on tax. None = use the product.
    gst_rate: float | None = Field(default=None, ge=0, le=100)
    hsn_sac: str | None = None

    @field_validator("hsn_sac")
    @classmethod
    def validate_hsn_sac(cls, value: str | None) -> str | None:
        return normalize_hsn_sac(value)
    # One code per unit on a serial-tracked product; the count must equal
    # quantity. None / [] on any other product.
    serial_numbers: list[str] | None = None


class InvoiceCreate(BaseModel):
    ledger_id: int
    voucher_type: Literal["sales", "purchase"] = "sales"
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    supplier_invoice_number: str | None = None
    reference_notes: str | None = None
    tax_inclusive: bool = False
    apply_round_off: bool = False
    discount_type: Literal["percentage", "net"] | None = None
    discount_value: float | None = None
    shipping_address_same_as_billing: bool = True
    shipping_address_id: int | None = None
    new_shipping_address: ShippingAddressInline | None = None
    items: List[InvoiceItemCreate]

    @field_validator("discount_value", mode="after")
    @classmethod
    def _check_discount_value(
        cls, value: float | None, info: ValidationInfo
    ) -> float | None:
        return _validate_discount_value(value, info)


class InvoiceItemOut(BaseModel):
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
    serial_numbers: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class InvoiceOut(BaseModel):
    id: int
    invoice_number: str | None = None
    ledger_id: int | None = None
    ledger_name: str | None = None
    ledger_address: str | None = None
    ledger_gst: str | None = None
    ledger_phone: str | None = None
    company_name: str | None = None
    company_address: str | None = None
    company_gst: str | None = None
    company_phone: str | None = None
    company_email: str | None = None
    company_website: str | None = None
    company_currency_code: str | None = None
    company_bank_name: str | None = None
    company_branch_name: str | None = None
    company_account_name: str | None = None
    company_account_number: str | None = None
    company_ifsc_code: str | None = None
    company_logo_data: str | None = None
    company_logo_mime_type: str | None = None
    company_additional_info: str | None = None
    company_terms_text: str | None = None
    voucher_type: str
    supplier_invoice_number: str | None = None
    reference_notes: str | None = None
    status: str = "active"
    credit_status: str = "not_credited"
    ledger: LedgerOut | None = None
    taxable_amount: float
    total_tax_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    total_amount: float
    invoice_date: datetime
    due_date: datetime | None = None
    paid_amount: float = 0
    remaining_amount: float = 0
    outstanding_amount: float = 0
    payment_status: str = "unpaid"
    due_in_days: int | None = None
    # Dues page only: what we owe this ledger on open purchase invoices, and
    # its open receivable net of that. Display only; allocation is unaffected.
    ledger_payable_amount: float = 0
    ledger_net_receivable: float | None = None
    tax_inclusive: bool = False
    apply_round_off: bool = False
    round_off_amount: float = 0
    discount_type: str | None = None
    discount_value: float | None = None
    financial_year_id: Optional[int] = None
    shipping_address: str | None = None
    shipping_address_label: str | None = None
    warnings: List[str] = Field(default_factory=list)
    created_at: datetime
    items: list[InvoiceItemOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class PaginatedInvoiceOut(BaseModel):
    class SummaryMeta(BaseModel):
        total_listed: float
        credit_total: float
        debit_total: float
        cancelled_total: float
        active_total: float
        others_total: float
        visible_page_total: float
        visible_page_count: int
        filtered_count: int
        include_cancelled: bool
        financial_year_id: int | None = None

    items: list[InvoiceOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    summary: SummaryMeta


class DuesAgeingBucketOut(BaseModel):
    key: str
    label: str
    invoice_count: int
    total_remaining: float


class DuesAgeingOut(BaseModel):
    as_of_date: date
    buckets: list[DuesAgeingBucketOut]
    total_invoice_count: int
    total_remaining: float


class OutstandingInvoiceOut(BaseModel):
    id: int
    invoice_number: str | None = None
    invoice_date: datetime
    due_date: datetime | None = None
    total_amount: float
    paid_amount: float = 0
    remaining_amount: float = 0
    outstanding_amount: float = 0
    payment_status: str = "unpaid"
    due_in_days: int | None = None
    suggested_allocation_amount: float | None = None

    class Config:
        from_attributes = True
