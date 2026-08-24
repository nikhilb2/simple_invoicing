"""Instance-side marketplace API.

The browser never talks to the central server directly — that would leak the
credential into the page and break CORS on every self-hosted deployment. Every
outbound call is proxied through these handlers.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user, require_roles
from src.core.validation import normalize_gstin
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.marketplace import (
    MarketplaceConnection,
    MarketplaceListing,
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplaceProductLink,
)
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.marketplace import (
    BrowseResultOut,
    ConnectionOut,
    ConnectionRegisterIn,
    ConnectionUpdateIn,
    ListingCreateIn,
    ListingOut,
    ListingUpdateIn,
    MarketplaceMetaOut,
    OrderCreateIn,
    OrderLinkProductIn,
    OrderOut,
    PaginatedOrdersOut,
    OrderRejectIn,
    SyncAllResultOut,
    SyncResultOut,
)
from src.services.marketplace import listings as listings_service
from src.services.marketplace import posting as posting_service
from src.services.marketplace import sync as sync_service
from src.services.marketplace.client import (
    CLIENT_VERSION,
    MarketplaceAuthError,
    MarketplaceConflict,
    MarketplaceError,
    MarketplaceUnavailable,
    build_client,
    client_for_connection,
)

router = APIRouter()

_MUTATOR_ROLES = (UserRole.admin, UserRole.manager)


def _http(exc: MarketplaceError) -> HTTPException:
    """Map the client's normalised exceptions onto HTTP status codes."""
    if isinstance(exc, MarketplaceAuthError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, MarketplaceConflict):
        return HTTPException(status_code=409, detail={"error": exc.code, "detail": str(exc)})
    if isinstance(exc, MarketplaceUnavailable):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _get_connection(db: Session, company_id: int) -> MarketplaceConnection | None:
    return (
        db.query(MarketplaceConnection)
        .filter(MarketplaceConnection.company_id == company_id)
        .first()
    )


def _require_connection(db: Session, company_id: int) -> MarketplaceConnection:
    connection = _get_connection(db, company_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="No marketplace connection configured")
    return connection


def _to_listing_out(listing: MarketplaceListing) -> ListingOut:
    return ListingOut.model_validate(listing)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@router.get("/connection", response_model=ConnectionOut | None)
