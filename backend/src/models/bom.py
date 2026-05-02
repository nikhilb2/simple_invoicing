from sqlalchemy import Column, Integer, Numeric, ForeignKey, DateTime, func
from src.db.base import Base


class BillOfMaterial(Base):
    __tablename__ = "bill_of_materials"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    component_product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity_required = Column(Numeric(12, 3), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
