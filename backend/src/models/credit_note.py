from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db.base import Base


class CreditNote(Base):
    __tablename__ = "credit_notes"

    id = Column(Integer, primary_key=True, index=True)
    credit_note_number = Column(String, nullable=False, unique=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    ledger_id = Column(Integer, ForeignKey("buyers.id"), nullable=False)
    financial_year_id = Column(Integer, ForeignKey("financial_years.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    credit_note_type = Column(String, nullable=False, default="return")
    reason = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    cgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    sgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    igst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    cancelled_at = Column(DateTime, nullable=True)

    ledger = relationship("Buyer", backref="credit_notes")
    invoice_refs = relationship("CreditNoteInvoiceRef", back_populates="credit_note", cascade="all, delete-orphan")
    items = relationship("CreditNoteItem", back_populates="credit_note", cascade="all, delete-orphan")


class CreditNoteInvoiceRef(Base):
    __tablename__ = "credit_note_invoice_refs"

    id = Column(Integer, primary_key=True, index=True)
    credit_note_id = Column(Integer, ForeignKey("credit_notes.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)

    credit_note = relationship("CreditNote", back_populates="invoice_refs")
    invoice = relationship("Invoice")


class CreditNoteItem(Base):
    __tablename__ = "credit_note_items"

    id = Column(Integer, primary_key=True, index=True)
    credit_note_id = Column(Integer, ForeignKey("credit_notes.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    invoice_item_id = Column(Integer, ForeignKey("invoice_items.id"), nullable=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(10, 2), nullable=False, default=0)
    line_total = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    credit_note = relationship("CreditNote", back_populates="items")
    invoice_item = relationship("InvoiceItem")