def get_connection(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _get_connection(db, active_company.id)
    return ConnectionOut.model_validate(connection) if connection else None


@router.get("/connection/meta", response_model=MarketplaceMetaOut)
def get_marketplace_meta(
    base_url: str = Query(...),
    _: User = Depends(require_roles(UserRole.admin)),
    __: CompanyProfile = Depends(get_active_company),
):
    """Validate a pasted base URL before attempting registration."""
    try:
        with build_client(base_url) as client:
            return MarketplaceMetaOut(**(client.get_meta() or {}))
    except MarketplaceError as exc:
        raise _http(exc) from exc


@router.post("/connection", response_model=ConnectionOut, status_code=201)
def register_connection(
    payload: ConnectionRegisterIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Register this company with a marketplace as a seller.

    The credential is issued exactly once and never retrievable, so it is stored
    Fernet-encrypted the moment it arrives and never returned to the browser.
    """
    existing = _get_connection(db, active_company.id)
    if existing is not None and existing.status not in ("unregistered", "disconnected"):
        raise HTTPException(status_code=409, detail="This company is already registered")

    try:
        gstin = normalize_gstin(active_company.gst)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not gstin:
        raise HTTPException(
            status_code=400,
            detail="Set a valid GSTIN on this company before registering",
        )

    instance_uuid = (existing.instance_uuid if existing else None) or str(uuid.uuid4())

    connection = existing or MarketplaceConnection(company_id=active_company.id)
    connection.base_url = payload.base_url
    connection.gstin = gstin
    connection.instance_uuid = instance_uuid
    connection.display_name = payload.legal_name or active_company.name
    connection.created_by_user_id = current_user.id
    if existing is None:
        db.add(connection)
    db.flush()

    body = {
        "gstin": gstin,
        "legal_name": payload.legal_name or active_company.name,
        "address": payload.address or active_company.address,
        "state_code": payload.state_code or gstin[:2],
        "contact_email": payload.contact_email or active_company.email,
        "contact_phone": payload.contact_phone or active_company.phone_number,
        "instance_id": instance_uuid,
        "client_version": CLIENT_VERSION,
    }

    try:
        with build_client(payload.base_url) as client:
            response = client.register_seller(body)
    except MarketplaceError as exc:
        db.rollback()
        raise _http(exc) from exc

    connection.remote_seller_id = response.get("seller_id")
    connection.credential = response.get("api_key")
    remote_status = response.get("status") or "pending_approval"
    connection.status = "connected" if remote_status == "active" else "pending_approval"
    connection.registered_at = datetime.utcnow()
    connection.last_sync_error = None
    db.commit()
    db.refresh(connection)
    return ConnectionOut.model_validate(connection)


@router.patch("/connection", response_model=ConnectionOut)
def update_connection(
    payload: ConnectionUpdateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    if payload.auto_accept is not None:
        connection.auto_accept = payload.auto_accept
    if payload.auto_accept_max_amount is not None:
        connection.auto_accept_max_amount = Decimal(str(payload.auto_accept_max_amount))
    if payload.auto_post is not None:
        connection.auto_post = payload.auto_post
    if payload.display_name is not None:
        connection.display_name = payload.display_name
    db.commit()
    db.refresh(connection)
    return ConnectionOut.model_validate(connection)


@router.delete("/connection", response_model=dict)
def delete_connection(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    if connection.credential:
        try:
            with client_for_connection(connection) as client:
                client.delete_me()
        except MarketplaceError:
            # Local disconnect must succeed even when the server is unreachable.
            pass
    connection.status = "disconnected"
    connection.credential = None
    db.commit()
    return {"detail": "Disconnected from the marketplace"}


@router.post("/connection/rotate-key", response_model=ConnectionOut)
def rotate_key(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    try:
        with client_for_connection(connection) as client:
            response = client.rotate_key()
    except MarketplaceError as exc:
        raise _http(exc) from exc
    new_key = response.get("api_key")
    if not new_key:
        raise HTTPException(status_code=502, detail="Marketplace returned no new key")
    connection.credential = new_key
    db.commit()
    db.refresh(connection)
    return ConnectionOut.model_validate(connection)


# ---------------------------------------------------------------------------
# Browse — proxied
# ---------------------------------------------------------------------------

@router.get("/catalog", response_model=BrowseResultOut)
def browse(
    q: str | None = None,
    hsn_sac: str | None = None,
    gst_rate: float | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    seller_state_code: str | None = None,
    in_stock: bool | None = None,
    sort: str | None = None,
    cursor: str | None = None,
    page_size: int = Query(50, le=100, ge=1),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    try:
        with client_for_connection(connection) as client:
            body = client.browse(
                q=q,
                hsn_sac=hsn_sac,
                gst_rate=gst_rate,
                min_price=min_price,
                max_price=max_price,
                seller_state_code=seller_state_code,
                in_stock=in_stock,
                exclude_own=True,
                sort=sort,
                cursor=cursor,
                page_size=page_size,
            )
    except MarketplaceError as exc:
        raise _http(exc) from exc
    return BrowseResultOut(**body)


@router.get("/catalog/{listing_id}", response_model=dict)
def browse_detail(
    listing_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    try:
        with client_for_connection(connection) as client:
            return client.get_listing(listing_id)
    except MarketplaceError as exc:
        raise _http(exc) from exc


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

@router.get("/listings", response_model=list[ListingOut])
def list_listings(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    query = db.query(MarketplaceListing).filter(
        MarketplaceListing.company_id == active_company.id
    )
    if status:
        query = query.filter(MarketplaceListing.status == status)
    return [
        _to_listing_out(listing)
        for listing in query.order_by(MarketplaceListing.id.desc()).all()
    ]


@router.post("/listings", response_model=ListingOut, status_code=201)
def create_listing(
    payload: ListingCreateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    product = (
        db.query(Product)
        .filter(
            Product.id == payload.product_id,
            or_(Product.company_id == active_company.id, Product.company_id.is_(None)),
        )
        .first()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = (
        db.query(MarketplaceListing)
        .filter(
            MarketplaceListing.company_id == active_company.id,
            MarketplaceListing.product_id == product.id,
            MarketplaceListing.status != "withdrawn",
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This product is already listed")

    listing = listings_service.build_listing(db, connection, product, payload)
    available = (
        Decimal(str(payload.available_quantity))
        if payload.available_quantity is not None
        else None
    )
    try:
        listings_service.publish_listing(
            db, connection, listing, client_for_connection(connection),
            available_quantity=available,
        )
    except MarketplaceError as exc:
        raise _http(exc) from exc
    db.refresh(listing)
    return _to_listing_out(listing)


@router.patch("/listings/{listing_id}", response_model=ListingOut)
def patch_listing(
    listing_id: int,
    payload: ListingUpdateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    listing = (
        db.query(MarketplaceListing)
        .filter(
            MarketplaceListing.id == listing_id,
            MarketplaceListing.company_id == active_company.id,
        )
        .first()
    )
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        listings_service.update_listing(
            db, connection, listing, payload, client_for_connection(connection)
        )
    except MarketplaceError as exc:
        raise _http(exc) from exc
    db.refresh(listing)
    return _to_listing_out(listing)


@router.delete("/listings/{listing_id}", response_model=dict)
def delete_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    listing = (
        db.query(MarketplaceListing)
        .filter(
            MarketplaceListing.id == listing_id,
            MarketplaceListing.company_id == active_company.id,
        )
        .first()
    )
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        listings_service.withdraw_listing(
            db, connection, listing, client_for_connection(connection)
        )
    except MarketplaceError as exc:
        raise _http(exc) from exc
    return {"detail": "Listing withdrawn"}


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def _order_query(db: Session, company_id: int):
    return db.query(MarketplaceOrder).filter(MarketplaceOrder.company_id == company_id)


def _to_order_out(db: Session, order: MarketplaceOrder) -> OrderOut:
    """Resolve the posted invoice's NUMBER alongside its id.

    The UI links to the invoice either way, but a user recognises
    "INV-2026-27-000042", not a row id — and the number is what they will be
    searching their own books for.
    """
    result = OrderOut.model_validate(order)
    if order.posted_invoice_id is not None:
        number = (
            db.query(Invoice.invoice_number)
            .filter(Invoice.id == order.posted_invoice_id)
            .scalar()
        )
        result.posted_invoice_number = number
    return result


@router.get("/orders", response_model=PaginatedOrdersOut)
def list_orders(
    side: str | None = None,
    state: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    query = _order_query(db, active_company.id)
    if side:
        query = query.filter(MarketplaceOrder.side == side)
    if state:
        query = query.filter(MarketplaceOrder.state == state)

    total = query.count()
    rows = (
        query.order_by(MarketplaceOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedOrdersOut(
        items=[_to_order_out(db, order) for order in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    order = _order_query(db, active_company.id).filter(MarketplaceOrder.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return _to_order_out(db, order)


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(
    payload: OrderCreateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Buy now. The response is mirrored locally straight away — the divergence
    check on the later order.posted event compares against exactly this."""
    connection = _require_connection(db, active_company.id)
    try:
        with client_for_connection(connection) as client:
            response = client.create_order(
                {
                    "listing_id": payload.listing_id,
                    "quantity": str(Decimal(str(payload.quantity))),
                    "buyer_note": payload.buyer_note,
                    "delivery_address": payload.delivery_address,
                }
            )
    except MarketplaceError as exc:
        raise _http(exc) from exc

    order = sync_service.upsert_order_from_snapshot(db, connection, response, "buy")
    order.state = response.get("state") or "pending"
    order.posting_state = "not_required"
    db.commit()
    db.refresh(order)
    return _to_order_out(db, order)


def _load_order(db: Session, company_id: int, order_id: int) -> MarketplaceOrder:
    order = _order_query(db, company_id).filter(MarketplaceOrder.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/orders/{order_id}/accept", response_model=OrderOut)
def accept_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    order = _load_order(db, active_company.id, order_id)
    if order.side != "sell" or order.state != "pending":
        raise HTTPException(status_code=409, detail=f"Cannot accept an order in state {order.state}")
    if not posting_service.seller_has_stock(db, connection, order):
        raise HTTPException(status_code=400, detail="Insufficient stock to fulfil this order")
    try:
        with client_for_connection(connection) as client:
            client.accept_order(order.remote_order_id)
    except MarketplaceError as exc:
        raise _http(exc) from exc
    order.state = "accepted"
    order.accepted_at = datetime.utcnow()
    order.posting_state = "pending"
    db.commit()
    db.refresh(order)
    return _to_order_out(db, order)


@router.post("/orders/{order_id}/reject", response_model=OrderOut)
def reject_order(
    order_id: int,
    payload: OrderRejectIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    order = _load_order(db, active_company.id, order_id)
    if order.side != "sell" or order.state != "pending":
        raise HTTPException(status_code=409, detail=f"Cannot reject an order in state {order.state}")
    try:
        with client_for_connection(connection) as client:
            client.reject_order(order.remote_order_id, payload.reason, payload.note)
    except MarketplaceError as exc:
        raise _http(exc) from exc
    order.state = "rejected"
    order.reject_reason = payload.reason
    order.reject_note = payload.note
    order.closed_at = datetime.utcnow()
    order.posting_state = "not_required"
    db.commit()
    db.refresh(order)
    return _to_order_out(db, order)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    order = _load_order(db, active_company.id, order_id)
    if order.side != "buy" or order.state != "pending":
        raise HTTPException(status_code=409, detail=f"Cannot cancel an order in state {order.state}")
    try:
        with client_for_connection(connection) as client:
            client.cancel_order(order.remote_order_id)
    except MarketplaceError as exc:
        raise _http(exc) from exc
    order.state = "cancelled"
    order.closed_at = datetime.utcnow()
    order.posting_state = "not_required"
    db.commit()
    db.refresh(order)
    return _to_order_out(db, order)


@router.post("/orders/{order_id}/retry-posting", response_model=OrderOut)
def retry_posting(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """The manual Retry behind a `failed` posting — and the only way to post at
    all while `auto_post` is off."""
    connection = _require_connection(db, active_company.id)
    order = _load_order(db, active_company.id, order_id)
    if order.posted_invoice_id is not None:
        raise HTTPException(status_code=409, detail="This order is already posted")
    if order.posting_state not in ("pending", "failed", "posting", "skipped"):
        raise HTTPException(
            status_code=409, detail=f"Nothing to post for state {order.posting_state}"
        )
    posting_service.post_order(db, connection, order.id, force=True)
    db.expire_all()
    order = _load_order(db, active_company.id, order_id)
    return _to_order_out(db, order)


@router.post("/orders/{order_id}/link-product", response_model=OrderOut)
def link_product(
    order_id: int,
    payload: OrderLinkProductIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*_MUTATOR_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Remap a remote listing onto an existing local product.

    Affects FUTURE orders only — posted accounting is never rewritten.
    """
    order = _load_order(db, active_company.id, order_id)
    product = (
        db.query(Product)
        .filter(
            Product.id == payload.product_id,
            or_(Product.company_id == active_company.id, Product.company_id.is_(None)),
        )
        .first()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    link = (
        db.query(MarketplaceProductLink)
        .filter(
            MarketplaceProductLink.company_id == active_company.id,
            MarketplaceProductLink.remote_listing_id == payload.remote_listing_id,
        )
        .first()
    )
    if link is None:
        link = MarketplaceProductLink(
            company_id=active_company.id,
            remote_listing_id=payload.remote_listing_id,
            product_id=product.id,
        )
        db.add(link)
    else:
        link.product_id = product.id

    if order.posting_state != "posted":
        db.query(MarketplaceOrderItem).filter(
            MarketplaceOrderItem.order_id == order.id,
            MarketplaceOrderItem.remote_listing_id == payload.remote_listing_id,
        ).update({"product_id": product.id}, synchronize_session=False)

    db.commit()
    db.refresh(order)
    return _to_order_out(db, order)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@router.post("/sync", response_model=SyncResultOut)
def sync_now(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    connection = _require_connection(db, active_company.id)
    return sync_service.drain(db, connection)


@router.post("/sync-all", response_model=SyncAllResultOut)
def sync_all(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Drain every connected company. Authenticated with the ordinary `si_` API
    key scheme so a crontab or CronJob can call it — the only path that works
    when nobody has the app open."""
    return SyncAllResultOut(results=sync_service.drain_all(db))
