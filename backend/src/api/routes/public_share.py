"""Public, unauthenticated share pages.

Mounted at the origin root (``/s/...``) and again under ``/api/s/...``. Every route
is ``include_in_schema=False``: ``src/mcp_server/registry.py`` turns each OpenAPI
operation into a callable MCP tool, and these must never become one.

The tenant boundary
-------------------
Nothing here depends on ``get_current_user`` or ``get_active_company``. The
``company_id`` comes from the ``ShareLink`` row and every downstream query filters
on it, exactly as the authenticated routes filter on ``active_company.id``. That is
the single rule that stops a token minted in one tenant from reaching another
tenant's documents; ``tests/api/test_share_links.py`` asserts by introspection that
neither auth dependency is ever declared on these routes.
"""

from __future__ import annotations

import base64
import binascii
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from src.core.config import settings
from src.db.session import get_db
from src.models.share_link import ShareLink
from src.services.share_documents import (
    ShareSummary,
    build_share_summary,
    render_share_document_html,
    render_share_pdf,
    resolve_share_link,
)

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "services" / "share_templates"
# Autoescape ON. Company names, party names and document numbers are all
# user-supplied and are now being rendered to an audience outside the tenant.
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------

# Without X-Robots-Tag, a share URL that lands in a public Slack/forum gets
# crawled and shared invoices show up in Google. Referrer-Policy is not a nicety
# either: the ad block links out, and the default referrer policy would hand the
# full URL — token and all — to the ad destination in the Referer header.
_PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

# The page needs no JavaScript whatsoever, so say so and let the browser enforce it.
_HTML_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
)


def _html_headers() -> dict[str, str]:
    return {**_PUBLIC_HEADERS, "Content-Security-Policy": _HTML_CSP}


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# In-process token bucket, PER REPLICA — two pods means two buckets and twice the
# allowance. That is fine for what this is: WeasyPrint rendering is expensive
# enough that an unauthenticated URL triggering it is a cheap DoS lever, and this
# raises the cost of pulling it without pretending to be a real distributed limit.
_RATE_CAPACITY = 60.0
_RATE_REFILL_PER_SECOND = 1.0
_RATE_MAX_TRACKED_IPS = 20_000

_rate_buckets: dict[str, tuple[float, float]] = {}
_rate_lock = threading.Lock()


def reset_rate_limits() -> None:
    """Test hook — the buckets are module state and must not leak between tests."""
    with _rate_lock:
        _rate_buckets.clear()


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request) -> bool:
    ip = _client_ip(request)
    now = time.monotonic()
    with _rate_lock:
        if len(_rate_buckets) > _RATE_MAX_TRACKED_IPS:
            _rate_buckets.clear()
        tokens, last = _rate_buckets.get(ip, (_RATE_CAPACITY, now))
        tokens = min(_RATE_CAPACITY, tokens + (now - last) * _RATE_REFILL_PER_SECOND)
        if tokens < 1.0:
            _rate_buckets[ip] = (tokens, now)
            return True
        _rate_buckets[ip] = (tokens - 1.0, now)
        return False


def _too_many_requests() -> Response:
    return Response(
        content="Too many requests",
        status_code=429,
        media_type="text/plain; charset=utf-8",
        headers={**_PUBLIC_HEADERS, "Retry-After": "60"},
    )


# ---------------------------------------------------------------------------
# Uniform not-found
# ---------------------------------------------------------------------------

def _not_found() -> Response:
    """One body for every miss.

    Unknown token, revoked token, deleted document — all identical. A different
    status or body for "revoked" would confirm to a scanner that the token was
    once real, which is exactly the signal a scanner is looking for.
    """
    return Response(
        content="Not found",
        status_code=404,
        media_type="text/plain; charset=utf-8",
        headers=dict(_PUBLIC_HEADERS),
    )


# ---------------------------------------------------------------------------
# View counting
# ---------------------------------------------------------------------------

# Every one of these fetches the page to draw a preview card in a chat. Counting
# those would make "opened 3 times" mean "forwarded to 3 chats", which is worse
# than useless when the owner is using the number to decide whether to chase a
# payment.
_CRAWLER_USER_AGENTS = (
    "whatsapp",
    "facebookexternalhit",
    "telegrambot",
    "twitterbot",
    "slackbot",
)


def _is_crawler(request: Request) -> bool:
    ua = (request.headers.get("user-agent") or "").lower()
    return any(marker in ua for marker in _CRAWLER_USER_AGENTS)


def _record_view(db: Session, link: ShareLink) -> None:
    from datetime import datetime

    link.view_count = (link.view_count or 0) + 1
    link.last_viewed_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _origin(request: Request) -> str:
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    scheme = forwarded_proto or request.url.scheme
    host = (request.headers.get("host") or "").strip() or request.url.netloc
    return f"{scheme}://{host}"


