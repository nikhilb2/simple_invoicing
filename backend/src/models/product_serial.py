"""Per-unit serial / IMEI tracking for stock items.

One row per physical unit of a serial-tracked product.  A row moves
``in_stock`` → ``sold`` as it is purchased and then sold, and ``in_stock`` →
``void`` when the purchase that brought it in is cancelled.  The invoices it
arrived on and went out on are recorded, so a handset a customer walks back in
with can be traced to the sale it came from.

**Why invoice-level pointers rather than an ``invoice_item_id``:**
``update_invoice`` deletes and recreates every ``invoice_items`` row on each
save, so an item FK would be destroyed on every edit.  ``(sales_invoice_id,
product_id)`` survives instead — at the cost of one rule, enforced in
:class:`~src.services.serial_service.SerialManager`: a serial-tracked product
may appear on at most one line per invoice.

The test suite builds its schema from ``Base.metadata`` against in-memory
SQLite while production runs on Postgres, so the partial index below is
declared for both dialects — with only ``postgresql_where`` SQLite would
silently make the index fully unique and refuse to re-register a voided serial.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import relationship

from src.db.base import Base

STATUS_IN_STOCK = "in_stock"
STATUS_SOLD = "sold"
STATUS_VOID = "void"


class ProductSerial(Base):
    __tablename__ = "product_serials"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    # Stored exactly as the operator entered it; compared case-insensitively.
    serial_number = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default=STATUS_IN_STOCK)
    purchase_invoice_id = Column(
        Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    sales_invoice_id = Column(
        Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    note = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    product = relationship("Product")

    __table_args__ = (
        # Mirrors the migration exactly — Base.metadata.create_all() runs before
        # the migration runner on boot, so the two definitions have to agree.
        # Voided rows are excluded so a wrongly-entered IMEI can be registered
        # again once the purchase that carried it is cancelled.
        Index(
            "ux_product_serials_company_number",
            "company_id",
            func.upper(serial_number),
            unique=True,
            postgresql_where=text("status <> 'void'"),
            sqlite_where=text("status <> 'void'"),
        ),
        Index(
            "ix_product_serials_product_status",
            "company_id",
            "product_id",
            "status",
        ),
        Index("ix_product_serials_sales_invoice", "sales_invoice_id"),
        Index("ix_product_serials_purchase_invoice", "purchase_invoice_id"),
    )
