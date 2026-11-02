from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func, text

from src.db.base import Base


class EwayBillTransporter(Base):
    __tablename__ = "eway_bill_transporters"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    transporter_name = Column(String(255), nullable=False)
    transporter_gstin = Column(String(15), nullable=True)
    transport_mode = Column(String(20), nullable=False, default="1", server_default=text("'1'"))
    vehicle_type = Column(String(10), nullable=False, default="R", server_default=text("'R'"))
    is_default = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
