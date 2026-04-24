from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from src.db.base import Base


class CompanyAccount(Base):
    __tablename__ = "company_accounts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    account_type = Column(String, nullable=False, default="bank")  # "bank" or "cash"
    display_name = Column(String, nullable=False, index=True)
    bank_name = Column(String, nullable=True)
    branch_name = Column(String, nullable=True)
    account_name = Column(String, nullable=True)
    account_number = Column(String, nullable=True)
    ifsc_code = Column(String, nullable=True)
    display_on_invoice = Column(Boolean, nullable=False, default=True)
    opening_balance = Column(Numeric(12, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    payments = relationship("Payment", back_populates="account")
