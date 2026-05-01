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
    unit: str = "Pieces"
    allow_decimal: bool = False
    maintain_inventory: bool = True
    initial_quantity: float = 0

    @field_validator("hsn_sac")
    @classmethod
    def validate_hsn_sac(cls, value: str | None) -> str | None:
        return normalize_hsn_sac(value)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Unit is required")
        return normalized


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: Optional[str]
    hsn_sac: Optional[str]
    price: float
    gst_rate: float
    unit: str
    allow_decimal: bool
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
