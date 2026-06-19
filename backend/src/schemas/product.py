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
    is_producable: bool = False
    production_cost: Optional[float] = None
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
    is_producable: bool
    production_cost: Optional[float]
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProductWithInventoryOut(BaseModel):
    id: int
    sku: str
    name: str
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    price: float
    gst_rate: float
    unit: str
    allow_decimal: bool
    maintain_inventory: bool
    is_producable: bool
    production_cost: Optional[float] = None
    created_at: Optional[datetime] = None
    current_stock: float = 0
    reorder_level: float = 0
    status: str = "active"

    class Config:
        from_attributes = True


class ProductWithInventoryUpdate(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    category: Optional[str] = None
    purchase_price: Optional[float] = None
    selling_price: Optional[float] = None
    current_stock: Optional[float] = None
    reorder_level: Optional[float] = None
    status: Optional[str] = None
    unit: Optional[str] = None
    gst_rate: Optional[float] = None

    @field_validator("hsn_sac")
    @classmethod
    def validate_hsn_sac(cls, value: str | None) -> str | None:
        return normalize_hsn_sac(value)


class ImportCSVResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]


class PaginatedProductOut(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int
    total_pages: int
