"""Publishing local products to the marketplace and keeping them in step.

The published quantity is an advisory snapshot only — the seller's instance holds
the real stock and the accept-time check is the actual reservation. This module
just keeps the advisory number from drifting too far.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from src.models.inventory import Inventory
from src.models.marketplace import MarketplaceConnection, MarketplaceListing
from src.models.product import Product
from src.services.marketplace.client import MarketplaceError

logger = logging.getLogger(__name__)


def local_quantity(db: Session, company_id: int, product_id: int) -> Decimal:
    """Current local stock, preferring the tenant row over the global fallback."""
    row = (
        db.query(Inventory)
        .filter(
            Inventory.product_id == product_id,
            or_(Inventory.company_id == company_id, Inventory.company_id.is_(None)),
        )
        .order_by(case((Inventory.company_id == company_id, 0), else_=1))
        .first()
    )
    return Decimal(str(row.quantity or 0)) if row else Decimal("0")


def _wire_payload(listing: MarketplaceListing, available: Decimal | None) -> dict:
    """All money and quantity values go out as decimal strings — float
    round-tripping silently corrupts tax arithmetic (contract §1)."""
    payload = {
        "title": listing.title,
        "description": listing.description,
        "asking_price": str(Decimal(str(listing.asking_price or 0))),
        "currency_code": listing.currency_code or "INR",
        "gst_rate": str(Decimal(str(listing.gst_rate or 0))),
        "hsn_sac": listing.hsn_sac,
        "unit": listing.unit or "Pieces",
        "allow_decimal": bool(listing.allow_decimal),
        "listing_type": listing.listing_type or "buy_now",
        "external_ref": str(listing.product_id),
    }
    if listing.min_order_quantity is not None:
        payload["min_order_quantity"] = str(Decimal(str(listing.min_order_quantity)))
    if listing.max_order_quantity is not None:
        payload["max_order_quantity"] = str(Decimal(str(listing.max_order_quantity)))
    if available is not None:
        payload["available_quantity"] = str(available)
    return payload


def build_listing(
    db: Session,
    connection: MarketplaceConnection,
    product: Product,
    payload,
) -> MarketplaceListing:
    """Create the local listing row from a product plus the user's overrides.

    gst_rate/hsn_sac/unit come from the product master — they are what the buyer
    will book, so they must be the seller's real figures.
    """
    listing = MarketplaceListing(
        company_id=connection.company_id,
        product_id=product.id,
        title=(payload.title or product.name)[:255],
        description=payload.description or product.description,
        asking_price=Decimal(str(payload.asking_price)),
        currency_code="INR",
        gst_rate=Decimal(str(product.gst_rate or 0)),
        hsn_sac=product.hsn_sac,
        unit=product.unit or "Pieces",
        allow_decimal=bool(product.allow_decimal),
        min_order_quantity=(
            Decimal(str(payload.min_order_quantity))
            if payload.min_order_quantity is not None
            else None
        ),
        max_order_quantity=(
            Decimal(str(payload.max_order_quantity))
            if payload.max_order_quantity is not None
            else None
        ),
        listing_type=payload.listing_type or "buy_now",
        status="draft",
    )
    db.add(listing)
    db.flush()
    return listing


def publish_listing(
    db: Session,
    connection: MarketplaceConnection,
    listing: MarketplaceListing,
    client,
    *,
    available_quantity: Decimal | None = None,
) -> MarketplaceListing:
    """Push a draft listing to the marketplace and record the remote id."""
    if available_quantity is None:
        available_quantity = local_quantity(db, connection.company_id, listing.product_id)

    try:
        response = client.create_listing(_wire_payload(listing, available_quantity))
    except MarketplaceError as exc:
        listing.last_error = f"{exc.code}: {exc}"[:1000]
        db.commit()
        raise

    listing.remote_listing_id = response.get("listing_id")
    listing.status = response.get("status") or "active"
    listing.available_quantity_published = available_quantity
    listing.last_published_at = datetime.utcnow()
    listing.last_error = None
    db.commit()
    return listing


def update_listing(
    db: Session,
    connection: MarketplaceConnection,
    listing: MarketplaceListing,
    payload,
    client,
) -> MarketplaceListing:
    changes: dict = {}
    if payload.title is not None:
        listing.title = payload.title[:255]
        changes["title"] = listing.title
    if payload.description is not None:
        listing.description = payload.description
        changes["description"] = listing.description
    if payload.asking_price is not None:
        listing.asking_price = Decimal(str(payload.asking_price))
        changes["asking_price"] = str(listing.asking_price)
    if payload.min_order_quantity is not None:
        listing.min_order_quantity = Decimal(str(payload.min_order_quantity))
        changes["min_order_quantity"] = str(listing.min_order_quantity)
    if payload.max_order_quantity is not None:
        listing.max_order_quantity = Decimal(str(payload.max_order_quantity))
        changes["max_order_quantity"] = str(listing.max_order_quantity)
    if payload.available_quantity is not None:
        listing.available_quantity_published = Decimal(str(payload.available_quantity))
        changes["available_quantity"] = str(listing.available_quantity_published)
    if payload.status is not None:
        listing.status = payload.status
        changes["status"] = payload.status

    if changes and listing.remote_listing_id:
        try:
            client.update_listing(listing.remote_listing_id, changes)
            listing.last_error = None
            listing.last_published_at = datetime.utcnow()
        except MarketplaceError as exc:
            listing.last_error = f"{exc.code}: {exc}"[:1000]
            db.commit()
            raise
    db.commit()
    return listing


def withdraw_listing(
    db: Session,
    connection: MarketplaceConnection,
    listing: MarketplaceListing,
    client,
) -> None:
    """Soft withdrawal on both sides — the row stays so posted orders that
    reference the listing can still resolve their product."""
    if listing.remote_listing_id:
        try:
            client.delete_listing(listing.remote_listing_id)
        except MarketplaceError as exc:
            listing.last_error = f"{exc.code}: {exc}"[:1000]
            db.commit()
            raise
    listing.status = "withdrawn"
    db.commit()


def refresh_published_quantities(
    db: Session, connection: MarketplaceConnection, client, *, limit: int = 50
) -> int:
    """Republish the advisory quantity wherever local stock has drifted."""
    listings = (
        db.query(MarketplaceListing)
        .filter(
            MarketplaceListing.company_id == connection.company_id,
            MarketplaceListing.status == "active",
            MarketplaceListing.remote_listing_id.isnot(None),
        )
        .order_by(MarketplaceListing.id.asc())
        .limit(limit)
        .all()
    )

    refreshed = 0
    for listing in listings:
        current = local_quantity(db, connection.company_id, listing.product_id)
        published = listing.available_quantity_published
        if published is not None and Decimal(str(published)) == current:
            continue
        try:
            client.update_listing(
                listing.remote_listing_id, {"available_quantity": str(current)}
            )
        except MarketplaceError as exc:
            logger.warning(
                "marketplace: quantity refresh for %s failed: %s",
                listing.remote_listing_id,
                exc,
            )
            continue
        listing.available_quantity_published = current
        listing.last_published_at = datetime.utcnow()
        refreshed += 1
    db.commit()
    return refreshed
