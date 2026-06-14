from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from sqlalchemy.orm import relationship

from src.db.base import Base


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    gst = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    currency_code = Column(String, nullable=True)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    bank_name = Column(String, nullable=True)
    branch_name = Column(String, nullable=True)
    account_name = Column(String, nullable=True)
    account_number = Column(String, nullable=True)
    ifsc_code = Column(String, nullable=True)
    logo_data = Column(Text, nullable=True)
    logo_mime_type = Column(String(50), nullable=True)
    additional_company_info = Column(Text, nullable=True)
    show_sku_on_pdf = Column(Boolean, nullable=False, default=False)
    eway_enabled = Column(Boolean, nullable=False, default=True)
    eway_local_threshold = Column(Float, nullable=False, default=100000)
    eway_interstate_threshold = Column(Float, nullable=False, default=50000)
    eway_always_show_button = Column(Boolean, nullable=False, default=True)
    terms = relationship("CompanyTerm", back_populates="company", order_by="CompanyTerm.serial_number", cascade="all, delete-orphan")
