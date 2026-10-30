"""Social sign-in providers, registered from config with Authlib.

The list works like Auth.js's: a provider is one entry in PROVIDERS saying how to
tell whether it is configured and what to hand Authlib. Adding Microsoft or GitHub
later is a new entry plus two settings, not new route code -- the routes in
routes/auth.py only ever deal in a provider id.

A provider is registered only when its credentials are set. An unconfigured one
does not exist as far as the API is concerned: /auth/config does not list it and
its /oauth/<id>/... routes 404.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App

from src.core.config import Settings, settings

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    # Whether the credentials are present, i.e. whether existing users may sign in.
    configured: Callable[[Settings], bool]
    # Whether an unknown person may create an account through this provider.
    signup_allowed: Callable[[Settings], bool]
    # Keyword arguments for OAuth.register.
    register_kwargs: Callable[[Settings], dict]
    # claims_options for the ID token. Authlib checks signature, exp and nonce
    # itself, and iss only by default -- the audience it checks only when told.
    id_token_claims: Callable[[Settings], dict]


PROVIDERS: dict[str, ProviderSpec] = {
    "google": ProviderSpec(
        id="google",
        name="Google",
        configured=lambda s: s.google_auth_enabled,
        signup_allowed=lambda s: s.google_signup_enabled,
        register_kwargs=lambda s: {
            "client_id": s.OAUTH_GOOGLE_CLIENT_ID,
            "client_secret": s.OAUTH_GOOGLE_CLIENT_SECRET,
            # OIDC discovery: Authlib fetches the endpoints and the signing keys
            # from here, and checks the ID token's signature, exp and nonce
            # against them in authorize_access_token; iss and aud are below.
            "server_metadata_url": GOOGLE_DISCOVERY_URL,
            "client_kwargs": {
                "scope": "openid email profile",
                # PKCE on top of the client secret: a code intercepted on its way
                # back is useless without the verifier held in our session cookie.
                "code_challenge_method": "S256",
            },
        },
        id_token_claims=lambda s: {
            # Google documents both spellings of its issuer.
            "iss": {"essential": True, "values": ["https://accounts.google.com", "accounts.google.com"]},
            # A token Google minted for some other app must not sign anyone in here.
            "aud": {"essential": True, "value": s.OAUTH_GOOGLE_CLIENT_ID},
        },
    ),
}


_oauth: OAuth | None = None


def _registry() -> OAuth:
    """Built on first use, from whatever the settings say at that moment."""
    global _oauth
    if _oauth is None:
        oauth = OAuth()
        for spec in PROVIDERS.values():
            if spec.configured(settings):
                oauth.register(name=spec.id, **spec.register_kwargs(settings))
        _oauth = oauth
    return _oauth


def reset_registry() -> None:
    """Test hook: forget the registered clients so changed settings take effect."""
    global _oauth
    _oauth = None


def enabled_providers() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS.values() if spec.configured(settings)]


def get_spec(provider_id: str) -> ProviderSpec | None:
    spec = PROVIDERS.get(provider_id)
    if spec is None or not spec.configured(settings):
        return None
    return spec


def get_client(provider_id: str) -> StarletteOAuth2App | None:
    if get_spec(provider_id) is None:
        return None
    return _registry().create_client(provider_id)


def redirect_uri(provider_id: str) -> str:
    """The callback URL registered with the provider.

    Built on PUBLIC_APP_BASE_URL, the web app's origin, not the API's: /api is
    proxied there (by Vite in dev, by the ingress in production), so the callback
    is same-origin with the page that started the flow and the SameSite=Lax state
    cookie set on the way out comes back with it.
    """
    return f"{settings.PUBLIC_APP_BASE_URL.rstrip('/')}/api/auth/oauth/{provider_id}/callback"
