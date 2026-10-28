from datetime import date
from typing import Literal

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


# --- Product performance ---------------------------------------------------
# All money is ex-GST. Revenue/spend are line taxable_amount less each line's
# share of any invoice-level discount, less active credit notes (outward for
# sales, inward for purchases). Cost is the period's weighted average purchase
# price, else the product's current purchase_price (cost_basis tells which);
# when neither exists every cost-derived field is null.

CostBasis = Literal["purchases", "current_price"]


class ProductPerformanceRow(BaseModel):
    product_id: int
    name: str
    sku: str | None = None
    units_sold: float  # gross, before returns
    units_returned: float  # from active outward "return" credit notes
    net_units_sold: float
    units_bought: float  # gross, before purchase returns
    units_purchase_returned: float  # from active inward "return" notes
    net_units_bought: float
    average_selling_price: float | None = None  # sales_value / units_sold
    average_buying_price: float | None = None  # unit cost used for COGS
    cost_basis: CostBasis | None = None  # None when there is no cost at all
    sales_value: float  # gross sales, ex-GST, net of all discounts
    return_value: float  # outward credit notes (returns and price credits)
    revenue: float  # sales_value - return_value
    purchase_value: float
    purchase_return_value: float  # inward credit notes
    purchase_spend: float  # purchase_value - purchase_return_value
    cogs: float | None = None  # net_units_sold * average_buying_price
    gross_profit: float | None = None  # revenue - cogs
    margin_pct: float | None = None  # gross_profit / revenue * 100
    profit_per_unit: float | None = None  # gross_profit / net_units_sold
    current_stock: float | None = None  # None when the product isn't stock-tracked


class ProductPerformanceTotals(BaseModel):
    product_count: int
    units_sold: float
    units_returned: float
    net_units_sold: float
    units_bought: float
    units_purchase_returned: float
    net_units_bought: float
    sales_value: float
    return_value: float
    revenue: float
    purchase_value: float
    purchase_return_value: float
    purchase_spend: float
    costed_revenue: float  # revenue of rows with a known cost
    cogs: float  # over costed rows only
    gross_profit: float  # over costed rows only
    margin_pct: float | None = None  # gross_profit / costed_revenue * 100
    uncosted_product_count: int  # rows excluded from profit totals
    current_price_product_count: int  # rows costed at the current purchase price


class ProductPerformanceReport(BaseModel):
    currency_code: str
    period: ReportPeriod
    sort_by: str
    sort_dir: str
    rows: list[ProductPerformanceRow]
    totals: ProductPerformanceTotals
