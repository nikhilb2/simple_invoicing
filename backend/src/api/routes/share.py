"""Authenticated management of public share links.

Owners mint, list and revoke links here. The links themselves are served by
``src.api.routes.public_share``, which requires no authentication at all.

Every route is ``include_in_schema=False``. That is not cosmetic: the MCP registry
generates a callable tool from every operation in ``app.openapi()``
(``src/mcp_server/registry.py``), and "mint a public unauthenticated URL for this
invoice" is not an action an LLM should be able to take on a user's behalf without
them going through the UI.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user
from src.core.config import settings
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.share_link import ShareLink
from src.models.user import User
from src.schemas.share import ShareLinkCreate, ShareLinkOut
from src.services.share_documents import (
    RESOURCE_INVOICE,
    RESOURCE_PAYMENT,
    RESOURCE_STATEMENT,
    generate_token,
    get_invoice,
    get_ledger,
    get_payment,
)

router = APIRouter()


def build_share_url(request: Request, token: str) -> str:
    """Absolute URL for a share token.

    ``PUBLIC_APP_BASE_URL`` is only trusted when it is already an https origin. It
    defaults to ``http://localhost:5173`` and several tenants (rudra, wf) never set
    it, so trusting it blindly would paste a localhost URL into a customer's
    WhatsApp thread. When it is not usable we derive the origin from the request
    the owner's own browser just made, which is by definition the right host.
    """
    configured = (settings.PUBLIC_APP_BASE_URL or "").strip().rstrip("/")
    if configured.startswith("https://"):
        return f"{configured}/s/{token}"

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    scheme = forwarded_proto or request.url.scheme
    host = (request.headers.get("host") or "").strip() or request.url.netloc
    return f"{scheme}://{host}/s/{token}"


def _to_out(link: ShareLink, url: str) -> ShareLinkOut:
    return ShareLinkOut(
        id=link.id,
        token=link.token,
        url=url,
        resource_type=link.resource_type,
        resource_id=link.resource_id,
        from_date=link.from_date,
        to_date=link.to_date,
        view_count=link.view_count or 0,
        last_viewed_at=link.last_viewed_at,
        created_at=link.created_at,
    )


def _require_enabled() -> None:
    if not settings.SHARE_LINKS_ENABLED:
        raise HTTPException(status_code=403, detail="Public share links are disabled")


def _validate_resource(db: Session, company_id: int, payload: ShareLinkCreate) -> None:
    """404 unless the resource exists *inside this company*.

    This is the tenant boundary at mint time; ``public_share`` enforces the same
    boundary at read time by filtering every query on the link's own ``company_id``.
    """
    if payload.resource_type == RESOURCE_INVOICE:
        if get_invoice(db, company_id, payload.resource_id) is None:
            raise HTTPException(status_code=404, detail=f"Invoice {payload.resource_id} not found")
        return

    if payload.resource_type == RESOURCE_STATEMENT:
        if payload.from_date is None or payload.to_date is None:
            raise HTTPException(status_code=400, detail="from_date and to_date are required for a statement link")
        if payload.from_date > payload.to_date:
            raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")
        if get_ledger(db, company_id, payload.resource_id) is None:
            raise HTTPException(status_code=404, detail=f"Ledger {payload.resource_id} not found")
        return

    if payload.resource_type == RESOURCE_PAYMENT:
        if get_payment(db, company_id, payload.resource_id) is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        return

    raise HTTPException(status_code=400, detail="Unsupported resource_type")


def _live_link_query(db: Session, company_id: int, resource_type: str, resource_id: int):
    return (
        db.query(ShareLink)
        .filter(
            ShareLink.company_id == company_id,
            ShareLink.resource_type == resource_type,
            ShareLink.resource_id == resource_id,
            ShareLink.revoked_at.is_(None),
        )
    )


@router.post("/", response_model=ShareLinkOut, include_in_schema=False)
def create_share_link(
    payload: ShareLinkCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    _require_enabled()
    company_id = active_company.id
    _validate_resource(db, company_id, payload)

    from_date = payload.from_date if payload.resource_type == RESOURCE_STATEMENT else None
    to_date = payload.to_date if payload.resource_type == RESOURCE_STATEMENT else None

    # Idempotent by design: "Share" is a button a user presses twice. Minting a
    # second live token for the same document would leave two URLs in circulation
    # and make "revoke" only half work.
    existing = (
        _live_link_query(db, company_id, payload.resource_type, payload.resource_id)
        .filter(ShareLink.from_date == from_date, ShareLink.to_date == to_date)
        .first()
    )
    if existing is not None:
        return _to_out(existing, build_share_url(request, existing.token))

    link = ShareLink(
        company_id=company_id,
        token=generate_token(),
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        from_date=from_date,
        to_date=to_date,
        view_count=0,
        created_by_user_id=getattr(current_user, "id", None),
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent mint (or hit the partial unique index).
        # The other writer's link is just as good as ours.
        db.rollback()
        existing = (
            _live_link_query(db, company_id, payload.resource_type, payload.resource_id)
            .filter(ShareLink.from_date == from_date, ShareLink.to_date == to_date)
            .first()
        )
        if existing is None:
            raise HTTPException(status_code=500, detail="Could not create share link")
        return _to_out(existing, build_share_url(request, existing.token))

    db.refresh(link)
    return _to_out(link, build_share_url(request, link.token))


@router.get("/", response_model=list[ShareLinkOut], include_in_schema=False)
def list_share_links(
    request: Request,
    resource_type: str | None = Query(default=None),
    # Typed as str, not int: a UI that renders `?resource_id=${id}` before the id
    # has loaded sends an empty string, and a 422 there is a worse answer than an
    # unfiltered list.
    resource_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    query = db.query(ShareLink).filter(
        ShareLink.company_id == active_company.id,
        ShareLink.revoked_at.is_(None),
    )
    if resource_type:
        query = query.filter(ShareLink.resource_type == resource_type)
    if resource_id:
        try:
            query = query.filter(ShareLink.resource_id == int(resource_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="resource_id must be an integer")

    links = query.order_by(ShareLink.id.desc()).all()
    return [_to_out(link, build_share_url(request, link.token)) for link in links]


@router.delete("/{link_id}", status_code=204, include_in_schema=False)
def revoke_share_link(
    link_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    link = (
        db.query(ShareLink)
        .filter(ShareLink.id == link_id, ShareLink.company_id == active_company.id)
        .first()
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Share link not found")

    # Never hard-delete: the row is the audit trail of what was shared, with whom
    # the token ended up, and how many times it was opened.
    if link.revoked_at is None:
        link.revoked_at = datetime.utcnow()
        db.commit()

    return Response(status_code=204)
