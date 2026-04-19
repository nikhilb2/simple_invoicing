from datetime import date, datetime
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from src.schemas.ledger import LedgerOut


class InvoiceItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: float | None = None
    description: str | None = None


class InvoiceCreate(BaseModel):
    ledger_id: int
    voucher_type: Literal["sales", "purchase"] = "sales"
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    supplier_invoice_number: str | None = None
    tax_inclusive: bool = False
    apply_round_off: bool = False
    items: List[InvoiceItemCreate]


class InvoiceItemOut(BaseModel):
    id: int
    product_id: int
    hsn_sac: str | None = None
    quantity: int
    unit_price: float
    gst_rate: float
    taxable_amount: float
    tax_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    line_total: float
    description: str | None = None

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
    voucher_type: str
    supplier_invoice_number: str | None = None
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
    tax_inclusive: bool = False
    apply_round_off: bool = False
    round_off_amount: float = 0
    financial_year_id: Optional[int] = None
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
