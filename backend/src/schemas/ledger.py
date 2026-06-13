from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator

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


class LedgerStatementInvoiceAllocation(BaseModel):
    invoice_id: int
    invoice_number: str | None = None
    invoice_date: datetime | None = None
    due_date: datetime | None = None
    payment_status: str | None = None
    allocated_amount: float


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
    invoice_allocations: list[LedgerStatementInvoiceAllocation] = Field(default_factory=list)


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
    ledger_gst: str | None = None
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


# ── GSTR-1 Schemas ────────────────────────────────────────────────────────


class Gstr1ValidationError(BaseModel):
    invoice_number: str
    field: str
    message: str
    severity: str = "error"  # "error" | "warning"


class Gstr1ValidationResult(BaseModel):
    status: str  # "valid" | "invalid"
    errors: list[Gstr1ValidationError] = []
    total_invoices: int = 0
    valid_invoices: int = 0
    invalid_invoices: int = 0


class Gstr1CategorySummary(BaseModel):
    invoice_count: int = 0
    taxable_value: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    total_tax: float = 0.0


class Gstr1HsnSummaryItem(BaseModel):
    hsn_code: str
    description: str | None = None
    uqc: str = "NOS"
    quantity: float = 0.0
    taxable_value: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    total_tax: float = 0.0


class Gstr1DocSummary(BaseModel):
    total_invoices: int = 0
    total_credit_notes: int = 0
    total_debit_notes: int = 0
    cancelled_invoices: int = 0


class Gstr1Summary(BaseModel):
    from_date: date
    to_date: date
    gstin: str | None = None
    b2b: Gstr1CategorySummary = Gstr1CategorySummary()
    b2cl: Gstr1CategorySummary = Gstr1CategorySummary()
    b2cs: Gstr1CategorySummary = Gstr1CategorySummary()
    credit_notes: Gstr1CategorySummary = Gstr1CategorySummary()
    debit_notes: Gstr1CategorySummary = Gstr1CategorySummary()
    nil_rated: Gstr1CategorySummary = Gstr1CategorySummary()
    exempt: Gstr1CategorySummary = Gstr1CategorySummary()
    non_gst: Gstr1CategorySummary = Gstr1CategorySummary()
    hsn_summary: list[Gstr1HsnSummaryItem] = []
    doc_summary: Gstr1DocSummary = Gstr1DocSummary()


# ── GSTR-1 JSON Export (GSTN-compatible) ──────────────────────────────────


class Gstr1B2BInvoice(BaseModel):
    inum: str  # Invoice Number
    idt: str   # Invoice Date (YYYY-MM-DD)
    val: float  # Invoice Value
    pos: str    # Place of Supply (state code, 2 digits)
    rchrg: str = "N"  # Reverse Charge
    inv_typ: str = "R"  # Invoice Type
    itms: list[dict] = []  # Items with tax breakdown


class Gstr1B2B(BaseModel):
    ctin: str  # Customer GSTIN
    inv: list[Gstr1B2BInvoice] = []


class Gstr1B2CLInvoice(BaseModel):
    inum: str
    idt: str
    val: float
    pos: str
    inv_typ: str = "R"
    itms: list[dict] = []


class Gstr1B2CSItem(BaseModel):
    ty: str   # Supply Type (inter/intra)
    hsn_sc: str
    txval: float
    irt: float  # IGST Rate
    crt: float  # CGST Rate
    srt: float  # SGST Rate
    iamt: float
    camt: float
    samt: float


class Gstr1JsonExport(BaseModel):
    gstin: str
    fp: str  # Filing Period (MMYYYY)
    b2b: list[dict] = []
    b2cl: list[dict] = []
    b2cs: list[dict] = []
    cdnr: list[dict] = []
    hsn: dict = {}
    doc_issue: dict = {}