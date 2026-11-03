from sqlalchemy import Boolean, Column, Index, Integer, ForeignKey, DateTime, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db.base import Base


class Invoice(Base):
    __tablename__ = "invoices"
    # Numbers are unique per company, not per database: every company's series
    # starts at -001, and a global constraint would make one tenant's numbers
    # collide with (and reveal the volume of) another's.
    __table_args__ = (
        UniqueConstraint("company_id", "invoice_number", name="uq_invoices_company_invoice_number"),
        # At most one live invoice per quotation. Cancelled invoices stay behind as
        # history, and restoring one while a newer invoice is live hits this too.
        # Declared for both dialects: with postgresql_where alone, the SQLite test
        # schema would make the index fully unique and refuse a re-conversion.
        Index(
            "ux_invoices_active_source_quotation",
            "source_quotation_id",
            unique=True,
            postgresql_where=text("source_quotation_id IS NOT NULL AND status = 'active'"),
            sqlite_where=text("source_quotation_id IS NOT NULL AND status = 'active'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String, nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
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
    supplier_invoice_number = Column(String, nullable=True)
    reference_notes = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    credit_status = Column(String, nullable=False, default="not_credited")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_tax_amount = Column(Numeric(10, 2), nullable=False, default=0)
    cgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    sgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    igst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)
    invoice_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    due_date = Column(DateTime, nullable=True)
    tax_inclusive = Column(Boolean, nullable=False, default=False)
    apply_round_off = Column(Boolean, nullable=False, default=False)
    round_off_amount = Column(Numeric(5, 2), nullable=False, default=0)
    discount_type = Column(String(20), nullable=True)
    discount_value = Column(Numeric(10, 2), nullable=True)
    financial_year_id = Column(Integer, ForeignKey("financial_years.id"), nullable=True)
    shipping_address = Column(Text, nullable=True)
    shipping_address_label = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Company branding fields snapped for per-invoice PDF rendering
    company_logo_data = Column(Text, nullable=True)
    company_logo_mime_type = Column(String(50), nullable=True)
    company_additional_info = Column(Text, nullable=True)
    company_terms_text = Column(Text, nullable=True)

    # The quotation or proforma this invoice was converted from. Kept for life, unless
    # the invoice is cancelled and the quotation is then edited: it no longer describes
    # this invoice, so update_quotation clears the link.
    source_quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=True)

    ledger = relationship("Buyer", back_populates="invoices")
    # selectin: an invoice list reads the number off every row, and most rows have
    # none, so one IN query for the few that do rather than one query each.
    source_quotation = relationship("Quotation", lazy="selectin")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payment_allocations = relationship("PaymentInvoiceAllocation", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def source_quotation_number(self) -> str | None:
        return self.source_quotation.quotation_number if self.source_quotation else None


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    hsn_sac = Column(String, nullable=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(10, 2), nullable=False, default=0)
    cgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    sgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    igst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    line_total = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    discount_type = Column(String(20), nullable=True)
    discount_value = Column(Numeric(10, 2), nullable=True)

    invoice = relationship("Invoice", back_populates="items")
