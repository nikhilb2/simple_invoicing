from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal, Optional

from src.schemas.product import ProductOut


class SerialInvoiceRef(BaseModel):
    id: int
    invoice_number: Optional[str] = None
    invoice_date: Optional[datetime] = None

    class Config:
        from_attributes = True


class SerialOut(BaseModel):
    id: int
    serial_number: str
    status: str
    product_id: int
    product: ProductOut
    # A sold unit carries the invoice it went out on — this is what turns the
    # scan bar into a warranty lookup for a handset carried back into the shop.
    purchase_invoice: Optional[SerialInvoiceRef] = None
    sales_invoice: Optional[SerialInvoiceRef] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SerialScanOut(BaseModel):
    kind: Literal["serial", "product"]
    serial: Optional[SerialOut] = None
    product: Optional[ProductOut] = None


class PaginatedSerialOut(BaseModel):
    items: list[SerialOut] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    total_pages: int
