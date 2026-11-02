from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from src.core.validation import normalize_hsn_sac


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    price: float = Field(ge=0)
    purchase_price: float = Field(default=0, ge=0)
    gst_rate: float = 0
    unit: str = "Pieces"
    allow_decimal: bool = False
    maintain_inventory: bool = True
    is_producable: bool = False
    production_cost: Optional[float] = Field(default=None, ge=0)
    reorder_level: float = Field(default=0, ge=0)
    initial_quantity: float = Field(default=0, ge=0)
    track_serials: bool = False
    # Opening serials on create, backfill on enable — one field, one round-trip,
    # so the flag and the units behind it can never be saved apart.
    serial_numbers: Optional[list[str]] = None

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

    @field_validator("sku", "name")
    @classmethod
    def validate_sku_and_name_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank")
        return normalized


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: Optional[str]
    hsn_sac: Optional[str]
    price: float
    purchase_price: float = 0
    gst_rate: float
    unit: str
    allow_decimal: bool
    maintain_inventory: bool
    is_producable: bool
    production_cost: Optional[float]
    reorder_level: float = 0
    track_serials: bool = False
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
    purchase_price: float = 0
    gst_rate: float
    unit: str
    allow_decimal: bool
    maintain_inventory: bool
    is_producable: bool
    production_cost: Optional[float] = None
    reorder_level: float = 0
    track_serials: bool = False
    created_at: Optional[datetime] = None
    current_stock: float = 0
    status: str = "active"

    class Config:
        from_attributes = True


class ProductWithInventoryUpdate(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    description: Optional[str] = None
    hsn_sac: Optional[str] = None
    category: Optional[str] = None
    purchase_price: Optional[float] = Field(default=None, ge=0)
    selling_price: Optional[float] = Field(default=None, ge=0)
    # Bounded like every other way of changing stock: the edit form must
    # not be a back door to a negative quantity.
    current_stock: Optional[float] = Field(default=None, ge=0)
    reorder_level: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None
    unit: Optional[str] = None
    gst_rate: Optional[float] = None

    @field_validator("hsn_sac")
    @classmethod
    def validate_hsn_sac(cls, value: str | None) -> str | None:
        return normalize_hsn_sac(value)

    @field_validator("name", "sku")
    @classmethod
    def validate_name_and_sku_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank")
        return normalized


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