def _base_path(request: Request) -> str:
    """The path this page was served from, minus any trailing slash.

    Derived from the request rather than hardcoded, because the router is mounted
    twice — at ``/s`` and at ``/api/s`` — and the page's own links have to stay on
    whichever mount the recipient actually reached.
    """
    return request.url.path.rstrip("/")


# Campaign tags on the ad's outbound link. This page sends
# `Referrer-Policy: no-referrer` and marks the link `rel="noreferrer"` on purpose,
# so the share token never reaches the marketing site in a Referer header — which
# also means simpleinvoicings.com would otherwise log every one of these arrivals
# as direct traffic. These tags are the only thing that identifies a visitor who
# came from a shared document; utm_content says which kind of document it was.
_AD_UTM = (
    ("utm_source", "share_page"),
    ("utm_medium", "referral"),
    ("utm_campaign", "document_share"),
)


def _tag_ad_website(website: str, placement: str) -> str:
    """`website` with the campaign tags appended, preserving any query it has."""
    if not website:
        return ""

    parts = urlsplit(website)
    query = parse_qsl(parts.query, keep_blank_values=True)
    # A deployment that already points SHARE_AD_WEBSITE at a tagged URL keeps its
    # own tags rather than carrying two conflicting utm_sources.
    if any(key.startswith("utm_") for key, _ in query):
        return website

    query.extend(_AD_UTM)
    query.append(("utm_content", placement))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _split_domain_label(label: str) -> tuple[str, str, str]:
    """Splits ``simpleinvoicings.com`` into ``("simpleinvoicing", "s", ".com")``.

    The middle piece is the one the panel flashes. The trailing "s" is the
    character people drop when they type the domain from memory, so the panel
    animates exactly that one letter and nothing else.

    A domain whose name does not end in "s" comes back as ``(label, "", "")`` and
    renders as flat text — a white-label deployment gets no stray animation
    drawing the eye to an ordinary letter.
    """
    name, dot, rest = label.partition(".")
    if not dot or not name.endswith("s"):
        return label, "", ""
    return name[:-1], name[-1], f".{rest}"


def _ad_context(placement: str) -> dict:
    """Everything the Simple Invoicings block renders.

    `placement` is what the reader was looking at — the resource type, or
    "unavailable" on the dead-link page — and rides out on the link as
    `utm_content`, so the marketing site can tell an invoice recipient from a
    statement recipient.

    Every field degrades independently: blank the phone and that button goes,
    blank the chips and the row goes, blank the price and that line goes, blank
    the website and the whole "powered by" line goes. A half-configured
    deployment therefore shows less, never something broken.
    """
    website = (settings.SHARE_AD_WEBSITE or "").strip()
    # The visible label is the bare domain, so it is taken before the tags go on.
    label = website.replace("https://", "").replace("http://", "").rstrip("/")
    label = label or website
    domain_head, domain_flash, domain_tail = _split_domain_label(label)
    phone = (settings.SHARE_AD_PHONE or "").strip()
    wa = "".join(ch for ch in (settings.SHARE_AD_WHATSAPP or "") if ch.isdigit())
    chips = [c.strip() for c in (settings.SHARE_AD_CHIPS or "").split(",") if c.strip()]
    return {
        "enabled": bool(settings.SHARE_AD_ENABLED),
        "brand_name": settings.SHARE_AD_BRAND_NAME,
        "headline": settings.SHARE_AD_HEADLINE,
        "tagline": settings.SHARE_AD_TAGLINE,
        "website": _tag_ad_website(website, placement),
        "website_label": label,
        # The label again, cut into the three pieces the "powered by" line sets
        # separately. Kept beside the whole label so anything that just wants
        # the domain as text still has it.
        "domain_head": domain_head,
        "domain_flash": domain_flash,
        "domain_tail": domain_tail,
        "chips": chips,
        "cta_label": settings.SHARE_AD_CTA_LABEL,
        "footnote": settings.SHARE_AD_FOOTNOTE,
        "price": (settings.SHARE_AD_PRICE or "").strip(),
        "price_period": (settings.SHARE_AD_PRICE_PERIOD or "").strip(),
        "price_prefix": (settings.SHARE_AD_PRICE_PREFIX or "").strip(),
        "phone": phone,
        # tel: wants no spaces; the visible label keeps them.
        "phone_href": "".join(ch for ch in phone if ch.isdigit() or ch == "+"),
        "whatsapp_url": f"https://wa.me/{wa}" if wa else "",
    }


def _captions(link: ShareLink) -> tuple[str, str, str]:
    """(party label, date label, amount label) for the summary card."""
    if link.resource_type == "ledger_statement":
        return "Account", "Period", "Closing balance"
    if link.resource_type == "payment":
        return "Party", "Date", "Amount"
    return "Billed to", "Date", "Total"


