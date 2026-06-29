from pydantic import BaseModel


class CatalogMetrics(BaseModel):
    total_products: int
    producible_products: int


class InventoryMetrics(BaseModel):
    tracked_products: int
    total_units: float
    low_stock_count: int
    out_of_stock_count: int
    stock_value: float


class SalesMetrics(BaseModel):
    sales_invoice_count: int
    purchase_invoice_count: int
    total_sales: float
    total_purchases: float
    this_month_sales: float
    average_invoice_value: float


class ReceivablesMetrics(BaseModel):
    outstanding_amount: float
    overdue_amount: float
    overdue_count: int
    paid_count: int
    partial_count: int
    unpaid_count: int


class PaymentsMetrics(BaseModel):
    received_total: float
    paid_total: float
    this_month_received: float


class MonthlyPoint(BaseModel):
    month: str  # ISO year-month, e.g. "2026-01"
    label: str  # short display label, e.g. "Jan 26"
    sales: float
    purchases: float
    receipts: float


class TopProduct(BaseModel):
    product_id: int
    name: str
    quantity: float
    revenue: float


class DashboardCharts(BaseModel):
    monthly: list[MonthlyPoint]
    top_products: list[TopProduct]


class DashboardMetrics(BaseModel):
    currency_code: str
    catalog: CatalogMetrics
    inventory: InventoryMetrics
    sales: SalesMetrics
    receivables: ReceivablesMetrics
    payments: PaymentsMetrics
    charts: DashboardCharts
