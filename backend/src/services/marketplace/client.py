"""The first outbound HTTP client in this backend, so it sets the convention.

Retry policy: 2 retries with 0.5 s then 1.5 s backoff, only on ConnectError /
ReadTimeout / 5xx / 429. Never on any other 4xx (they are deterministic), and
never on a POST that carries no Idempotency-Key — a retried un-keyed POST can
create a second order.

Errors are normalised to four exception types so route handlers map cleanly onto
502 / 401 / 409 / 502 without knowing anything about httpx.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

CLIENT_NAME = "respawn-invoicing"
CLIENT_VERSION = "0.1.0"

_RETRY_BACKOFF_SECONDS = (0.5, 1.5)
_RETRYABLE_STATUS = {429}


class MarketplaceError(Exception):
    """Base for every marketplace transport/protocol failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.payload = payload or {}


class MarketplaceUnavailable(MarketplaceError):
    """The central server could not be reached, or answered 5xx/429 after retries."""


class MarketplaceAuthError(MarketplaceError):
    """401/403 — the credential is dead or the seller is not approved."""


class MarketplaceConflict(MarketplaceError):
    """409 — a state-machine or cursor conflict the caller must interpret."""


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_base_url(base_url: str) -> str:
    """Validate a user-supplied marketplace base URL and return it normalised.

    The user pastes this URL and the *server* fetches it, so an unguarded value
    turns the instance into an SSRF proxy onto its own private network. Local
    development legitimately points at localhost, hence the escape hatch.
    """
    if not base_url or not base_url.strip():
        raise MarketplaceError("Marketplace URL is required", code="invalid_base_url")

    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)

    if parsed.scheme not in ("http", "https"):
        raise MarketplaceError(
            "Marketplace URL must start with http:// or https://", code="invalid_base_url"
        )
    if not parsed.hostname:
        raise MarketplaceError("Marketplace URL has no host", code="invalid_base_url")

    allow_insecure = bool(settings.MARKETPLACE_ALLOW_INSECURE_URL)

    if settings.ENVIRONMENT == "production" and parsed.scheme != "https" and not allow_insecure:
        raise MarketplaceError(
            "Marketplace URL must use https in production", code="insecure_base_url"
        )

    if allow_insecure:
        return normalized

    host = parsed.hostname.lower()
    if host in _BLOCKED_HOSTNAMES:
        raise MarketplaceError(
            "Marketplace URL may not point at a local or private address",
            code="blocked_base_url",
        )

    candidates: list[str] = []
    try:
        candidates.append(str(ipaddress.ip_address(host)))
    except ValueError:
        try:
            candidates = [info[4][0] for info in socket.getaddrinfo(host, None)]
        except OSError as exc:
            raise MarketplaceError(
                f"Could not resolve marketplace host {host}", code="unresolvable_base_url"
            ) from exc

    for candidate in candidates:
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise MarketplaceError(
                "Marketplace URL may not point at a local or private address",
                code="blocked_base_url",
            )

    return normalized


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MarketplaceClient:
    """Thin wrapper over ``httpx.Client`` speaking the ``/v1`` contract.

    ``transport`` is the entire test seam: tests pass an ``ASGITransport`` bound
    to the in-memory fake, or a ``MockTransport`` for retry/backoff assertions.
    """

    def __init__(
        self,
        base_url: str,
        credential: str | None = None,
        *,
        instance_uuid: str | None = None,
        transport: httpx.BaseTransport | None = None,
        validate_url: bool = True,
        sleep=time.sleep,
    ) -> None:
        if validate_url and transport is None:
            base_url = validate_base_url(base_url)
        else:
            base_url = (base_url or "").strip().rstrip("/")

        self.base_url = base_url
        self._sleep = sleep

        headers = {
            "Accept": "application/json",
            "X-Marketplace-Client": f"{CLIENT_NAME}/{CLIENT_VERSION}",
        }
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        if instance_uuid:
            headers["X-Marketplace-Instance"] = instance_uuid

        read_timeout = float(settings.MARKETPLACE_HTTP_TIMEOUT_SECONDS or 15)
        self._client = httpx.Client(
            base_url=f"{base_url}/v1",
            timeout=httpx.Timeout(connect=5.0, read=read_timeout, write=10.0, pool=5.0),
            transport=transport,
            headers=headers,
            follow_redirects=False,
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MarketplaceClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- request plumbing --------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        # A POST without an idempotency key is not safe to replay: the server has
        # no way to collapse the duplicate, so a retry can create a second order.
        retryable = method.upper() in ("GET", "HEAD") or idempotency_key is not None
        attempts = len(_RETRY_BACKOFF_SECONDS) + 1 if retryable else 1

        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self._client.request(
                    method, path, params=params, json=json, headers=headers or None
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_error = MarketplaceUnavailable(
                    f"Could not reach the marketplace: {exc}", code="unreachable"
                )
                if attempt < attempts - 1:
                    self._sleep(_RETRY_BACKOFF_SECONDS[attempt])
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                raise MarketplaceError(
                    f"Marketplace request failed: {exc}", code="transport_error"
                ) from exc

            status = response.status_code
            if status >= 500 or status in _RETRYABLE_STATUS:
                if attempt < attempts - 1:
                    self._sleep(self._retry_delay(response, attempt))
                    continue
                raise self._to_exception(response)

            if status >= 400:
                raise self._to_exception(response)

            return self._decode(response)

        raise last_error or MarketplaceUnavailable("Marketplace request failed")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                # Honour the server's own pacing when it bothers to state one, but
                # never stall a synchronous drain for minutes.
                return min(float(retry_after), 5.0)
            except ValueError:
                pass
        return _RETRY_BACKOFF_SECONDS[attempt]

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise MarketplaceError(
                "Marketplace returned a non-JSON response", code="bad_response"
            ) from exc

    @staticmethod
    def _to_exception(response: httpx.Response) -> MarketplaceError:
        status = response.status_code
        try:
            body = response.json()
            if not isinstance(body, dict):
                body = {}
        except ValueError:
            body = {}
        code = body.get("error") or f"http_{status}"
        detail = body.get("detail") or response.text[:200] or f"HTTP {status}"

        if status in (401, 403):
            return MarketplaceAuthError(detail, code=code, status_code=status, payload=body)
        if status == 409:
            return MarketplaceConflict(detail, code=code, status_code=status, payload=body)
        if status >= 500 or status == 429:
            return MarketplaceUnavailable(detail, code=code, status_code=status, payload=body)
        return MarketplaceError(detail, code=code, status_code=status, payload=body)

    # -- endpoints ---------------------------------------------------------

    def get_meta(self) -> dict:
        return self._request("GET", "/meta") or {}

    def get_health(self) -> dict:
        return self._request("GET", "/health") or {}

    def register_seller(self, payload: dict) -> dict:
        # Registration is un-keyed by contract; a retry could claim a second
        # credential, so it deliberately does not retry.
        return self._request("POST", "/sellers/register", json=payload) or {}

    def get_me(self) -> dict:
        return self._request("GET", "/sellers/me") or {}

    def patch_me(self, payload: dict) -> dict:
        return self._request("PATCH", "/sellers/me", json=payload) or {}

    def rotate_key(self) -> dict:
        return self._request("POST", "/sellers/me/rotate-key", json={}) or {}

    def delete_me(self) -> None:
        self._request("DELETE", "/sellers/me")

    # listings
    def create_listing(self, payload: dict) -> dict:
        return self._request("POST", "/listings", json=payload) or {}

    def update_listing(self, listing_id: str, payload: dict) -> dict:
        return self._request("PATCH", f"/listings/{listing_id}", json=payload) or {}

    def delete_listing(self, listing_id: str) -> None:
        self._request("DELETE", f"/listings/{listing_id}")

    def list_my_listings(self, **params) -> dict:
        return self._request("GET", "/listings/mine", params=_clean(params)) or {}

    def browse(self, **params) -> dict:
        return self._request("GET", "/listings", params=_clean(params)) or {}

    def get_listing(self, listing_id: str) -> dict:
        return self._request("GET", f"/listings/{listing_id}") or {}

    # orders
    def create_order(self, payload: dict, *, idempotency_key: str | None = None) -> dict:
        return (
            self._request(
                "POST",
                "/orders",
                json=payload,
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )
            or {}
        )

    def list_orders(self, **params) -> dict:
        return self._request("GET", "/orders", params=_clean(params)) or {}

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/orders/{order_id}") or {}

    def accept_order(self, order_id: str, *, idempotency_key: str | None = None) -> dict:
        return (
            self._request(
                "POST",
                f"/orders/{order_id}/accept",
                json={},
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )
            or {}
        )

    def reject_order(self, order_id: str, reason: str, note: str | None = None) -> dict:
        return (
            self._request(
                "POST", f"/orders/{order_id}/reject", json={"reason": reason, "note": note}
            )
            or {}
        )

    def cancel_order(self, order_id: str) -> dict:
        return self._request("POST", f"/orders/{order_id}/cancel", json={}) or {}

    def report_posting(
        self, order_id: str, payload: dict, *, idempotency_key: str | None = None
    ) -> dict:
        return (
            self._request(
                "POST",
                f"/orders/{order_id}/posting",
                json=payload,
                idempotency_key=idempotency_key or str(uuid.uuid4()),
            )
            or {}
        )

    def report_buyer_posting(self, order_id: str, payload: dict) -> dict:
        return self._request("POST", f"/orders/{order_id}/buyer-posting", json=payload) or {}

    # events
    def get_events(self, since: int, limit: int = 200) -> dict:
        return self._request("GET", "/events", params={"since": since, "limit": limit}) or {}


def _clean(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None}


# Set by the test suite to point every client at the in-memory fake. Production
# leaves it None, so httpx opens a real socket.
_TRANSPORT_OVERRIDE: httpx.BaseTransport | None = None


def set_transport_override(transport: httpx.BaseTransport | None) -> None:
    """Route every client built by this module through *transport* (tests only)."""
    global _TRANSPORT_OVERRIDE
    _TRANSPORT_OVERRIDE = transport


def build_client(
    base_url: str,
    credential: str | None = None,
    *,
    instance_uuid: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> MarketplaceClient:
    return MarketplaceClient(
        base_url,
        credential,
        instance_uuid=instance_uuid,
        transport=transport or _TRANSPORT_OVERRIDE,
    )


def client_for_connection(connection, *, transport: httpx.BaseTransport | None = None):
    """Build a client from a :class:`MarketplaceConnection` row."""
    return build_client(
        connection.base_url,
        connection.credential,
        instance_uuid=connection.instance_uuid,
        transport=transport,
    )
