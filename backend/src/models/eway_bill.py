from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey
from datetime import datetime
from src.db.base import Base


class EwayBillTransporter(Base):
    __tablename__ = "eway_bill_transporters"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=False, index=True)
    transporter_name = Column(String(255), nullable=False)
    transporter_gstin = Column(String(15), nullable=True)
    transport_mode = Column(String(20), nullable=False, default="1")
    vehicle_type = Column(String(10), nullable=False, default="R")
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
