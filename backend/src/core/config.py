from pydantic_settings import BaseSettings
from pydantic import model_validator
import os
from pathlib import Path


# Detect environment from ENVIRONMENT variable, default to development
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Build path to the appropriate .env file
env_file_path = Path(f".env.{ENVIRONMENT}")
if not env_file_path.exists():
    # Fallback to .env if environment-specific file doesn't exist
    env_file_path = Path(".env")


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    DEBUG: bool = False
    ENVIRONMENT: str = ENVIRONMENT
    SMTP_ENCRYPTION_KEY: str | None = None
    MCP_API_TOKEN: str | None = None
    # Declared as real fields, not read via getattr: `extra = "ignore"` below means
    # an undeclared name resolves to nothing at all, so a getattr fallback would
    # silently return None forever.
    MARKETPLACE_ALLOW_INSECURE_URL: bool = False
    MARKETPLACE_HTTP_TIMEOUT_SECONDS: int = 15

    # --- MCP server + OAuth authorization server ---
    # Public origin of this API. Doubles as the OAuth issuer and the base of the
    # canonical MCP resource URI, so it MUST match what users type into their client.
    PUBLIC_API_BASE_URL: str = "http://localhost:8000"
    # Public origin of the web app: OAuth consent redirect + search/fetch citation links.
    PUBLIC_APP_BASE_URL: str = "http://localhost:5173"
    # Auto-disabled in production if the public URLs below are not configured --
    # see disable_mcp_without_public_urls.
    MCP_ENABLED: bool = True
    # Kill switch: with this off, write tools are neither listed nor callable, even for
    # a token that was granted invoicing:write.
    MCP_WRITE_ENABLED: bool = False
    # "core" (~35 curated tools) or "all" (every generated tool).
    MCP_DEFAULT_PROFILE: str = "core"
    OAUTH_DCR_ENABLED: bool = True
    OAUTH_ACCESS_TOKEN_TTL_MINUTES: int = 60
    OAUTH_REFRESH_TOKEN_TTL_DAYS: int = 30

    # --- Public share links ---
    # Every one of these has a default: an existing deployment takes an image with
    # this feature and keeps working without touching its secret.
    SHARE_LINKS_ENABLED: bool = True
    SHARE_AD_ENABLED: bool = True
    SHARE_AD_BRAND_NAME: str = "Simple Invoicings"
    # Deliberately contextual: the reader has just looked at a clean invoice, so
    # the pitch is that document, not a generic feature list.
    SHARE_AD_HEADLINE: str = "Invoices this clean, in two minutes."
    SHARE_AD_TAGLINE: str = (
        "GST-ready invoicing, inventory and ledgers \u2014 built for small "
        "businesses and freelancers."
    )
    SHARE_AD_WEBSITE: str = "https://simpleinvoicings.com"
    # Comma-separated trust chips; blank hides the row.
    SHARE_AD_CHIPS: str = "1 month free,No credit card,GST-ready"
    SHARE_AD_CTA_LABEL: str = "Chat on WhatsApp"
    SHARE_AD_FOOTNOTE: str = "Try free for 1 month"
    # Both published on simpleinvoicings.com. Each line renders only when set,
    # so blanking either one degrades cleanly rather than leaving dead UI.
    SHARE_AD_PHONE: str = "+91 98710 52105"
    SHARE_AD_WHATSAPP: str = "919871052105"

    @property
    def MCP_RESOURCE_URI(self) -> str:
        """Canonical RFC 8707 resource identifier for the MCP endpoint."""
        return f"{self.PUBLIC_API_BASE_URL.rstrip('/')}/mcp"

    @model_validator(mode="after")
    def validate_smtp_key_in_production(self):
        if self.ENVIRONMENT == "production" and not self.SMTP_ENCRYPTION_KEY:
            raise ValueError("SMTP_ENCRYPTION_KEY is required in production environment")
        return self

    @model_validator(mode="after")
    def disable_mcp_without_public_urls(self):
        """Turn MCP off rather than refusing to boot when it is misconfigured.

        MCP is an optional add-on. An earlier version of this raised here, which
        meant every existing production deployment crash-looped the moment it took
        an image containing this feature, because the two new variables were not in
        its secret yet. Taking a working invoicing app offline over an unconfigured
        optional feature is the wrong trade: degrade instead, and say so loudly.

        The https requirement is real, not cosmetic -- OAuth discovery documents
        publish these URLs and access tokens are audience-bound to them -- so MCP
        stays off until they are set, but the rest of the app serves normally.
        """
        if not self.MCP_ENABLED or self.ENVIRONMENT != "production":
            return self

        bad = [
            name
            for name in ("PUBLIC_API_BASE_URL", "PUBLIC_APP_BASE_URL")
            if not getattr(self, name).startswith("https://")
        ]
        if bad:
            object.__setattr__(self, "MCP_ENABLED", False)
            print(
                "⚠️  MCP disabled: " + " and ".join(bad) + " must be set to the "
                "public https:// origin(s) of this deployment. The app is running "
                "normally; MCP and OAuth endpoints are not mounted."
            )
        return self

    class Config:
        env_file = str(env_file_path)
        case_sensitive = False
        extra = "ignore"


settings = Settings()

# Log which environment is being used
print(f"🚀 Backend running in {settings.ENVIRONMENT} mode (loaded from {env_file_path})")
