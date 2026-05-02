from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class BOMComponentOut(BaseModel):
    """BOM component with product details"""
    id: int
    product_id: int
    component_product_id: int
    quantity_required: float
    created_at: Optional[datetime] = None
    
    # Denormalized component product info
    component_sku: str
    component_name: str
    component_price: float
    component_unit: str
    component_allow_decimal: bool


class BOMCreate(BaseModel):
    """Create a new BOM entry"""
    product_id: int
    component_product_id: int
    quantity_required: float


class BOMUpdate(BaseModel):
    """Update a BOM entry"""
    quantity_required: float


class ProduceRequest(BaseModel):
    """Request to produce an item"""
    product_id: int
    quantity: float


class ProductionTransactionOut(BaseModel):
    """Production transaction response"""
    id: int
    company_id: int
    product_id: int
    quantity_produced: float
    user_id: int
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaginatedProductionTransactionOut(BaseModel):
    """Paginated production transactions"""
    items: list[ProductionTransactionOut]
    total: int
    page: int
    page_size: int
    total_pages: int
