from datetime import date, datetime
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from src.schemas.ledger import LedgerOut


class InvoiceItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: float | None = None


class InvoiceCreate(BaseModel):
    ledger_id: int
    voucher_type: Literal["sales", "purchase"] = "sales"
    invoice_date: Optional[date] = None
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
    line_total: float

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
    ledger: LedgerOut | None = None
    taxable_amount: float
    total_tax_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    total_amount: float
    invoice_date: datetime
    created_at: datetime
    items: list[InvoiceItemOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class PaginatedInvoiceOut(BaseModel):
    items: list[InvoiceOut]
    total: int
    page: int
    page_size: int
    total_pages: int
