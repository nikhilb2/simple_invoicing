"""OAuth 2.1 authorization server.

Mounted at ``/api/oauth``. Two content types are in play and they are not
interchangeable: ``/register`` takes ``application/json`` (RFC 7591) while
``/token`` and ``/revoke`` take ``application/x-www-form-urlencoded`` (RFC 6749).
Both are parsed by hand so that bad input yields a spec-shaped error body rather
than FastAPI's 422 — Claude and ChatGPT branch on ``error`` codes, and a 422 or a
custom code silently breaks the connector instead of surfacing anything useful.

These routes are excluded from the OpenAPI schema on purpose: the MCP tool
catalog is generated from that schema, and the token endpoint has no business
being callable as a tool.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.core.config import settings
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.oauth import (
    OAuthAuthorizationCode,
    OAuthAuthRequest,
    OAuthClient,
    OAuthToken,
)
from src.models.user import User, UserRole
from src.schemas.oauth import (
    AuthorizationDecisionRequest,
    AuthorizationDecisionResponse,
    AuthorizationRequestInfo,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    ConsentCompany,
    GrantResponse,
    RevokeGrantResponse,
    ScopeDescription,
)
from src.services.oauth.clients import (
    RegistrationError,
    authenticate_client,
    check_registration_rate_limit,
    load_redirect_uris,
    match_registered_redirect_uri,
    parse_basic_auth,
    redirect_uri_matches,
    register_client,
    verify_pkce,
)
from src.services.oauth.tokens import (
    SCOPE_ADMIN,
    SCOPE_DESCRIPTIONS,
    SCOPE_OFFLINE,
    SUPPORTED_SCOPES,
    as_utc,
    format_scope,
    hash_token,
    mint_token,
    now_utc,
    parse_scope,
    revoke_grant_chain,
    revoke_token_row,
)

router = APIRouter()

AUTH_REQUEST_TTL_MINUTES = 10
AUTHORIZATION_CODE_TTL_SECONDS = 60

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _issuer() -> str:
    return settings.PUBLIC_API_BASE_URL.rstrip("/")


def _app_base() -> str:
    return settings.PUBLIC_APP_BASE_URL.rstrip("/")


def _oauth_error(error: str, description: str | None = None, status_code: int = 400) -> JSONResponse:
    """An RFC 6749 §5.2 error body. The code is load-bearing — never invent one."""
    body: dict = {"error": error}
    if description:
        body["error_description"] = description
    return JSONResponse(body, status_code=status_code, headers=NO_STORE)


def _append_query(url: str, params: dict[str, str | None]) -> str:
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _redirect_error(redirect_uri: str, error: str, description: str, state: str | None) -> RedirectResponse:
    return RedirectResponse(
        _append_query(
            redirect_uri,
            {"error": error, "error_description": description, "state": state, "iss": _issuer()},
        ),
        status_code=302,
    )


def _is_expired(value: datetime | None) -> bool:
    moment = as_utc(value)
    return moment is None or moment <= now_utc()


def _user_role_value(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def _filter_scopes_to_user(scopes: list[str], user: User) -> list[str]:
    """Scope never escalates past the consenting user's own role."""
    if _user_role_value(user) != UserRole.admin.value:
        return [scope for scope in scopes if scope != SCOPE_ADMIN]
    return list(scopes)


# --------------------------------------------------------------------------
# RFC 7591 dynamic client registration  (application/json)
# --------------------------------------------------------------------------


@router.post("/register", include_in_schema=False)
async def register(request: Request, db: Session = Depends(get_db)):
    if not settings.OAUTH_DCR_ENABLED:
        return _oauth_error(
            "access_denied", "Dynamic client registration is disabled on this server", 403
        )

    client_ip = request.client.host if request.client else "unknown"
    if not check_registration_rate_limit(client_ip):
        return _oauth_error("invalid_request", "Too many registration attempts", 429)

    try:
        raw = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return _oauth_error("invalid_client_metadata", "Request body must be JSON")
    if not isinstance(raw, dict):
        return _oauth_error("invalid_client_metadata", "Request body must be a JSON object")

    try:
        metadata = ClientRegistrationRequest.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError
        return _oauth_error("invalid_client_metadata", str(exc))

    try:
        client, client_secret = register_client(db, metadata.model_dump(exclude_none=True))
    except RegistrationError as exc:
        return _oauth_error(exc.error, exc.description)

    db.commit()
    db.refresh(client)

    issued_at = as_utc(client.created_at) or now_utc()
    body = ClientRegistrationResponse(
        client_id=client.client_id,
        client_secret=client_secret,
        client_id_issued_at=int(issued_at.timestamp()),
        client_name=client.client_name,
        redirect_uris=load_redirect_uris(client),
        grant_types=client.grant_types.split(),
        response_types=client.response_types.split(),
        scope=client.scope,
        token_endpoint_auth_method=client.token_endpoint_auth_method,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=201, headers=NO_STORE
    )


