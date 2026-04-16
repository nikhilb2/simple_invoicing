from sqlalchemy import Column, DateTime, Integer, String, Numeric, func
from src.db.base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    hsn_sac = Column(String, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
