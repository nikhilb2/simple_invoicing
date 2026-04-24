from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey
from datetime import datetime
from src.db.base import Base


class FinancialYear(Base):
    __tablename__ = "financial_years"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    label = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
