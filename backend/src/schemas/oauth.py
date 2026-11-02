"""Pydantic v2 schemas for the OAuth 2.1 authorization server.

Only the JSON-bodied endpoints use these. ``/token`` and ``/revoke`` are
``application/x-www-form-urlencoded`` and are parsed by hand so that malformed
input produces an RFC 6749 error body rather than FastAPI's 422.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 client metadata. Unknown members are ignored, per the RFC."""

    model_config = ConfigDict(extra="ignore")

    redirect_uris: list[str] = Field(default_factory=list)
    client_name: str | None = None
    client_uri: str | None = None
    logo_uri: str | None = None
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    scope: str | None = None
    token_endpoint_auth_method: str | None = None
    software_id: str | None = None
    software_version: str | None = None


class ClientRegistrationResponse(BaseModel):
    client_id: str
    client_secret: str | None = None
    client_id_issued_at: int
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    scope: str
    token_endpoint_auth_method: str


class ScopeDescription(BaseModel):
    scope: str
    description: str


class ConsentCompany(BaseModel):
    id: int
    name: str


class AuthorizationRequestInfo(BaseModel):
    """What the consent screen renders.

    ``redirect_uri_host`` is where the authorization code will actually be
    sent, and is the one field a user can make a trust decision on: a
    self-asserted ``client_name`` is a label, not an identity.
    """

    request_id: str
    client_id: str
    client_name: str
    client_uri: str | None = None
    client_uri_host: str | None = None
    logo_uri: str | None = None
    redirect_uri_host: str
    redirect_uri: str
    scopes: list[ScopeDescription]
    resource: str | None = None
    companies: list[ConsentCompany]
    default_company_id: int | None = None
    expires_at: datetime


class AuthorizationDecisionRequest(BaseModel):
    request_id: str
    approve: bool
    company_id: int | None = None


class AuthorizationDecisionResponse(BaseModel):
    redirect_to: str


class GrantResponse(BaseModel):
    client_id: str
    client_name: str
    scopes: list[str]
    company_id: int | None = None
    company_name: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None


class RevokeGrantResponse(BaseModel):
    revoked: int
