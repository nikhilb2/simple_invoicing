from sqlalchemy import Boolean, Column, DateTime, Integer, String, Numeric, ForeignKey, func
from src.db.base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    sku = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    hsn_sac = Column(String, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    unit = Column(String, nullable=False, default="Pieces")
    allow_decimal = Column(Boolean, nullable=False, default=False)
    maintain_inventory = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
