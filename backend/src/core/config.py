import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings


logger = logging.getLogger(__name__)


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

    # --- PostHog product analytics ---
    # Events are captured server-side; the browser only records replays. Leave the
    # key blank and the app runs with analytics off, silently, in every
    # environment -- see src/core/analytics.py.
    POSTHOG_PROJECT_API_KEY: str | None = None
    POSTHOG_HOST: str = "https://eu.i.posthog.com"

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
    # The price, split so the panel can typeset the amount large and the period
    # small beside it. Blank the amount and the whole price line goes.
    SHARE_AD_PRICE: str = "Rs. 299"
    SHARE_AD_PRICE_PERIOD: str = "/month"
    SHARE_AD_PRICE_PREFIX: str = "only"
    # Both published on simpleinvoicings.com. Each line renders only when set,
    # so blanking either one degrades cleanly rather than leaving dead UI.
    SHARE_AD_PHONE: str = "+91 98710 52105"
    SHARE_AD_WHATSAPP: str = "919871052105"

    # --- Automatic backups ---
    # A nightly pg_dump written to BACKUP_DIR by an in-process scheduler. Defaults
    # to midnight IST because that is when every deployment of this app is idle.
    # Note that BACKUP_DIR is container-local and not on a volume, so these are a
    # convenience copy to download, not an offsite backup -- a pod restart clears them.
    AUTO_BACKUP_ENABLED: bool = True
    # 24-hour "HH:MM" in AUTO_BACKUP_TIMEZONE. An unparseable value disables the
    # scheduler with a warning rather than crash-looping the whole app on boot.
    AUTO_BACKUP_TIME: str = "00:00"
    AUTO_BACKUP_TIMEZONE: str = "Asia/Kolkata"
    # How many scheduler-created archives to keep. Files created by hand from the
    # Backups page are never pruned -- only ones the scheduler itself wrote.
    AUTO_BACKUP_KEEP: int = 7
    # Mail each finished archive to the admins. Gated on an active SMTP config
    # existing, so a deployment that never set up email simply never sends.
    AUTO_BACKUP_EMAIL_ENABLED: bool = True
    # Comma-separated override. Blank means "every admin user", which is the right
    # default -- the Backups page is admin-only, so those are already the people
    # trusted with the database.
    AUTO_BACKUP_EMAIL_TO: str = ""
    # Cap on the RAW archive size. Base64 inflates an attachment by about a third,
    # so 15 MB here lands near 20 MB on the wire, under the usual 25 MB cap. Past
    # this the mail still goes out, just without the attachment.
    AUTO_BACKUP_EMAIL_MAX_MB: int = 15

    # --- UPI ---
    # Kill switch for the pay-by-UPI block on public share pages. Kept separate from
    # SHARE_LINKS_ENABLED because a deployment outside India wants the share pages
    # and has no use at all for the payment offer.
    UPI_QR_ENABLED: bool = True

    # --- Deployment mode / public signup ---
    # "single_tenant" is every per-customer deployment: one company set per
    # database, every user reaches every company, global roles apply -- exactly
    # the behaviour from before this setting existed. "shared_hosting" is the one
    # public instance: a user reaches only the companies they are a member of,
    # the membership role is what counts, and people can register themselves.
    DEPLOYMENT_MODE: Literal["single_tenant", "shared_hosting"] = "single_tenant"
    # DSN used to run DDL on boot. Shared hosting connects as a non-owner role so
    # that row-level security applies to it, and that role cannot create tables.
    # Unset means migrate with DATABASE_URL, as every single-tenant deployment does.
    # Also used for the jobs that must see every row: pg_dump, restore, and the
    # automatic-backup email (see src/db/session.py).
    MIGRATION_DATABASE_URL: str | None = None
    # Shared hosting refuses to boot when DATABASE_URL's role would bypass
    # row-level security (superuser, BYPASSRLS, or owner of a protected table),
    # because then every policy is silently off. Turn this off ONLY to run shared
    # hosting locally against a superuser; never in a real deployment.
    RLS_BOOT_CHECK: bool = True

    # Platform mailer. Carries account-lifecycle mail (address verification, password
    # reset) in either mode, because a person who is registering has no company yet to
    # send from. On a shared host it also carries all tenant mail, because nobody there
    # hands over SMTP credentials. Any SMTP relay works, e.g. smtp-relay.brevo.com.
    PLATFORM_SMTP_HOST: str | None = None
    PLATFORM_SMTP_PORT: int = 587
    PLATFORM_SMTP_USERNAME: str | None = None
    PLATFORM_SMTP_PASSWORD: str | None = None
    PLATFORM_SMTP_FROM_EMAIL: str | None = None
    PLATFORM_SMTP_FROM_NAME: str = "Simple Invoicing"
    PLATFORM_SMTP_USE_STARTTLS: bool = True
    # Shared hosting only: emails one company may send in 24 hours. Every tenant
    # spends the same relay allowance and sender reputation.
    TENANT_EMAIL_DAILY_LIMIT: int = 50

    # Sign in with Google. Both must be set for the provider to be offered.
    OAUTH_GOOGLE_CLIENT_ID: str | None = None
    OAUTH_GOOGLE_CLIENT_SECRET: str | None = None

    # Shared hosting only: how many companies one user may create. Single-tenant
    # deployments keep the global cap in global_settings.max_companies.
    MAX_COMPANIES_PER_USER: int = 3
    # Shared hosting only: comma-separated emails of the people who run the
    # deployment. They alone reach the surfaces that span every tenant -- backups
    # (a pg_dump of the whole database), the SMTP config, the user list and
    # marketplace sync-all. Empty means nobody. Single-tenant deployments ignore
    # it and keep their usual admin role checks.
    PLATFORM_ADMIN_EMAILS: str = ""

    @property
    def MCP_RESOURCE_URI(self) -> str:
        """Canonical RFC 8707 resource identifier for the MCP endpoint."""
        return f"{self.PUBLIC_API_BASE_URL.rstrip('/')}/mcp"

    @property
    def is_shared_hosting(self) -> bool:
        return self.DEPLOYMENT_MODE == "shared_hosting"

    @property
    def password_signup_enabled(self) -> bool:
        """Email + password registration needs somewhere to send the verification mail."""
        return self.is_shared_hosting and bool(self.PLATFORM_SMTP_HOST)

    @property
    def google_auth_enabled(self) -> bool:
        """Google login for existing users. Works in either mode."""
        return bool(self.OAUTH_GOOGLE_CLIENT_ID and self.OAUTH_GOOGLE_CLIENT_SECRET)

    @property
    def google_signup_enabled(self) -> bool:
        """Creating new users through Google. Google proves the address, so no SMTP needed."""
        return self.is_shared_hosting and self.google_auth_enabled

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
            logger.warning(
                "⚠️  MCP disabled: " + " and ".join(bad) + " must be set to the "
                "public https:// origin(s) of this deployment. The app is running "
                "normally; MCP and OAuth endpoints are not mounted."
            )
        return self

    @model_validator(mode="after")
    def warn_signup_disabled_without_platform_smtp(self):
        """Boot, but say so, when shared hosting has no platform mailer.

        Registering people who can never receive their verification mail is worse
        than not registering them, so password signup stays off until
        PLATFORM_SMTP_HOST is set. Like the MCP check above, this degrades rather
        than refusing to boot: existing users can still sign in and work.
        """
        if self.is_shared_hosting and not self.PLATFORM_SMTP_HOST:
            logger.warning(
                "⚠️  Signup disabled: DEPLOYMENT_MODE=shared_hosting but "
                "PLATFORM_SMTP_HOST is not set, so no mail can be sent. Email/password "
                "registration and tenant email are off; the app is otherwise running "
                "normally."
            )
        return self

    class Config:
        env_file = str(env_file_path)
        case_sensitive = False
        extra = "ignore"


settings = Settings()

# Log which environment is being used
print(f"🚀 Backend running in {settings.ENVIRONMENT} mode (loaded from {env_file_path})")
