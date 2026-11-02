from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class InventoryAdjust(BaseModel):
    product_id: int
    quantity: float
    # Required on a serial-tracked product: which units came in, or which ones
    # are being written off.
    serial_numbers: Optional[list[str]] = None
    note: Optional[str] = None


class InventoryOut(BaseModel):
    product_id: int
    product_name: str
    sku: str
    unit: str
    allow_decimal: bool
    price: float
    maintain_inventory: bool
    track_serials: bool = False
    quantity: float
    date_added: Optional[datetime] = None
    last_sold_at: Optional[datetime] = None


class PaginatedInventoryOut(BaseModel):
    items: list[InventoryOut]
    total: int
    page: int
    page_size: int
    total_pages: int
