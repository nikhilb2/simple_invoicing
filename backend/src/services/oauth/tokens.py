"""Opaque OAuth token minting, hashing, chain revocation and bearer resolution.

Tokens are ``sio_at_<43 url-safe chars>`` / ``sio_rt_<…>`` and are persisted only
as sha256 hex digests. They deliberately do not look like the app's JWTs, so the
existing ``get_current_user`` JWT path rejects them outright — an OAuth access
token must never authenticate a plain REST call.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.oauth import OAuthToken
from src.models.user import User

ACCESS_TOKEN_PREFIX = "sio_at_"
REFRESH_TOKEN_PREFIX = "sio_rt_"

SCOPE_READ = "invoicing:read"
SCOPE_WRITE = "invoicing:write"
SCOPE_ADMIN = "invoicing:admin"
SCOPE_SEND_EMAIL = "invoicing:send_email"
SCOPE_OFFLINE = "offline_access"

# Scopes that name a capability on the resource server.
RESOURCE_SCOPES: tuple[str, ...] = (
    SCOPE_READ,
    SCOPE_WRITE,
    SCOPE_ADMIN,
    SCOPE_SEND_EMAIL,
)
# Everything a client may ask for. offline_access is an authorization-server
# concern (it buys a refresh token) and is never advertised by the resource.
SUPPORTED_SCOPES: tuple[str, ...] = RESOURCE_SCOPES + (SCOPE_OFFLINE,)

SCOPE_DESCRIPTIONS: dict[str, str] = {
    SCOPE_READ: "Read your invoices, ledgers, stock, payments and reports",
    SCOPE_WRITE: "Create and modify invoices, ledgers, stock and payments",
    SCOPE_ADMIN: "Manage users, company settings, invoice series and API keys",
    SCOPE_SEND_EMAIL: "Send invoices and documents by email on your behalf",
    SCOPE_OFFLINE: "Stay connected without asking you to sign in again",
}


@dataclass(frozen=True)
class OAuthPrincipal:
    """A resolved bearer token, flattened to plain values.

    Deliberately not an ORM object: the caller closes the session before using
    this, so a lazy attribute load would raise ``DetachedInstanceError``.
    """

    user_id: int
    email: str
    role: str  # "admin" | "manager" | "staff"
    company_id: int | None
    scopes: frozenset[str]
    client_id: str


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on the way back out; re-attach UTC so comparisons work."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret_hash(secret: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False
    return hmac.compare_digest(hash_secret(secret), expected_hash)


def generate_token(prefix: str) -> str:
    # 32 random bytes -> 43 url-safe base64 characters, unpadded.
    return prefix + secrets.token_urlsafe(32)


def parse_scope(raw: str | None) -> list[str]:
    if not raw:
        return []
    seen: list[str] = []
    for part in raw.replace(",", " ").split():
        if part not in seen:
            seen.append(part)
    return seen


def format_scope(scopes) -> str:
    return " ".join(scopes)


def mint_token(
    db: Session,
    *,
    token_type: str,
    client_id: str,
    user_id: int,
    company_id: int | None,
    scope: str,
    resource: str | None,
    auth_code_id: int | None = None,
    parent_id: int | None = None,
) -> tuple[str, OAuthToken]:
    """Create one token row and return ``(raw_token, row)``. Does not commit."""
    if token_type == "access":
        raw = generate_token(ACCESS_TOKEN_PREFIX)
        expires_at = now_utc() + timedelta(minutes=settings.OAUTH_ACCESS_TOKEN_TTL_MINUTES)
    elif token_type == "refresh":
        raw = generate_token(REFRESH_TOKEN_PREFIX)
        expires_at = now_utc() + timedelta(days=settings.OAUTH_REFRESH_TOKEN_TTL_DAYS)
    else:  # pragma: no cover - programmer error
        raise ValueError(f"unknown token_type {token_type!r}")

    row = OAuthToken(
        token_type=token_type,
        token_hash=hash_token(raw),
        client_id=client_id,
        user_id=user_id,
        company_id=company_id,
        scope=scope,
        resource=resource,
        auth_code_id=auth_code_id,
        parent_id=parent_id,
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return raw, row


def revoke_grant_chain(db: Session, *, auth_code_id: int | None, token: OAuthToken | None = None) -> int:
    """Revoke every live token descended from one authorization code.

    OAuth 2.1 requires that a replayed code, and the reuse of a retired refresh
    token, take down the entire grant rather than just the offending credential.
    ``auth_code_id`` is that grant's identity. Falls back to the single token when
    the code row is gone (``ON DELETE SET NULL``).
    """
    query = db.query(OAuthToken).filter(OAuthToken.revoked_at.is_(None))
    if auth_code_id is not None:
        query = query.filter(OAuthToken.auth_code_id == auth_code_id)
    elif token is not None:
        query = query.filter(OAuthToken.id == token.id)
    else:  # pragma: no cover - nothing to revoke
        return 0

    stamp = now_utc()
    count = 0
    for row in query.all():
        row.revoked_at = stamp
        count += 1
    return count


def revoke_token_row(db: Session, token: OAuthToken) -> None:
    if token.revoked_at is None:
        token.revoked_at = now_utc()


def resolve_bearer(token: str, db: Session) -> OAuthPrincipal | None:
    """Resolve a raw bearer token to a principal, or ``None`` if it is no good.

    Rejects unknown, revoked and expired tokens, and — a MUST from RFC 8707 /
    the MCP authorization spec — any token whose stored ``resource`` is not our
    canonical resource URI. A token minted for someone else's audience must not
    open this door.
    """
    if not token or not token.startswith(ACCESS_TOKEN_PREFIX):
        return None

    row = (
        db.query(OAuthToken)
        .filter(
            OAuthToken.token_hash == hash_token(token),
            OAuthToken.token_type == "access",
        )
        .first()
    )
    if row is None:
        return None
    if row.revoked_at is not None:
        return None

    expires_at = as_utc(row.expires_at)
    if expires_at is None or expires_at <= now_utc():
        return None

    # Audience validation.
    if (row.resource or "") != settings.MCP_RESOURCE_URI:
        return None

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        return None

    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    principal = OAuthPrincipal(
        user_id=user.id,
        email=user.email,
        role=role,
        company_id=row.company_id,
        scopes=frozenset(parse_scope(row.scope)),
        client_id=row.client_id,
    )

    row.last_used_at = now_utc()
    db.commit()

    return principal
