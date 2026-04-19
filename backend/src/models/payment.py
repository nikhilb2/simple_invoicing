from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db.base import Base
from src.models.company_account import CompanyAccount  # noqa: F401


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column("buyer_id", Integer, ForeignKey("buyers.id"), nullable=True)
    voucher_type = Column(String, nullable=False)  # "receipt" or "payment"
    amount = Column(Numeric(10, 2), nullable=False)
    date = Column(DateTime, nullable=False, default=datetime.utcnow)
    payment_number = Column(String, nullable=True)  # e.g. PAY-2026-001
    mode = Column(String, nullable=True)  # cash, bank, upi, cheque
    reference = Column(String, nullable=True)  # cheque no, txn id
    notes = Column(String, nullable=True)
    financial_year_id = Column(Integer, ForeignKey("financial_years.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("company_accounts.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, nullable=False, default="active")  # "active" | "cancelled"

    ledger = relationship("Buyer", backref="payments")
    account = relationship("CompanyAccount", back_populates="payments")
    invoice_allocations = relationship("PaymentInvoiceAllocation", back_populates="payment", cascade="all, delete-orphan")


class PaymentInvoiceAllocation(Base):
    __tablename__ = "payment_invoice_allocations"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    allocated_amount = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="invoice_allocations")
    invoice = relationship("Invoice", back_populates="payment_allocations")
