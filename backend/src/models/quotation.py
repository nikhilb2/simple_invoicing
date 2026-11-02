"""Quotations and proforma invoices: offers, kept entirely apart from the books.

One model for both documents, told apart by ``document_type``. They live in their
own tables on purpose. Across this codebase "not sales" is read as "purchase" --
stock goes up, GST becomes input credit -- so a quotation stored on ``invoices``
would add stock and reduce the tax shown as payable unless every query remembered
to exclude it. Here a query that has never heard of quotations is already correct.

A quotation holds no serials and no payments, and reaches the books only when
:func:`src.services.quotation.convert_quotation` creates a real invoice from it.
``invoices.source_quotation_id`` records that link; it sits on the invoice side so
the history survives the invoice being cancelled and the quotation re-invoiced.

Columns carry the same names as their ``invoices`` counterparts, and the money
columns the same precision, so conversion cannot overflow and the shared totals
and PDF helpers work on either.
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from src.db.base import Base

DOCUMENT_QUOTATION = "quotation"
DOCUMENT_PROFORMA = "proforma"
DOCUMENT_TYPES = (DOCUMENT_QUOTATION, DOCUMENT_PROFORMA)

STATUS_OPEN = "open"
STATUS_ACCEPTED = "accepted"
STATUS_DECLINED = "declined"
STATUS_CONVERTED = "converted"
STATUS_CANCELLED = "cancelled"
# Derived for display and filtering, never stored.
STATUS_EXPIRED = "expired"

# The states a validity date can run out in. A declined, converted or cancelled
# quotation has nothing left to expire.
EXPIRABLE_STATUSES = (STATUS_OPEN, STATUS_ACCEPTED)


class Quotation(Base):
    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("company_id", "quotation_number", name="uq_quotations_company_number"),
        Index("ix_quotations_company_status", "company_id", "status"),
        Index("ix_quotations_company_date", "company_id", "quotation_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=False)
    document_type = Column(String(16), nullable=False, default=DOCUMENT_QUOTATION)
    quotation_number = Column(String, nullable=False)
    status = Column(String(16), nullable=False, default=STATUS_OPEN)
    quotation_date = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=True)
    financial_year_id = Column(Integer, ForeignKey("financial_years.id"), nullable=True)

    ledger_id = Column(Integer, ForeignKey("buyers.id"), nullable=False, index=True)
    ledger_name = Column(String, nullable=True)
    ledger_address = Column(String, nullable=True)
    ledger_gst = Column(String, nullable=True)
    ledger_phone = Column(String, nullable=True)

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
    company_logo_data = Column(Text, nullable=True)
    company_logo_mime_type = Column(String(50), nullable=True)
    company_additional_info = Column(Text, nullable=True)
    company_terms_text = Column(Text, nullable=True)

    shipping_address = Column(Text, nullable=True)
    shipping_address_label = Column(String(255), nullable=True)
    # Kept alongside the snapshot so conversion can hand the invoice the saved
    # address by id. Passing the snapshot through new_shipping_address instead
    # would add a duplicate ledger_addresses row on every conversion.
    shipping_address_id = Column(
        Integer, ForeignKey("ledger_addresses.id", ondelete="SET NULL"), nullable=True
    )

    reference_notes = Column(String, nullable=True)
    tax_inclusive = Column(Boolean, nullable=False, default=False)
    apply_round_off = Column(Boolean, nullable=False, default=False)
    round_off_amount = Column(Numeric(5, 2), nullable=False, default=0)
    discount_type = Column(String(20), nullable=True)
    discount_value = Column(Numeric(10, 2), nullable=True)
    taxable_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_tax_amount = Column(Numeric(10, 2), nullable=False, default=0)
    cgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    sgst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    igst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False, default=0)

    # Decline reason, or how an acceptance arrived ("PO 123 by email").
    status_note = Column(String, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    declined_at = Column(DateTime, nullable=True)
    converted_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    ledger = relationship("Buyer")
    items = relationship(
        "QuotationItem",
        back_populates="quotation",
        cascade="all, delete-orphan",
        order_by="QuotationItem.id",
    )

    def is_expired_on(self, today: date) -> bool:
        """Expiry is derived from the date, never stored, so it cannot go stale.

        Valid through the whole of ``valid_until``, the same rule as an invoice
        due date: due today counts as not yet due.
        """
        return (
            self.valid_until is not None
            and self.status in EXPIRABLE_STATUSES
            and self.valid_until < today
        )


class QuotationItem(Base):
    """One line. No serial column: serials are physical units, picked at conversion."""

    __tablename__ = "quotation_items"

    id = Column(Integer, primary_key=True, index=True)
    quotation_id = Column(
        Integer, ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
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

    quotation = relationship("Quotation", back_populates="items")
