"""Server-side PostHog product analytics.

Events are captured here, on the backend, rather than in the browser. The
browser only records replays now. That split is deliberate:

* An event fires when the write actually committed. A browser event fires when
  a request *appeared* to succeed, so a 500 swallowed by a retry, a tab closed
  mid-save or an ad blocker eating the ingestion request all skew the funnel.
* The same action performed through the MCP connector, the API keys or a script
  is counted identically, because it goes through the same route handler.
* Nothing about the product's event taxonomy ships in a public JS bundle.

Every export is a no-op until `POSTHOG_PROJECT_API_KEY` is set. An instance
running with no PostHog project configured -- a self-hosted copy, CI, a
contributor's checkout -- must boot and behave identically, and it does so
quietly: absent configuration is a supported state, not a fault.

Capture must never break a request. A tenant's invoice does not fail to save
because an analytics host is unreachable, so every entry point swallows its
own exceptions and logs at debug level.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Optional

from src.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_init_attempted = False

# Set per-request by AnalyticsSessionMiddleware from the headers the browser
# attaches. Carrying the replay's session id onto server-side events is what
# makes them appear on the recording's timeline -- without it the replay and
# the events it caused live in the same project but never line up.
_session_id: ContextVar[Optional[str]] = ContextVar("posthog_session_id", default=None)

# Which surface made the call. The old browser events carried a `source` naming
# the modal or page an action came from; a route handler cannot see that, and
# a replay answers it better anyway. What the server does know -- and the
# browser never did -- is whether an invoice was written by a person in the web
# app, by Claude through the MCP connector, or by a script holding an API key.
_client_kind: ContextVar[str] = ContextVar("posthog_client_kind", default="api")

# The caller's own IP, so PostHog can resolve where an event happened. Nothing
# else can: the client is constructed with `disable_geoip=True` because the
# address PostHog would otherwise see is this pod's, and a datacentre in
# Frankfurt is not where the invoice was written.
_client_ip: ContextVar[Optional[str]] = ContextVar("posthog_client_ip", default=None)


def _get_client():
    """Returns the PostHog client, or None when analytics is not configured."""
    global _client, _init_attempted

    if _init_attempted:
        return _client

    _init_attempted = True

    if not settings.POSTHOG_PROJECT_API_KEY:
        return None

    try:
        from posthog import Posthog

        _client = Posthog(
            settings.POSTHOG_PROJECT_API_KEY,
            host=settings.POSTHOG_HOST,
            # Events are queued and flushed by a background thread, so `capture`
            # returns immediately and a slow ingestion host cannot add latency to
            # an invoice save.
            sync_mode=False,
            # The server's IP is a datacentre, not the operator's location, so a
            # GeoIP lookup on it would attach confidently wrong geography to every
            # person. Better no country than the wrong one.
            disable_geoip=True,
        )
    except Exception:  # pragma: no cover - defensive: never break boot
        logger.debug("PostHog client could not be created; analytics disabled", exc_info=True)
        _client = None

    return _client


def is_analytics_ready() -> bool:
    """True once PostHog is configured and the client was created."""
    return _get_client() is not None


def bind_request(
    session_id: Optional[str],
    client_kind: str,
    client_ip: Optional[str] = None,
) -> None:
    """Binds the replay session, calling surface and caller IP to this request."""
    _session_id.set(session_id or None)
    _client_kind.set(client_kind)
    _client_ip.set(client_ip or None)


def client_ip_from_request(request) -> Optional[str]:
    """The caller's address, as close to the real one as this app can get.

    Behind an ingress the socket peer is the proxy, so the left-most
    `X-Forwarded-For` entry is the one that means anything. That entry is
    client-supplied and therefore spoofable -- a fabricated one buys nothing but
    a wrong dot on a map, and it is the same trust the rate limiter on the public
    share pages already places in the header.
    """
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else None


def _geo_properties() -> tuple[dict[str, Any], Optional[bool]]:
    """($ip property, per-event disable_geoip) for the request in scope.

    Returning `False` re-enables PostHog's GeoIP for this one event, overriding
    the client-wide default. The override and the address travel together on
    purpose: geolocation is only ever switched on for an event that carries a
    real caller IP, so a code path that forgets to bind one degrades to no
    location rather than to this server's location.
    """
    ip = _client_ip.get()
    if not ip:
        return {}, None
    return {"$ip": ip}, False


def client_kind_from_headers(headers) -> str:
    """Classifies the caller from its request headers.

    `X-MCP-Tool` is set by the MCP dispatcher on every tool call, and the
    PostHog session header is sent only by the SPA, so anything with neither is
    a script, an API key or curl.
    """
    if "X-MCP-Tool" in headers:
        return "mcp"
    if headers.get("X-PostHog-Session-Id"):
        return "web"
    return "api"


def distinct_id_for(user: Any) -> Optional[str]:
    """The identifier a person is keyed by.

    Email, matching what the browser passes to `posthog.identify`, so the replay
    recorded in the browser and the events recorded here land on one person.
    """
    email = getattr(user, "email", None)
    return email or None


def track(
    event: str,
    distinct_id: Optional[str],
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """Records a product event.

    Property values are deliberately limited to counts, ids, enums and money
    totals -- never customer names, addresses, item descriptions or anything
    else off a document. Aggregate shape is what the funnels need; the contents
    of a tenant's invoices are not ours to ship off-site.

    A call with no `distinct_id` is dropped rather than captured anonymously:
    an unattributable event only inflates counts.
    """
    client = _get_client()
    if client is None or not distinct_id:
        return

    payload = dict(properties or {})

    payload.setdefault("client", _client_kind.get())

    session_id = _session_id.get()
    if session_id:
        payload["$session_id"] = session_id

    geo, disable_geoip = _geo_properties()
    payload.update(geo)

    try:
        client.capture(
            event,
            distinct_id=distinct_id,
            properties=payload,
            disable_geoip=disable_geoip,
        )
    except Exception:
        logger.debug("PostHog capture failed for %s", event, exc_info=True)


def track_anonymous(
    event: str,
    group_key: str,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """Records an event by someone who is not a user of this app.

    A public share page is read by the tenant's customer, not by an operator.
    They have no account, and they must not acquire a PostHog person profile
    just for opening an invoice someone sent them, so these go out personless --
    `$process_person_profile` is what stops one being minted.

    `group_key` is a grouping key, not an identity. Pass a share link's numeric
    id, never its token: the token is the credential that opens the document,
    and it has no business sitting in an analytics payload.
    """
    payload = dict(properties or {})
    payload["$process_person_profile"] = False
    track(event, group_key, payload)


def set_person_properties(distinct_id: Optional[str], properties: dict[str, Any]) -> None:
    """Updates properties on a person without recording a product event."""
    client = _get_client()
    if client is None or not distinct_id:
        return

    try:
        client.set(distinct_id=distinct_id, properties=properties)
    except Exception:
        logger.debug("PostHog person update failed", exc_info=True)


def track_exception(
    exc: BaseException,
    distinct_id: Optional[str] = None,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """Reports an unhandled exception to PostHog error tracking.

    Unlike `track`, this captures with no distinct id when there is none. A
    request can blow up before anything has authenticated it, and an
    unattributed crash report is still worth having.
    """
    client = _get_client()
    if client is None:
        return

    payload = dict(properties or {})

    session_id = _session_id.get()
    if session_id:
        payload["$session_id"] = session_id

    geo, disable_geoip = _geo_properties()
    payload.update(geo)

    try:
        client.capture_exception(
            exc,
            distinct_id=distinct_id,
            properties=payload,
            disable_geoip=disable_geoip,
        )
    except Exception:
        logger.debug("PostHog exception capture failed", exc_info=True)


def shutdown_analytics() -> None:
    """Flushes anything still queued. Called on application shutdown."""
    client = _get_client()
    if client is None:
        return

    try:
        client.shutdown()
    except Exception:
        logger.debug("PostHog shutdown failed", exc_info=True)