def _render_unavailable(request: Request) -> HTMLResponse:
    """The one page a human sees for every miss on the landing route.

    Unknown token, revoked link, deleted row and cancelled document all render
    THIS, byte for byte, with the same 404. Indistinguishable to a scanner, and
    a real customer whose link was withdrawn gets a sentence they can act on
    instead of a raw "Not found" — the plain-text `_not_found()` is kept for the
    sub-resources (pdf, logo, document.html), which nobody lands on directly.
    """
    html = _jinja_env.get_template("share_unavailable.html").render(
        page_title="Document unavailable",
        ad=_ad_context("unavailable"),
    )
    return HTMLResponse(content=html, status_code=404, headers=_html_headers())


def _resolve(db: Session, token: str) -> ShareLink | None:
    if not settings.SHARE_LINKS_ENABLED:
        return None
    return resolve_share_link(db, token)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/s/{token}", include_in_schema=False)
def public_share_page(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if _rate_limited(request):
        return _too_many_requests()

    link = _resolve(db, token)
    if link is None:
        return _render_unavailable(request)

    summary: ShareSummary | None = build_share_summary(db, link)
    if summary is None:
        # Dangling: the document row is gone. Same answer as an unknown token.
        return _render_unavailable(request)

    # Counted here and ONLY here. The PDF route is hit again by the download
    # button, so counting it there would multiply every real open.
    if not _is_crawler(request):
        _record_view(db, link)

    if not summary.available:
        return _render_unavailable(request)

    base = _base_path(request)
    origin = _origin(request)
    party_caption, date_caption, amount_caption = _captions(link)

    description_parts = [p for p in (summary.party_name, summary.amount_label, summary.date_label) if p]

    html = _jinja_env.get_template("share_document.html").render(
        page_title=f"{summary.title} · {summary.company_name}".strip(" ·"),
        summary=summary,
        party_label=party_caption,
        date_label_caption=date_caption,
        amount_caption=amount_caption,
        download_url=f"{base}/pdf?download=1",
        # No document_url or logo_url: the page no longer embeds the document or
        # draws the sender's logo. Both routes still answer on their own — the
        # logo is what a chat app fetches for the og:image below.
        og={
            "site_name": summary.company_name or "Simple Invoicing",
            "title": f"{summary.title} · {summary.company_name}".strip(" ·"),
            "description": " · ".join(description_parts),
            "url": f"{origin}{base}",
            # Absolute, because a crawler will not resolve a relative og:image.
            "image": f"{origin}{base}/logo" if summary.logo_data else None,
        },
        ad=_ad_context(link.resource_type),
    )
    return HTMLResponse(content=html, headers=_html_headers())


@router.get("/s/{token}/pdf", include_in_schema=False)
def public_share_pdf(
    token: str,
    request: Request,
    download: int = Query(default=0),
    db: Session = Depends(get_db),
) -> Response:
    if _rate_limited(request):
        return _too_many_requests()

    link = _resolve(db, token)
    if link is None:
        return _not_found()

    summary = build_share_summary(db, link)
    if summary is None or not summary.available:
        return _not_found()

    buf = render_share_pdf(db, link)

    disposition = "attachment" if download else "inline"
    headers = {
        **_PUBLIC_HEADERS,
        "Content-Disposition": f'{disposition}; filename="{summary.pdf_filename}"',
    }
    # NOTE: no view counting here. See public_share_page.
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)


@router.get("/s/{token}/document.html", include_in_schema=False)
def public_share_document_html(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """The print-styled document as HTML.

    No longer embedded anywhere — the share page dropped its inline preview —
    but still served: it is the one way to read the document itself without
    downloading a PDF, and links to it are already in circulation.
    """
    if _rate_limited(request):
        return _too_many_requests()

    link = _resolve(db, token)
    if link is None:
        return _not_found()

    summary = build_share_summary(db, link)
    if summary is None or not summary.available:
        return _not_found()

    html = render_share_document_html(db, link)
    return HTMLResponse(content=html, headers=_html_headers())


@router.get("/s/{token}/logo", include_in_schema=False)
def public_share_logo(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """The company logo, so ``og:image`` has something real to point at.

    Crawlers will not render a data: URI in an og:image, which is why the logo
    needs a URL of its own rather than being inlined like it is in the PDF.
    """
    if _rate_limited(request):
        return _too_many_requests()

    link = _resolve(db, token)
    if link is None:
        return _not_found()

    summary = build_share_summary(db, link)
    if summary is None or not summary.available or not summary.logo_data:
        return _not_found()

    try:
        raw = base64.b64decode(summary.logo_data, validate=False)
    except (binascii.Error, ValueError):
        return _not_found()
    if not raw:
        return _not_found()

    mime = (summary.logo_mime_type or "").strip().lower()
    if not mime.startswith("image/"):
        mime = "image/png"

    return Response(content=raw, media_type=mime, headers=dict(_PUBLIC_HEADERS))
