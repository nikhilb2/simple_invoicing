from sqlalchemy import Column, Integer, ForeignKey, DateTime, Numeric, String
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db.base import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String, nullable=True, unique=True, index=True)
    ledger_id = Column("buyer_id", Integer, ForeignKey("buyers.id"), nullable=True)
    ledger_name = Column("buyer_name", String, nullable=True)
    ledger_address = Column("buyer_address", String, nullable=True)
    ledger_gst = Column("buyer_gst", String, nullable=True)
    ledger_phone = Column("buyer_phone", String, nullable=True)
    company_name = Column(String, nullable=True)
    company_address = Column(String, nullable=True)
    company_gst = Column(String, nullable=True)
    company_phone = Column(String, nullable=True)
    company_email = Column(String, nullable=True)
    company_website = Column(String, nullable=True)
    company_currency_code = Column(String, nullable=True)
    company_bank_name = Column(String, nullable=True)
    company_branch_name = Column(String, nullable=True)
    company_account_name = Column(String, nullable=True)
    company_account_number = Column(String, nullable=True)
    company_ifsc_code = Column(String, nullable=True)
    voucher_type = Column(String, nullable=False, default="sales")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_tax_amount = Column(Numeric(10, 2), nullable=False, default=0)
    cgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    sgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    igst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)
    invoice_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    ledger = relationship("Buyer", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    hsn_sac = Column(String, nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(10, 2), nullable=False, default=0)
    line_total = Column(Numeric(10, 2), nullable=False)

    invoice = relationship("Invoice", back_populates="items")
