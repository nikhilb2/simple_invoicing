from sqlalchemy import Column, Integer, Numeric, String, ForeignKey, DateTime, func
from src.db.base import Base


class ProductionTransaction(Base):
    __tablename__ = "production_transactions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity_produced = Column(Numeric(12, 3), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
