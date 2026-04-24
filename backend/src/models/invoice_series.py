from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from datetime import datetime
from src.db.base import Base


class InvoiceSeries(Base):
    __tablename__ = "invoice_series"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    voucher_type = Column(String, nullable=False)  # sales | purchase | payment
    financial_year_id = Column(Integer, ForeignKey("financial_years.id"), nullable=True)
    prefix = Column(String, nullable=False)
    suffix = Column(String, default="", nullable=False)
    include_year = Column(Boolean, default=True, nullable=False)
    year_format = Column(String, default="YYYY", nullable=False)  # 'YYYY' or 'MM-YYYY'
    separator = Column(String, default="-", nullable=False)
    next_sequence = Column(Integer, default=1, nullable=False)
    pad_digits = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
