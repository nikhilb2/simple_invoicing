from datetime import date

from pydantic import BaseModel


class ReportPeriod(BaseModel):
    """The date window a report actually covers, after server-side resolution.

    Echoed back because the client may send no dates at all and let the server
    fall back to the active financial year — the UI needs to show what it got.
    """

    from_date: date
    to_date: date
    financial_year_id: int | None = None
    fy_label: str | None = None


class MonthlySalesRow(BaseModel):
    month: str  # "2026-04"
    label: str  # "Apr 26"
    invoice_count: int
    total_sales: float  # sum of invoice total_amount, incl. GST and round-off
    taxable_value: float  # sum of invoice taxable_amount, ex-GST
    gst_collected: float  # sum of invoice total_tax_amount
    discount_given: float  # derived — see src.services.invoice_discounts
    average_invoice_value: float


class MonthlySalesTotals(BaseModel):
    invoice_count: int
    total_sales: float
    taxable_value: float
    gst_collected: float
    discount_given: float
    average_invoice_value: float


class MonthlySalesReport(BaseModel):
    currency_code: str
    voucher_type: str
    period: ReportPeriod
    rows: list[MonthlySalesRow]
    totals: MonthlySalesTotals


class ProductSalesRow(BaseModel):
    product_id: int
    name: str
    sku: str | None = None
    quantity_sold: float
    sales_amount: float  # sum of line taxable_amount, ex-GST
    average_selling_price: float  # sales_amount / quantity_sold
    total_revenue: float  # sum of line_total, incl. GST
    total_gst: float  # sum of line tax_amount
    invoice_count: int  # distinct invoices, not line items
    current_stock: float | None = None  # None when the product isn't stock-tracked


class ProductSalesTotals(BaseModel):
    product_count: int
    quantity_sold: float
    sales_amount: float
    total_revenue: float
    total_gst: float
    invoice_count: int  # distinct invoices across all rows


class ProductSalesReport(BaseModel):
    currency_code: str
    voucher_type: str
    period: ReportPeriod
    sort_by: str
    sort_dir: str
    rows: list[ProductSalesRow]
    totals: ProductSalesTotals


# --- Profit & Loss ---------------------------------------------------------
# Cost basis is the product's *current* purchase_price (invoice lines carry no
# cost snapshot). Revenue is taxable_amount, ex-GST — GST is pass-through and
# never profit. gross_profit = revenue - cogs; margin_pct = gross_profit / revenue.


class ProfitLossProductRow(BaseModel):
    product_id: int
    name: str
    sku: str | None = None
    quantity_sold: float
    sales_amount: float  # revenue, sum of line taxable_amount (ex-GST)
    average_selling_price: float  # sales_amount / quantity_sold
    purchase_price: float  # current unit cost
    cogs: float  # quantity_sold * purchase_price
    gross_profit: float  # sales_amount - cogs
    margin_pct: float  # gross_profit / sales_amount * 100


class ProfitLossMonthlyRow(BaseModel):
    month: str  # "2026-04"
    label: str  # "Apr 26"
    quantity: float
    revenue: float  # ex-GST
    cogs: float
    gross_profit: float
    margin_pct: float


class ProfitLossCustomerRow(BaseModel):
    ledger_id: int | None = None
    name: str
    revenue: float
    cogs: float
    gross_profit: float
    margin_pct: float
    invoice_count: int


class ProfitLossTotals(BaseModel):
    product_count: int
    quantity_sold: float
    revenue: float
    cogs: float
    gross_profit: float
    margin_pct: float


class ProfitLossReport(BaseModel):
    currency_code: str
    voucher_type: str
    period: ReportPeriod
    product_rows: list[ProfitLossProductRow]
    monthly_rows: list[ProfitLossMonthlyRow]
    customer_rows: list[ProfitLossCustomerRow]
    totals: ProfitLossTotals