# --------------------------------------------------------------------------
# Authorization endpoint
# --------------------------------------------------------------------------


@router.get("/authorize", include_in_schema=False)
def authorize(request: Request, db: Session = Depends(get_db)):
    params = request.query_params
    client_id = params.get("client_id")
    redirect_uri = params.get("redirect_uri")
    state = params.get("state")

    if not client_id:
        return _oauth_error("invalid_request", "client_id is required")

    client = (
        db.query(OAuthClient)
        .filter(OAuthClient.client_id == client_id, OAuthClient.is_active.is_(True))
        .first()
    )
    if client is None:
        return _oauth_error("invalid_client", "Unknown client_id", 401)

    registered_uris = load_redirect_uris(client)
    if redirect_uri is None:
        if len(registered_uris) != 1:
            return _oauth_error("invalid_request", "redirect_uri is required")
        redirect_uri = registered_uris[0]
    elif match_registered_redirect_uri(client, redirect_uri) is None:
        # Never redirect to an unverified URI — that is the open-redirect hole.
        return _oauth_error("invalid_request", "redirect_uri does not match a registered value")

    # From here the URI is trusted, so failures go back to the client per RFC 6749 §4.1.2.1.
    if params.get("response_type") != "code":
        return _redirect_error(
            redirect_uri, "unsupported_response_type", "Only response_type=code is supported", state
        )

    code_challenge = params.get("code_challenge")
    code_challenge_method = params.get("code_challenge_method")
    if not code_challenge:
        return _redirect_error(
            redirect_uri, "invalid_request", "PKCE code_challenge is required", state
        )
    if code_challenge_method != "S256":
        # "plain" is explicitly refused: OAuth 2.1 removed it.
        return _redirect_error(
            redirect_uri,
            "invalid_request",
            "code_challenge_method must be S256",
            state,
        )

    requested_scopes = parse_scope(params.get("scope"))
    client_scopes = parse_scope(client.scope) or list(SUPPORTED_SCOPES)
    if not requested_scopes:
        requested_scopes = [s for s in client_scopes if s != SCOPE_OFFLINE]
    unknown = [s for s in requested_scopes if s not in SUPPORTED_SCOPES]
    if unknown:
        return _redirect_error(
            redirect_uri, "invalid_scope", f"Unknown scope: {' '.join(unknown)}", state
        )
    not_registered = [s for s in requested_scopes if s not in client_scopes]
    if not_registered:
        return _redirect_error(
            redirect_uri,
            "invalid_scope",
            f"Scope not permitted for this client: {' '.join(not_registered)}",
            state,
        )

    resource = params.get("resource")
    if resource is not None and resource != settings.MCP_RESOURCE_URI:
        return _redirect_error(
            redirect_uri,
            "invalid_target",
            "resource does not match this server's protected resource",
            state,
        )
    resource = settings.MCP_RESOURCE_URI

    auth_request = OAuthAuthRequest(
        request_id=str(uuid.uuid4()),
        client_id=client.client_id,
        redirect_uri=redirect_uri,
        scope=format_scope(requested_scopes),
        state=state,
        code_challenge=code_challenge,
        code_challenge_method="S256",
        resource=resource,
        expires_at=now_utc() + timedelta(minutes=AUTH_REQUEST_TTL_MINUTES),
    )
    db.add(auth_request)
    db.commit()

    # Only the opaque request_id crosses the browser.
    return RedirectResponse(
        f"{_app_base()}/oauth/consent?request_id={auth_request.request_id}",
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/authorize/request/{request_id}",
    response_model=AuthorizationRequestInfo,
    include_in_schema=False,
)
def get_authorize_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    auth_request = (
        db.query(OAuthAuthRequest).filter(OAuthAuthRequest.request_id == request_id).first()
    )
    if auth_request is None or auth_request.consumed_at is not None:
        return _oauth_error("invalid_request", "Unknown or already-used authorization request", 404)
    if _is_expired(auth_request.expires_at):
        return _oauth_error("invalid_request", "Authorization request has expired", 410)

    client = (
        db.query(OAuthClient).filter(OAuthClient.client_id == auth_request.client_id).first()
    )
    if client is None:
        return _oauth_error("invalid_client", "Unknown client", 404)

    granted = _filter_scopes_to_user(parse_scope(auth_request.scope), current_user)
    companies = db.query(CompanyProfile).order_by(
        CompanyProfile.name.asc(), CompanyProfile.id.asc()
    ).all()

    default_company_id = current_user.active_company_id
    if default_company_id is None and companies:
        default_company_id = companies[0].id

    return AuthorizationRequestInfo(
        request_id=auth_request.request_id,
        client_id=client.client_id,
        client_name=client.client_name,
        client_uri=client.client_uri,
        client_uri_host=(urlparse(client.client_uri).netloc or None) if client.client_uri else None,
        logo_uri=client.logo_uri,
        # Where the code will actually be sent — the trustworthy identifier.
        # client_name is self-asserted at registration.
        redirect_uri_host=urlparse(auth_request.redirect_uri).netloc,
        redirect_uri=auth_request.redirect_uri,
        scopes=[
            ScopeDescription(scope=scope, description=SCOPE_DESCRIPTIONS.get(scope, scope))
            for scope in granted
        ],
        resource=auth_request.resource,
        companies=[ConsentCompany(id=c.id, name=c.name or f"Company #{c.id}") for c in companies],
        default_company_id=default_company_id,
        expires_at=as_utc(auth_request.expires_at),
    )


