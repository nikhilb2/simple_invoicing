from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db.base import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column("buyer_id", Integer, ForeignKey("buyers.id"), nullable=False)
    voucher_type = Column(String, nullable=False)  # "receipt" or "payment"
    amount = Column(Numeric(10, 2), nullable=False)
    date = Column(DateTime, nullable=False, default=datetime.utcnow)
    payment_number = Column(String, nullable=True)  # e.g. PAY-2026-001
    mode = Column(String, nullable=True)  # cash, bank, upi, cheque
    reference = Column(String, nullable=True)  # cheque no, txn id
    notes = Column(String, nullable=True)
    financial_year_id = Column(Integer, ForeignKey("financial_years.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ledger = relationship("Buyer", backref="payments")
