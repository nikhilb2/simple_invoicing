from datetime import date, datetime
from pydantic import BaseModel, field_validator

from src.core.validation import normalize_gstin


class LedgerCreate(BaseModel):
    name: str
    address: str
    gst: str | None = None
    opening_balance: float | None = None
    phone_number: str
    email: str | None = None
    website: str | None = None
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None

    @field_validator("gst")
    @classmethod
    def validate_gst(cls, value: str | None) -> str | None:
        return normalize_gstin(value)


class LedgerOut(BaseModel):
    id: int
    name: str
    address: str
    gst: str = ""
    opening_balance: float | None = None
    phone_number: str
    email: str | None = None
    website: str | None = None
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None

    @field_validator("gst", mode="before")
    @classmethod
    def normalize_gst_output(cls, value: str | None) -> str:
        normalized = normalize_gstin(value)
        return normalized or ""

    class Config:
        from_attributes = True


class PaginatedLedgerOut(BaseModel):
    items: list[LedgerOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class LedgerStatementEntry(BaseModel):
    entry_id: int
    entry_type: str  # "invoice" or "payment"
    date: datetime
    voucher_type: str
    reference_number: str | None = None  # Invoice number, payment number, or credit note number
    particulars: str
    debit: float
    credit: float
    account_display_name: str | None = None
    account_type: str | None = None


class LedgerStatementOut(BaseModel):
    ledger: LedgerOut
    from_date: date
    to_date: date
    opening_balance: float
    period_debit: float
    period_credit: float
    closing_balance: float
    entries: list[LedgerStatementEntry]
    fy_label: str | None = None
    financial_year_id: int | None = None


class DayBookEntry(BaseModel):
    entry_id: int
    entry_type: str  # "invoice" or "payment"
    date: datetime
    voucher_type: str
    reference_number: str | None = None  # Invoice number, payment number, or credit note number
    ledger_name: str
    particulars: str
    debit: float
    credit: float
    account_display_name: str | None = None
    account_type: str | None = None


class DayBookOut(BaseModel):
    from_date: date
    to_date: date
    total_debit: float
    total_credit: float
    entries: list[DayBookEntry]
    fy_label: str | None = None
    financial_year_id: int | None = None


class TaxLedgerEntry(BaseModel):
    entry_id: int
    entry_type: str  # "invoice" or "credit_note"
    date: datetime
    voucher_type: str
    source_voucher_type: str  # "sales" or "purchase"
    reference_number: str
    ledger_name: str
    particulars: str
    gst_rate: float
    taxable_amount: float
    debit_cgst: float
    debit_sgst: float
    debit_igst: float
    debit_total_tax: float
    credit_cgst: float
    credit_sgst: float
    credit_igst: float
    credit_total_tax: float


class TaxLedgerTotals(BaseModel):
    debit_cgst: float
    debit_sgst: float
    debit_igst: float
    debit_total_tax: float
    credit_cgst: float
    credit_sgst: float
    credit_igst: float
    credit_total_tax: float
    net_cgst: float
    net_sgst: float
    net_igst: float
    net_total_tax: float


class TaxLedgerOut(BaseModel):
    from_date: date
    to_date: date
    voucher_type: str | None = None
    gst_rate: float | None = None
    entries: list[TaxLedgerEntry]
    totals: TaxLedgerTotals
    fy_label: str | None = None
    financial_year_id: int | None = None