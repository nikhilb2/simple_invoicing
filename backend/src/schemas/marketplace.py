"""Pydantic schemas for the instance-side marketplace API.

Money and quantities go out as decimal STRINGS, matching MARKETPLACE.md section 1
rather than the float convention the rest of this backend uses. That looks
inconsistent until you notice the browse/catalog endpoints proxy the central
server's payloads through untouched: if our own endpoints emitted floats, the
frontend would face two different representations of the same value inside one
feature. It parses these with exact decimal arithmetic, so a JSON float both
breaks that parser and silently rounds tax.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_serializer


def _money_str(value) -> str | None:
    """Two-decimal fixed point. Numeric columns arrive as Decimal on Postgres
    but float on SQLite, so route through str() before quantizing to avoid
    binary-float artefacts."""
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _qty_str(value) -> str | None:
    """Quantities are Numeric(12,3); trailing zeros are trimmed so a whole
    number reads as "50" rather than "50.000"."""
    if value is None:
        return None
    quantized = Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    # normalize() renders some integers in scientific notation (5E+1); format
    # with "f" to keep it plain.
    return format(quantized.normalize(), "f")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class MarketplaceMetaOut(BaseModel):
    marketplace_name: str | None = None
    min_client_version: str | None = None
    terms_url: str | None = None
    registration_open: bool = True
    requires_approval: bool = True
    order_ttl_hours: int | None = None
    event_retention_days: int | None = None


class ConnectionRegisterIn(BaseModel):
    base_url: str
    legal_name: str | None = None
    address: str | None = None
    state_code: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class ConnectionUpdateIn(BaseModel):
    auto_accept: bool | None = None
    auto_accept_max_amount: float | None = None
    auto_post: bool | None = None
    display_name: str | None = None


class ConnectionOut(BaseModel):
    id: int
    company_id: int
    base_url: str
    remote_seller_id: str | None = None
    gstin: str | None = None
    display_name: str | None = None
    # The credential itself is never returned — only its prefix, for display.
    credential_prefix: str | None = None
    instance_uuid: str | None = None
    status: str
    sync_cursor: int = 0
    last_sync_at: datetime | None = None
    last_sync_error: str | None = None
    auto_accept: bool = True
    auto_accept_max_amount: Decimal | None = None
    auto_post: bool = False
    registered_at: datetime | None = None
    created_at: datetime | None = None

    @field_serializer('auto_accept_max_amount')
    def _ser_money(self, value, _info):
        return _money_str(value)

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

class ListingCreateIn(BaseModel):
    product_id: int
    title: str | None = None
    description: str | None = None
    asking_price: float
    min_order_quantity: float | None = None
    max_order_quantity: float | None = None
    available_quantity: float | None = None
    listing_type: Literal["buy_now"] = "buy_now"


class ListingUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    asking_price: float | None = None
    min_order_quantity: float | None = None
    max_order_quantity: float | None = None
    available_quantity: float | None = None
    status: Literal["active", "paused"] | None = None


class ListingOut(BaseModel):
    id: int
    company_id: int
    product_id: int
    remote_listing_id: str | None = None
    title: str
    description: str | None = None
    asking_price: Decimal
    currency_code: str = "INR"
    gst_rate: Decimal = Decimal("0")
    hsn_sac: str | None = None
    unit: str = "Pieces"
    allow_decimal: bool = False
    min_order_quantity: Decimal | None = None
    max_order_quantity: Decimal | None = None
    available_quantity_published: Decimal | None = None
    status: str
    listing_type: str = "buy_now"
    last_published_at: datetime | None = None
    last_error: str | None = None

    @field_serializer('asking_price', 'gst_rate')
    def _ser_money(self, value, _info):
        return _money_str(value)

    @field_serializer('min_order_quantity', 'max_order_quantity', 'available_quantity_published')
    def _ser_qty(self, value, _info):
        return _qty_str(value)

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Browse — proxied straight through from the central server
# ---------------------------------------------------------------------------

class BrowseSellerOut(BaseModel):
    seller_id: str | None = None
    legal_name: str | None = None
    gstin: str | None = None
    state_code: str | None = None
    # v1 never verifies GSTIN ownership; the UI must badge this.
    verified: bool = False


class BrowseListingOut(BaseModel):
    listing_id: str
    title: str | None = None
    description: str | None = None
    asking_price: float | None = None
    currency_code: str = "INR"
    gst_rate: float | None = None
    hsn_sac: str | None = None
    unit: str | None = None
    allow_decimal: bool = False
    min_order_quantity: float | None = None
    max_order_quantity: float | None = None
    available_quantity: float | None = None
    available_quantity_as_of: datetime | None = None
    seller: BrowseSellerOut | None = None


class BrowseResultOut(BaseModel):
    items: list[BrowseListingOut] = Field(default_factory=list)
    next_cursor: str | None = None
    total_estimate: int | None = None


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class OrderCreateIn(BaseModel):
    listing_id: str
    quantity: float
    buyer_note: str | None = None
    delivery_address: str | None = None


class OrderRejectIn(BaseModel):
    reason: Literal[
        "insufficient_stock", "price_changed", "cannot_ship", "unknown_buyer", "other"
    ] = "other"
    note: str | None = None


class OrderLinkProductIn(BaseModel):
    remote_listing_id: str
    product_id: int


class OrderItemOut(BaseModel):
    id: int
    line_no: int
    remote_listing_id: str | None = None
    title: str | None = None
    product_id: int | None = None
    quantity: Decimal
    unit: str | None = None
    unit_price: Decimal
    gst_rate: Decimal
    hsn_sac: str | None = None

    @field_serializer('unit_price', 'gst_rate')
    def _ser_money(self, value, _info):
        return _money_str(value)

    @field_serializer('quantity')
    def _ser_qty(self, value, _info):
        return _qty_str(value)

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: int
    company_id: int
    side: str
    remote_order_id: str
    order_type: str = "buy_now"
    state: str
    remote_listing_id: str | None = None
    counterparty_remote_id: str | None = None
    counterparty_name: str | None = None
    counterparty_gstin: str | None = None
    counterparty_address: str | None = None
    counterparty_phone: str | None = None
    counterparty_email: str | None = None
    currency_code: str = "INR"
    remote_total_amount: Decimal | None = None
    order_placed_at: datetime | None = None
    expires_at: datetime | None = None
    accepted_at: datetime | None = None
    closed_at: datetime | None = None
    reject_reason: str | None = None
    reject_note: str | None = None
    seller_invoice_number: str | None = None
    seller_invoice_date: datetime | None = None
    posting_state: str
    posted_invoice_id: int | None = None
    # Resolved by the route, not stored on the order: a user recognises the
    # invoice number, not the row id.
    posted_invoice_number: str | None = None
    posted_at: datetime | None = None
    posting_error: str | None = None
    posting_attempts: int = 0
    posting_warnings: str | None = None
    total_mismatch: bool = False
    remote_posting_reported: bool = False
    last_event_seq: int = 0
    items: list[OrderItemOut] = Field(default_factory=list)

    @field_serializer('remote_total_amount')
    def _ser_money(self, value, _info):
        return _money_str(value)

    class Config:
        from_attributes = True


class PaginatedOrdersOut(BaseModel):
    """Matches the envelope every other list endpoint in this app returns
    (PaginatedInvoiceOut, email logs, products), so the frontend's pagination
    controls work the same way here."""

    items: list[OrderOut]
    total: int
    page: int
    page_size: int
    total_pages: int


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

class SyncResultOut(BaseModel):
    company_id: int | None = None
    ran: bool = False
    # False when another drain held the lock — not an error, just a no-op.
    locked: bool = False
    events_fetched: int = 0
    events_applied: int = 0
    events_ignored: int = 0
    events_skipped: int = 0
    posted: int = 0
    posting_failed: int = 0
    resynced: bool = False
    cursor: int = 0
    error: str | None = None


class SyncAllResultOut(BaseModel):
    results: list[SyncResultOut] = Field(default_factory=list)
