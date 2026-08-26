"""Client registration, redirect-URI matching, PKCE and client authentication."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import time
import uuid
from collections import defaultdict, deque
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from src.models.oauth import OAuthClient
from src.services.oauth.tokens import (
    SUPPORTED_SCOPES,
    format_scope,
    hash_secret,
    parse_scope,
    verify_secret_hash,
)

SUPPORTED_GRANT_TYPES = ("authorization_code", "refresh_token")
SUPPORTED_RESPONSE_TYPES = ("code",)
SUPPORTED_AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")

# RFC 8252 §7.3 loopback hosts.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class RegistrationError(Exception):
    """RFC 7591 registration failure carrying its own error code."""

    def __init__(self, error: str, description: str):
        super().__init__(description)
        self.error = error
        self.description = description


# --- redirect URIs ---------------------------------------------------------


def is_loopback_redirect(uri: str) -> bool:
    parsed = urlparse(uri)
    return parsed.scheme == "http" and (parsed.hostname or "") in LOOPBACK_HOSTS


def validate_redirect_uri(uri: str) -> None:
    """A redirect URI must be https, or an RFC 8252 loopback http URI."""
    parsed = urlparse(uri)
    if parsed.fragment:
        raise RegistrationError("invalid_redirect_uri", f"redirect_uri must not contain a fragment: {uri}")
    if parsed.scheme == "https" and parsed.hostname:
        return
    if is_loopback_redirect(uri):
        return
    raise RegistrationError(
        "invalid_redirect_uri",
        f"redirect_uri must be https:// or an http loopback address: {uri}",
    )


def redirect_uri_matches(registered: str, requested: str) -> bool:
    """Exact string comparison — except loopback, where the port is ignored.

    Native clients such as Claude Code bind an ephemeral localhost port at run
    time and cannot register it in advance (RFC 8252 §7.3), so for loopback the
    port is the one component allowed to differ. Everything else, including the
    path and query, must still match exactly.
    """
    if registered == requested:
        return True

    if not (is_loopback_redirect(registered) and is_loopback_redirect(requested)):
        return False

    a, b = urlparse(registered), urlparse(requested)
    return (
        a.scheme == b.scheme
        and (a.hostname or "") == (b.hostname or "")
        and a.path == b.path
        and a.params == b.params
        and a.query == b.query
        and a.username == b.username
    )


def match_registered_redirect_uri(client: OAuthClient, requested: str) -> str | None:
    for registered in load_redirect_uris(client):
        if redirect_uri_matches(registered, requested):
            return registered
    return None


def load_redirect_uris(client: OAuthClient) -> list[str]:
    try:
        value = json.loads(client.redirect_uris or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


# --- PKCE ------------------------------------------------------------------


def verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    """S256 only. ``plain`` is not accepted anywhere in this server."""
    if method != "S256":
        return False
    if not code_verifier or not (43 <= len(code_verifier) <= 128):
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii", errors="ignore")).digest()
    expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return secrets.compare_digest(expected, code_challenge)


# --- registration ----------------------------------------------------------

_RATE_LIMIT_WINDOW_SECONDS = 3600
_RATE_LIMIT_MAX = 60
_rate_limit_buckets: dict[str, deque] = defaultdict(deque)


def reset_rate_limits() -> None:
    _rate_limit_buckets.clear()


def check_registration_rate_limit(client_ip: str) -> bool:
    bucket = _rate_limit_buckets[client_ip]
    now = time.monotonic()
    while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_MAX:
        return False
    bucket.append(now)
    return True


def register_client(db: Session, payload: dict) -> tuple[OAuthClient, str | None]:
    """Validate an RFC 7591 registration request and persist it.

    Returns ``(client, plaintext_client_secret_or_None)``. Does not commit.
    """
    redirect_uris = payload.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise RegistrationError("invalid_redirect_uri", "redirect_uris is required and must be a non-empty array")
    for uri in redirect_uris:
        if not isinstance(uri, str):
            raise RegistrationError("invalid_redirect_uri", "redirect_uris entries must be strings")
        validate_redirect_uri(uri)

    grant_types = payload.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grant_types, list):
        raise RegistrationError("invalid_client_metadata", "grant_types must be an array")
    unknown = [g for g in grant_types if g not in SUPPORTED_GRANT_TYPES]
    if unknown:
        raise RegistrationError(
            "invalid_client_metadata",
            f"unsupported grant_types: {', '.join(map(str, unknown))}",
        )

    response_types = payload.get("response_types") or ["code"]
    if not isinstance(response_types, list):
        raise RegistrationError("invalid_client_metadata", "response_types must be an array")
    unknown_rt = [r for r in response_types if r not in SUPPORTED_RESPONSE_TYPES]
    if unknown_rt:
        raise RegistrationError(
            "invalid_client_metadata",
            f"unsupported response_types: {', '.join(map(str, unknown_rt))}",
        )

    auth_method = payload.get("token_endpoint_auth_method") or "none"
    if auth_method not in SUPPORTED_AUTH_METHODS:
        raise RegistrationError(
            "invalid_client_metadata",
            f"unsupported token_endpoint_auth_method: {auth_method}",
        )

    requested_scopes = parse_scope(payload.get("scope"))
    if requested_scopes:
        bad = [s for s in requested_scopes if s not in SUPPORTED_SCOPES]
        if bad:
            raise RegistrationError("invalid_client_metadata", f"unknown scope: {' '.join(bad)}")
        scope = format_scope(requested_scopes)
    else:
        scope = format_scope(SUPPORTED_SCOPES)

    client_name = (payload.get("client_name") or "").strip() or "Unnamed client"

    client_secret: str | None = None
    secret_hash: str | None = None
    if auth_method != "none":
        client_secret = secrets.token_urlsafe(32)
        secret_hash = hash_secret(client_secret)

    client = OAuthClient(
        client_id=str(uuid.uuid4()),
        client_secret_hash=secret_hash,
        client_name=client_name[:255],
        client_uri=(payload.get("client_uri") or None),
        logo_uri=(payload.get("logo_uri") or None),
        redirect_uris=json.dumps(list(redirect_uris)),
        grant_types=" ".join(grant_types),
        response_types=" ".join(response_types),
        scope=scope,
        token_endpoint_auth_method=auth_method,
        software_id=(payload.get("software_id") or None),
        is_active=True,
    )
    db.add(client)
    db.flush()
    return client, client_secret


# --- client authentication at the token endpoint ---------------------------


def parse_basic_auth(header_value: str | None) -> tuple[str, str] | None:
    if not header_value or not header_value.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header_value.split(" ", 1)[1]).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, IndexError):
        return None
    if ":" not in decoded:
        return None
    client_id, secret = decoded.split(":", 1)
    return client_id, secret


def authenticate_client(
    db: Session,
    *,
    client_id: str | None,
    client_secret: str | None,
    basic_auth: tuple[str, str] | None,
) -> OAuthClient | None:
    """Resolve and authenticate the client for a token/revocation request."""
    if basic_auth is not None:
        basic_id, basic_secret = basic_auth
        if client_id and client_id != basic_id:
            return None
        client_id, client_secret = basic_id, basic_secret

    if not client_id:
        return None

    client = (
        db.query(OAuthClient)
        .filter(OAuthClient.client_id == client_id, OAuthClient.is_active.is_(True))
        .first()
    )
    if client is None:
        return None

    if client.token_endpoint_auth_method == "none":
        # Public client: PKCE is the proof, no secret is expected or accepted.
        return client

    if not client_secret or not verify_secret_hash(client_secret, client.client_secret_hash):
        return None
    return client
