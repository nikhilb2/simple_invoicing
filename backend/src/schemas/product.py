from datetime import datetime
from pydantic import BaseModel, field_validator
from typing import Optional

from src.core.validation import normalize_hsn_sac


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    price: float
    gst_rate: float = 0
    maintain_inventory: bool = True
    initial_quantity: int = 0

    @field_validator("hsn_sac")
    @classmethod
    def validate_hsn_sac(cls, value: str | None) -> str | None:
        return normalize_hsn_sac(value)


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: Optional[str]
    hsn_sac: Optional[str]
    price: float
    gst_rate: float
    maintain_inventory: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaginatedProductOut(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int
    total_pages: int
