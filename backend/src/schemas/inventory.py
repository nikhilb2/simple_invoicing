from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class InventoryAdjust(BaseModel):
    product_id: int
    quantity: int


class InventoryOut(BaseModel):
    product_id: int
    product_name: str
    sku: str
    price: float
    quantity: int
    date_added: Optional[datetime] = None
    last_sold_at: Optional[datetime] = None
