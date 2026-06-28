from datetime import datetime

from pydantic import BaseModel


class DashboardInventoryPreview(BaseModel):
    product_id: int
    product_name: str
    quantity: float


class DashboardInvoicePreview(BaseModel):
    id: int
    invoice_number: str | None = None
    ledger_name: str | None = None
    total_amount: float
    invoice_date: datetime


class DashboardSummaryOut(BaseModel):
    product_count: int
    tracked_inventory_rows: int
    total_inventory_units: float
    low_stock_count: int
    active_invoice_total: float
    low_stock_threshold: float
    low_stock_items: list[DashboardInventoryPreview]
    recent_invoices: list[DashboardInvoicePreview]
