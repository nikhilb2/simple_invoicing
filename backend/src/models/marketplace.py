"""Instance-side marketplace models.

These mirror what the central marketplace server holds for this instance: the
connection credential, the listings we published, and the orders on both sides
together with the exactly-once event ledger that drives them.

SQLite compatibility is load-bearing here — the test suite builds its schema from
``Base.metadata`` rather than from the migrations, so nothing in this module may
use JSONB, SERIAL, partial indexes or any other Postgres-only construct. The
Postgres-specific structure lives in the migration only.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from src.core.security import decrypt_value, encrypt_value
from src.db.base import Base


class MarketplaceConnection(Base):
    """One row per CompanyProfile — a company registers with the marketplace as a
    seller identified by its GSTIN, and is both seller and buyer through it."""

    __tablename__ = "marketplace_connections"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer,
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    base_url = Column(String(500), nullable=False)
    remote_seller_id = Column(String(100), nullable=True)
    gstin = Column(String(20), nullable=True)
    display_name = Column(String(255), nullable=True)
    # Fernet ciphertext. Rotating SMTP_ENCRYPTION_KEY orphans this exactly as it
    # orphans SMTP passwords and API keys.
    _credential = Column("credential_encrypted", Text, nullable=True)
    credential_prefix = Column(String(32), nullable=True)
    # Stable per install; the central server logs a mismatch, which is how a
    # credential copied to a second machine becomes detectable.
    instance_uuid = Column(String(64), nullable=True)

    # unregistered|pending_approval|connected|unauthorized|suspended|disconnected
    status = Column(String(32), nullable=False, default="unregistered")

    sync_cursor = Column(BigInteger, nullable=False, default=0)
    # Claimed by a conditional UPDATE rather than an advisory lock, so the same
    # code path works on SQLite under test.
    sync_lock_until = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_error = Column(Text, nullable=True)

    auto_accept = Column(Boolean, nullable=False, default=True)
    auto_accept_max_amount = Column(Numeric(12, 2), nullable=True)
    # Phase 3 posture: orders land in the Orders page and a human posts them.
    auto_post = Column(Boolean, nullable=False, default=False)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    registered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @property
    def credential(self) -> str | None:
        if not self._credential:
            return None
        return decrypt_value(self._credential)

    @credential.setter
    def credential(self, value: str | None) -> None:
        if value is None:
            self._credential = None
            self.credential_prefix = None
            return
        self._credential = encrypt_value(value)
        self.credential_prefix = value[:16]


class MarketplaceListing(Base):
    """Local mirror of a product we published to the marketplace."""

    __tablename__ = "marketplace_listings"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    remote_listing_id = Column(String(100), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # Per unit and TAX EXCLUSIVE — both sides post with tax_inclusive=false so the
    # two documents agree to the paisa.
    asking_price = Column(Numeric(12, 2), nullable=False, default=0)
    currency_code = Column(String(8), nullable=False, default="INR")
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    hsn_sac = Column(String(20), nullable=True)
    unit = Column(String(50), nullable=False, default="Pieces")
    allow_decimal = Column(Boolean, nullable=False, default=False)
    min_order_quantity = Column(Numeric(12, 3), nullable=True)
    max_order_quantity = Column(Numeric(12, 3), nullable=True)
    # Advisory snapshot: stale by construction, the seller instance is authoritative.
    available_quantity_published = Column(Numeric(12, 3), nullable=True)

    status = Column(String(32), nullable=False, default="draft")
    listing_type = Column(String(32), nullable=False, default="buy_now")
    last_published_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", name="ux_marketplace_listings_company_product"),
        UniqueConstraint(
            "company_id", "remote_listing_id", name="ux_marketplace_listings_company_remote"
        ),
    )


class MarketplaceOrder(Base):
    """An order, held by both sides — ``side`` says which one we are."""

    __tablename__ = "marketplace_orders"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    side = Column(String(8), nullable=False)  # 'sell' | 'buy'
    remote_order_id = Column(String(100), nullable=False)
    order_type = Column(String(32), nullable=False, default="buy_now")
    # pending|accepted|rejected|cancelled|expired|posted
    state = Column(String(32), nullable=False, default="pending")
    remote_listing_id = Column(String(100), nullable=True)

    counterparty_remote_id = Column(String(100), nullable=True)
    counterparty_name = Column(String(255), nullable=True)
    counterparty_gstin = Column(String(20), nullable=True)
    counterparty_address = Column(Text, nullable=True)
    counterparty_phone = Column(String(50), nullable=True)
    counterparty_email = Column(String(255), nullable=True)

    currency_code = Column(String(8), nullable=False, default="INR")
    remote_total_amount = Column(Numeric(14, 2), nullable=True)
    order_placed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    reject_reason = Column(String(64), nullable=True)
    reject_note = Column(Text, nullable=True)

    seller_invoice_number = Column(String(100), nullable=True)
    seller_invoice_date = Column(DateTime, nullable=True)

    # not_required|pending|posting|posted|failed|skipped
    posting_state = Column(String(32), nullable=False, default="not_required")
    posting_lock_until = Column(DateTime, nullable=True)
    posted_invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    posting_error = Column(Text, nullable=True)
    posting_attempts = Column(Integer, nullable=False, default=0)
    posting_warnings = Column(Text, nullable=True)
    total_mismatch = Column(Boolean, nullable=False, default=False)
    remote_posting_reported = Column(Boolean, nullable=False, default=False)
    # Belt-and-braces against redelivery out of order: an event whose seq is not
    # ahead of this is dropped.
    last_event_seq = Column(BigInteger, nullable=False, default=0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    items = relationship(
        "MarketplaceOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="MarketplaceOrderItem.line_no",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "remote_order_id", name="ux_marketplace_orders_company_remote"),
    )


class MarketplaceOrderItem(Base):
    """Multi-line from day one — a future auction/basket flow needs it and
    retrofitting a child table onto posted accounting is not an option."""

    __tablename__ = "marketplace_order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer, ForeignKey("marketplace_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no = Column(Integer, nullable=False)
    remote_listing_id = Column(String(100), nullable=True)
    title = Column(String(255), nullable=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    quantity = Column(Numeric(12, 3), nullable=False, default=0)
    unit = Column(String(50), nullable=True)
    unit_price = Column(Numeric(12, 2), nullable=False, default=0)
    gst_rate = Column(Numeric(5, 2), nullable=False, default=0)
    hsn_sac = Column(String(20), nullable=True)

    order = relationship("MarketplaceOrder", back_populates="items")

    __table_args__ = (
        UniqueConstraint("order_id", "line_no", name="ux_marketplace_order_items_order_line"),
    )


class MarketplaceProcessedEvent(Base):
    """The exactly-once ledger. Inserted as the FIRST statement of each per-event
    transaction, so a duplicate raises IntegrityError before anything is applied."""

    __tablename__ = "marketplace_processed_events"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id = Column(String(100), nullable=False)
    event_type = Column(String(64), nullable=False)
    seq = Column(BigInteger, nullable=False, default=0)
    remote_order_id = Column(String(100), nullable=True)
    result = Column(String(16), nullable=False, default="applied")  # applied|ignored|error
    error = Column(Text, nullable=True)
    payload = Column(Text, nullable=True)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "event_id", name="ux_marketplace_events_company_event"),
        Index("ix_marketplace_events_company_seq", "company_id", "seq"),
    )


class MarketplaceProductLink(Base):
    """Remote listing → local product, so repeat purchases from the same listing
    reuse the product instead of auto-creating another one."""

    __tablename__ = "marketplace_product_links"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    remote_listing_id = Column(String(100), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "company_id", "remote_listing_id", name="ux_marketplace_product_links_company_listing"
        ),
    )


class MarketplaceLedgerLink(Base):
    """Remote seller → local ledger (Buyer row)."""

    __tablename__ = "marketplace_ledger_links"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    remote_seller_id = Column(String(100), nullable=False)
    ledger_id = Column(Integer, ForeignKey("buyers.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "company_id", "remote_seller_id", name="ux_marketplace_ledger_links_company_seller"
        ),
    )
