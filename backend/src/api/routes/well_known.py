"""OAuth discovery documents.

These MUST be served from the origin root (``/.well-known/...``), not from under
``/api`` — RFC 8414 and RFC 9728 both define the location by the issuer/resource
origin, and clients will not look anywhere else. This router therefore carries no
prefix and is mounted directly on the app.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.core.config import settings
from src.services.oauth.tokens import RESOURCE_SCOPES, SCOPE_OFFLINE

router = APIRouter()

_DISCOVERY_HEADERS = {
    "Cache-Control": "public, max-age=300",
    "Access-Control-Allow-Origin": "*",
}


def _issuer() -> str:
    return settings.PUBLIC_API_BASE_URL.rstrip("/")


def _protected_resource_metadata() -> dict:
    return {
        # Must equal, exactly, the URL the user types into their MCP client.
        "resource": settings.MCP_RESOURCE_URI,
        "authorization_servers": [_issuer()],
        "bearer_methods_supported": ["header"],
        # offline_access is deliberately absent: a protected resource must not
        # advertise it (it is an authorization-server concern).
        "scopes_supported": list(RESOURCE_SCOPES),
    }


def _authorization_server_metadata() -> dict:
    issuer = _issuer()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/api/oauth/authorize",
        "token_endpoint": f"{issuer}/api/oauth/token",
        "registration_endpoint": f"{issuer}/api/oauth/register",
        "revocation_endpoint": f"{issuer}/api/oauth/revoke",
        "scopes_supported": [*RESOURCE_SCOPES, SCOPE_OFFLINE],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        "authorization_response_iss_parameter_supported": True,
    }


# RFC 9728 §3.1: when the resource URL has a path, clients probe the
# path-suffixed form first — so both spellings have to answer.
@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def oauth_protected_resource() -> JSONResponse:
    return JSONResponse(_protected_resource_metadata(), headers=_DISCOVERY_HEADERS)


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
@router.get("/.well-known/oauth-authorization-server/mcp", include_in_schema=False)
def oauth_authorization_server() -> JSONResponse:
    return JSONResponse(_authorization_server_metadata(), headers=_DISCOVERY_HEADERS)