@router.post(
    "/authorize/decision",
    response_model=AuthorizationDecisionResponse,
    include_in_schema=False,
)
def authorize_decision(
    payload: AuthorizationDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    auth_request = (
        db.query(OAuthAuthRequest)
        .filter(OAuthAuthRequest.request_id == payload.request_id)
        .first()
    )
    if auth_request is None or auth_request.consumed_at is not None:
        return _oauth_error("invalid_request", "Unknown or already-used authorization request", 404)
    if _is_expired(auth_request.expires_at):
        return _oauth_error("invalid_request", "Authorization request has expired", 410)

    if not payload.approve:
        auth_request.consumed_at = now_utc()
        db.commit()
        return AuthorizationDecisionResponse(
            redirect_to=_append_query(
                auth_request.redirect_uri,
                {
                    "error": "access_denied",
                    "error_description": "The user denied the request",
                    "state": auth_request.state,
                    "iss": _issuer(),
                },
            )
        )

    company_id = payload.company_id if payload.company_id is not None else current_user.active_company_id
    company = (
        db.query(CompanyProfile).filter(CompanyProfile.id == company_id).first()
        if company_id is not None
        else None
    )
    if company is None:
        return _oauth_error("invalid_request", "A valid company_id is required to approve", 400)

    granted_scopes = _filter_scopes_to_user(parse_scope(auth_request.scope), current_user)

    raw_code = secrets.token_urlsafe(32)
    code_row = OAuthAuthorizationCode(
        code_hash=hash_token(raw_code),
        client_id=auth_request.client_id,
        user_id=current_user.id,
        company_id=company.id,
        scope=format_scope(granted_scopes),
        redirect_uri=auth_request.redirect_uri,
        code_challenge=auth_request.code_challenge,
        code_challenge_method=auth_request.code_challenge_method,
        resource=auth_request.resource,
        expires_at=now_utc() + timedelta(seconds=AUTHORIZATION_CODE_TTL_SECONDS),
    )
    db.add(code_row)
    auth_request.consumed_at = now_utc()
    db.commit()

    return AuthorizationDecisionResponse(
        redirect_to=_append_query(
            auth_request.redirect_uri,
            # iss per RFC 9207, matching authorization_response_iss_parameter_supported.
            {"code": raw_code, "state": auth_request.state, "iss": _issuer()},
        )
    )


# --------------------------------------------------------------------------
# Token endpoint  (application/x-www-form-urlencoded)
# --------------------------------------------------------------------------


def _token_response(
    db: Session,
    *,
    client_id: str,
    user_id: int,
    company_id: int | None,
    scope: str,
    resource: str | None,
    auth_code_id: int | None,
    parent_id: int | None = None,
    with_refresh: bool,
) -> JSONResponse:
    refresh_raw = None
    refresh_row = None
    if with_refresh:
        refresh_raw, refresh_row = mint_token(
            db,
            token_type="refresh",
            client_id=client_id,
            user_id=user_id,
            company_id=company_id,
            scope=scope,
            resource=resource,
            auth_code_id=auth_code_id,
            parent_id=parent_id,
        )

    access_raw, _ = mint_token(
        db,
        token_type="access",
        client_id=client_id,
        user_id=user_id,
        company_id=company_id,
        scope=scope,
        resource=resource,
        auth_code_id=auth_code_id,
        parent_id=refresh_row.id if refresh_row is not None else parent_id,
    )
    db.commit()

    body = {
        "access_token": access_raw,
        "token_type": "Bearer",
        "expires_in": settings.OAUTH_ACCESS_TOKEN_TTL_MINUTES * 60,
        "scope": scope,
    }
    if refresh_raw:
        body["refresh_token"] = refresh_raw
    return JSONResponse(body, headers=NO_STORE)


@router.post("/token", include_in_schema=False)
async def token_endpoint(request: Request, db: Session = Depends(get_db)):
    try:
        form = await request.form()
    except Exception:
        return _oauth_error("invalid_request", "Request body must be form-encoded")

    if not form:
        return _oauth_error(
            "invalid_request",
            "Request body must be application/x-www-form-urlencoded",
        )

    grant_type = form.get("grant_type")
    client = authenticate_client(
        db,
        client_id=form.get("client_id"),
        client_secret=form.get("client_secret"),
        basic_auth=parse_basic_auth(request.headers.get("authorization")),
    )
    if client is None:
        return _oauth_error("invalid_client", "Client authentication failed", 401)

    allowed_grants = (client.grant_types or "").split()
    if grant_type not in allowed_grants:
        return _oauth_error(
            "unsupported_grant_type", f"grant_type {grant_type!r} is not permitted for this client"
        )

    if grant_type == "authorization_code":
        return _grant_authorization_code(db, form, client)
    if grant_type == "refresh_token":
        return _grant_refresh_token(db, form, client)
    return _oauth_error("unsupported_grant_type", f"Unsupported grant_type: {grant_type!r}")


def _grant_authorization_code(db: Session, form, client: OAuthClient) -> JSONResponse:
    code = form.get("code")
    if not code:
        return _oauth_error("invalid_request", "code is required")

    code_row = (
        db.query(OAuthAuthorizationCode)
        .filter(OAuthAuthorizationCode.code_hash == hash_token(code))
        .first()
    )
    if code_row is None or code_row.client_id != client.client_id:
        return _oauth_error("invalid_grant", "Authorization code is invalid")

    if code_row.used_at is not None:
        # OAuth 2.1: a replayed code takes down every token it produced.
        revoke_grant_chain(db, auth_code_id=code_row.id)
        db.commit()
        return _oauth_error("invalid_grant", "Authorization code has already been used")

    if _is_expired(code_row.expires_at):
        return _oauth_error("invalid_grant", "Authorization code has expired")

    redirect_uri = form.get("redirect_uri")
    if not redirect_uri or not redirect_uri_matches(code_row.redirect_uri, redirect_uri):
        return _oauth_error("invalid_grant", "redirect_uri does not match the authorization request")

    if not verify_pkce(form.get("code_verifier") or "", code_row.code_challenge, code_row.code_challenge_method):
        return _oauth_error("invalid_grant", "PKCE verification failed")

    code_row.used_at = now_utc()
    client.last_used_at = now_utc()

    scopes = parse_scope(code_row.scope)
    return _token_response(
        db,
        client_id=client.client_id,
        user_id=code_row.user_id,
        company_id=code_row.company_id,
        scope=format_scope(scopes),
        resource=code_row.resource,
        auth_code_id=code_row.id,
        with_refresh=SCOPE_OFFLINE in scopes,
    )


def _grant_refresh_token(db: Session, form, client: OAuthClient) -> JSONResponse:
    raw = form.get("refresh_token")
    if not raw:
        return _oauth_error("invalid_request", "refresh_token is required")

    row = (
        db.query(OAuthToken)
        .filter(OAuthToken.token_hash == hash_token(raw), OAuthToken.token_type == "refresh")
        .first()
    )
    if row is None or row.client_id != client.client_id:
        return _oauth_error("invalid_grant", "Refresh token is invalid")

    if row.revoked_at is not None:
        # Reuse of a retired token: assume exfiltration and kill the whole chain.
        revoke_grant_chain(db, auth_code_id=row.auth_code_id, token=row)
        db.commit()
        return _oauth_error("invalid_grant", "Refresh token has been revoked")

    if _is_expired(row.expires_at):
        return _oauth_error("invalid_grant", "Refresh token has expired")

    held_scopes = parse_scope(row.scope)
    requested = parse_scope(form.get("scope"))
    if requested:
        extra = [s for s in requested if s not in held_scopes]
        if extra:
            return _oauth_error("invalid_scope", f"Scope exceeds the original grant: {' '.join(extra)}")
        granted = requested
    else:
        granted = held_scopes

    # Rotation: issuing the replacement retires this one immediately.
    revoke_token_row(db, row)
    client.last_used_at = now_utc()

    return _token_response(
        db,
        client_id=client.client_id,
        user_id=row.user_id,
        company_id=row.company_id,
        scope=format_scope(granted),
        resource=row.resource,
        auth_code_id=row.auth_code_id,
        parent_id=row.id,
        with_refresh=SCOPE_OFFLINE in granted,
    )


# --------------------------------------------------------------------------
# RFC 7009 revocation
# --------------------------------------------------------------------------


@router.post("/revoke", include_in_schema=False)
async def revoke(request: Request, db: Session = Depends(get_db)):
    try:
        form = await request.form()
    except Exception:
        return _oauth_error("invalid_request", "Request body must be form-encoded")

    client = authenticate_client(
        db,
        client_id=form.get("client_id"),
        client_secret=form.get("client_secret"),
        basic_auth=parse_basic_auth(request.headers.get("authorization")),
    )
    if client is None:
        return _oauth_error("invalid_client", "Client authentication failed", 401)

    raw = form.get("token")
    if raw:
        row = (
            db.query(OAuthToken)
            .filter(OAuthToken.token_hash == hash_token(raw), OAuthToken.client_id == client.client_id)
            .first()
        )
        if row is not None:
            if row.token_type == "refresh":
                # RFC 7009 §2.1: revoking a refresh token takes the access
                # tokens issued alongside it with it.
                revoke_grant_chain(db, auth_code_id=row.auth_code_id, token=row)
            else:
                revoke_token_row(db, row)
            db.commit()

    # An unknown token is not an error, per RFC 7009 §2.2.
    return JSONResponse({}, status_code=200, headers=NO_STORE)


# --------------------------------------------------------------------------
# Grant management for the Settings UI (app-JWT authed)
# --------------------------------------------------------------------------


@router.get("/grants", response_model=list[GrantResponse], include_in_schema=False)
def list_grants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(OAuthToken)
        .filter(OAuthToken.user_id == current_user.id, OAuthToken.revoked_at.is_(None))
        .order_by(OAuthToken.created_at.asc())
        .all()
    )
    live = [row for row in rows if not _is_expired(row.expires_at)]
    if not live:
        return []

    clients = {
        c.client_id: c
        for c in db.query(OAuthClient)
        .filter(OAuthClient.client_id.in_({row.client_id for row in live}))
        .all()
    }
    companies = {
        c.id: c
        for c in db.query(CompanyProfile)
        .filter(CompanyProfile.id.in_({row.company_id for row in live if row.company_id}))
        .all()
    }

    grants: dict[str, GrantResponse] = {}
    for row in live:
        client = clients.get(row.client_id)
        company = companies.get(row.company_id) if row.company_id else None
        created_at = as_utc(row.created_at) or now_utc()
        last_used_at = as_utc(row.last_used_at)
        existing = grants.get(row.client_id)
        if existing is None:
            grants[row.client_id] = GrantResponse(
                client_id=row.client_id,
                client_name=client.client_name if client else row.client_id,
                scopes=parse_scope(row.scope),
                company_id=row.company_id,
                company_name=(company.name or f"Company #{company.id}") if company else None,
                created_at=created_at,
                last_used_at=last_used_at,
            )
        else:
            merged = sorted(set(existing.scopes) | set(parse_scope(row.scope)))
            existing.scopes = merged
            if created_at < existing.created_at:
                existing.created_at = created_at
            if last_used_at and (existing.last_used_at is None or last_used_at > existing.last_used_at):
                existing.last_used_at = last_used_at

    return list(grants.values())


@router.delete(
    "/grants/{client_id}", response_model=RevokeGrantResponse, include_in_schema=False
)
def revoke_grant(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(OAuthToken)
        .filter(
            OAuthToken.user_id == current_user.id,
            OAuthToken.client_id == client_id,
            OAuthToken.revoked_at.is_(None),
        )
        .all()
    )
    stamp = now_utc()
    for row in rows:
        row.revoked_at = stamp
    db.commit()
    return RevokeGrantResponse(revoked=len(rows))
