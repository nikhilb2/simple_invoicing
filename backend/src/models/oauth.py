"""OAuth 2.1 authorization-server tables.

Classic ``Column()`` style, matching :mod:`src.models.api_key`. These must stay
SQLite-compatible because the test suite builds the schema straight from
``Base.metadata`` against in-memory SQLite: no JSONB, no partial indexes here.
Postgres-only DDL lives in ``migrations/20260827000001_add_oauth_server.py``.

Tokens are stored as sha256 hex digests, never in a reversible form, so a
database dump yields no usable credential.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)

from src.db.base import Base


class OAuthClient(Base):
    """An RFC 7591 dynamic client registration."""

    __tablename__ = "oauth_clients"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(64), nullable=False, unique=True, index=True)
    # sha256 hex of the client secret; NULL for public clients (auth method "none").
    client_secret_hash = Column(String(64), nullable=True)
    client_name = Column(String(255), nullable=False)
    client_uri = Column(String(2048), nullable=True)
    logo_uri = Column(String(2048), nullable=True)
    # JSON array of strings. Text, not JSONB — SQLite has to build this schema too.
    redirect_uris = Column(Text, nullable=False)
    # Space-delimited, as they appear on the wire.
    grant_types = Column(Text, nullable=False, default="authorization_code refresh_token")
    response_types = Column(Text, nullable=False, default="code")
    scope = Column(Text, nullable=False, default="")
    token_endpoint_auth_method = Column(String(32), nullable=False, default="none")
    software_id = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)


class OAuthAuthRequest(Base):
    """An in-flight ``/authorize`` request, parked while the user logs in and consents.

    Nothing security-relevant round-trips through the browser: the redirect to the
    consent screen carries only this opaque ``request_id``.
    """

    __tablename__ = "oauth_auth_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), nullable=False, unique=True, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    redirect_uri = Column(Text, nullable=False)
    scope = Column(Text, nullable=False, default="")
    state = Column(Text, nullable=True)
    code_challenge = Column(String(255), nullable=False)
    code_challenge_method = Column(String(16), nullable=False, default="S256")
    resource = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OAuthAuthorizationCode(Base):
    """A one-shot authorization code. Replaying one revokes everything it produced."""

    __tablename__ = "oauth_authorization_codes"

    id = Column(Integer, primary_key=True, index=True)
    code_hash = Column(String(64), nullable=False, unique=True, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=True, index=True)
    scope = Column(Text, nullable=False, default="")
    redirect_uri = Column(Text, nullable=False)
    code_challenge = Column(String(255), nullable=False)
    code_challenge_method = Column(String(16), nullable=False, default="S256")
    resource = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OAuthToken(Base):
    """An issued access or refresh token, stored only as a sha256 digest.

    ``auth_code_id`` is the grant identity: every token descended from one
    authorization code shares it, which is what makes "a replayed code revokes
    every token it produced" and "refresh reuse kills the whole chain" a single
    indexed UPDATE. ``parent_id`` records the rotation lineage itself.
    """

    __tablename__ = "oauth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token_type = Column(String(16), nullable=False, index=True)  # "access" | "refresh"
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("company_profiles.id", ondelete="CASCADE"), nullable=True, index=True)
    scope = Column(Text, nullable=False, default="")
    resource = Column(Text, nullable=True)
    auth_code_id = Column(
        Integer,
        ForeignKey("oauth_authorization_codes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parent_id = Column(Integer, ForeignKey("oauth_tokens.id", ondelete="SET NULL"), nullable=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
