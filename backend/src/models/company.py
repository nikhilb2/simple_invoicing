from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

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
    terms_and_conditions = Column(JSONB, default=list, nullable=True)
    logo_path = Column(String(512), nullable=True)
    additional_company_info = Column(Text, nullable=True)