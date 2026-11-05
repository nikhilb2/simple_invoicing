import os
import hashlib
import importlib.util
import math
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text

from src.api.routes import auth, users, products, inventory, invoices, ledgers, company, payments, smtp, email as email_routes, shortcuts, invoice_series as invoice_series_routes, financial_years as financial_years_routes
from src.api.routes import auth, users, products, inventory, invoices, ledgers, company, payments, smtp, email as email_routes, shortcuts, invoice_series as invoice_series_routes, financial_years as financial_years_routes, credit_notes as credit_notes_routes, backups as backups_routes, company_accounts as company_accounts_routes, bom as bom_routes, email_logs as email_logs_routes, api_keys as api_keys_routes, dashboard as dashboard_routes, analytics as analytics_routes, marketplace as marketplace_routes, serials as serials_routes, oauth as oauth_routes, well_known as well_known_routes, share as share_routes, public_share as public_share_routes, eway_bill as eway_bill_routes, quotations as quotations_routes, gstr3b as gstr3b_routes
from src.mcp_server import register_mcp
from src.services.inventory_service import InsufficientStockError
from src.core.analytics import (
    bind_request,
    client_ip_from_request,
    client_kind_from_headers,
    shutdown_analytics,
    track_exception,
)
from src.core.config import settings
from src.services.backup_scheduler import start_scheduler, stop_scheduler
from src.db.base import Base
from src.db.rls import check_app_role_or_raise, ensure_row_level_security
from src.db.session import engine, migration_engine
# Import all models to register them with declarative_base
import src.models  # noqa: F401

# DDL runs as the owner (MIGRATION_DATABASE_URL, else DATABASE_URL). In shared
# hosting the app's own role cannot create tables, and must not own them: an
# owner is not constrained by row-level security.
Base.metadata.create_all(bind=migration_engine)


def run_pending_migrations() -> None:
    """Auto-apply pending migrations on startup (same as `python migrate.py up`)."""
    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        return

    with migration_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                name VARCHAR NOT NULL UNIQUE,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

        applied = {
            row[0]
            for row in conn.execute(text("SELECT name FROM _migrations")).fetchall()
        }

        files = sorted(
            f for f in migrations_dir.iterdir()
            if f.suffix == ".py" and f.name != "__init__.py"
        )

        for migration_file in files:
            if migration_file.stem in applied:
                continue

            spec = importlib.util.spec_from_file_location(migration_file.stem, migration_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            print(f"  ▸ Applying migration {migration_file.stem}...")
            module.up(conn)
            conn.execute(
                text("INSERT INTO _migrations (name) VALUES (:name)"),
                {"name": migration_file.stem},
            )

    print("✓ Database migrations up to date.")


run_pending_migrations()


def secure_shared_hosting_database() -> None:
    """Shared hosting: make sure RLS is on, then refuse to boot if it cannot bite.

    The first step runs as the owner and is a no-op on an up-to-date database
    (src/db/rls.py). The second runs as the APP role and raises -- stopping the
    process -- when that role is a superuser, has BYPASSRLS, owns a protected
    table, or lacks its grants: in each case the policies would be silently off
    or the app broken, and tenants would only be kept apart by application code.
    """
    if not settings.is_shared_hosting:
        return
    with migration_engine.begin() as conn:
        for statement in ensure_row_level_security(conn):
            print(f"  ▸ {statement.split(' USING ')[0]}")
    if not settings.RLS_BOOT_CHECK:
        print("⚠ RLS_BOOT_CHECK is off: the app role is NOT checked against row-level security.")
        return
    with engine.connect() as conn:
        check_app_role_or_raise(conn)
        role = conn.execute(text("SELECT current_user")).scalar()
    print(f"✓ Row-level security enforced for database role {role!r}.")


secure_shared_hosting_database()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Starts the nightly backup loop, and drains the PostHog queue on the way out.

    The backup scheduler belongs here rather than at import time because it needs a
    running event loop, and it is started before yield so the first request is
    already served by a process that has its timer armed. It never raises: a
    disabled or misconfigured schedule logs and leaves the app otherwise untouched.

    On the way down, shutting the PostHog queue means events from a pod's last
    seconds are not lost. Note that ``tests/conftest.py`` builds a bare
    ``TestClient(app)``, which never runs a lifespan -- fine here, and deliberate
    for the scheduler: a test suite must not start dumping the database on a timer.
    """
    start_scheduler()
    yield
    await stop_scheduler()
    shutdown_analytics()


app = FastAPI(
    title="Simple Invoicing API",
    version="0.1.0",
    description=(
        "API for Simple Invoicing: create and manage GST invoices, ledgers, "
        "payments, products, inventory, and related business documents. "
        "Most endpoints require authentication: sign in at "
        "POST /api/auth/login for a JWT bearer token, or use an API key. "
        "Public share links (/s/{token}) and GET /api/health need no "
        "authentication."
    ),
    contact={
        "name": "Simple Invoicing",
        "url": "https://github.com/nikhilb2/simple_invoicing",
    },
    license_info={
        "name": "MIT",
        "url": "https://github.com/nikhilb2/simple_invoicing/blob/main/LICENSE",
    },
    openapi_tags=[
        {"name": "auth", "description": "Sign-in, sign-out, and current-user endpoints."},
        {"name": "users", "description": "User accounts and roles."},
        {"name": "products", "description": "Product catalogue."},
        {"name": "inventory", "description": "Stock levels and inventory movements."},
        {"name": "bom", "description": "Bills of materials for products."},
        {"name": "invoices", "description": "GST invoices and their lifecycle."},
        {"name": "ledgers", "description": "Customer and supplier ledgers."},
        {"name": "company", "description": "Company profile and settings."},
        {"name": "company-accounts", "description": "Company bank and account details."},
        {"name": "payments", "description": "Payments against invoices and ledgers."},
        {"name": "smtp", "description": "SMTP configuration for outgoing mail."},
        {"name": "email", "description": "Send invoices, statements, and payment reminders by email."},
        {"name": "shortcuts", "description": "Per-user keyboard shortcuts."},
        {"name": "invoice-series", "description": "Numbering series for invoices."},
        {"name": "financial-years", "description": "Financial year definitions."},
        {"name": "credit-notes", "description": "Credit notes against invoices."},
        {"name": "backups", "description": "Database backups and restores."},
        {"name": "email-logs", "description": "Log of sent emails."},
        {"name": "api-keys", "description": "API keys for programmatic access."},
        {"name": "dashboard", "description": "Dashboard metrics."},
        {"name": "analytics", "description": "Sales analytics and reports."},
        {"name": "marketplace", "description": "Marketplace connection settings."},
        {"name": "serials", "description": "Serial-number scanning and tracking."},
        {"name": "share", "description": "Share links for invoices and documents."},
        {"name": "public-share", "description": "Public, unauthenticated invoice share pages."},
        {"name": "oauth", "description": "OAuth authorization server for MCP clients."},
        {"name": "well-known", "description": "OAuth discovery documents (RFC 8414 / RFC 9728)."},
        {"name": "health", "description": "Service health check."},
    ],
    lifespan=lifespan,
)


def _json_safe(value):
    """Make validation error payloads JSON-serializable.

    Python's JSON decoder accepts NaN/Infinity, and Pydantic may echo them in
    ``input``. Those values cannot be written as JSON, so the default 422
    handler crashes with 500. Stringify non-finite floats instead.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe(jsonable_encoder(exc.errors()))},
    )


@app.exception_handler(InsufficientStockError)
async def insufficient_stock_error(
    request: Request, exc: InsufficientStockError
) -> JSONResponse:
    # Same status and `detail` string as any other 400, plus the fields a client needs
    # to offer "add stock" for the product that fell short.
    return JSONResponse(status_code=exc.status_code, content=exc.body())


def get_cors_origins() -> list[str]:
    # Allow local dev and production frontend by default.
    default_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://invoicing.nikhilbhatia.com",
    ]

    raw_origins = os.getenv("CORS_ORIGINS", "")
    if not raw_origins.strip():
        return default_origins

    parsed_origins = [origin.strip().rstrip("/") for origin in raw_origins.split(",") if origin.strip()]
    return parsed_origins or default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # A browser-based MCP client has to read the 401 challenge to discover where
    # the authorization server is. Without this it never starts the OAuth flow --
    # the failure looks like "works in curl, fails in the browser".
    expose_headers=["WWW-Authenticate", "Mcp-Session-Id", "MCP-Protocol-Version"],
)


# Holds the OAuth state, nonce and PKCE verifier between /auth/oauth/<p>/login and
# its callback -- Authlib keeps them in request.session, and comparing the state
# that comes back against this cookie is what defeats CSRF on the callback. It is
# nothing else: the app's own sessions are bearer tokens, not cookies.
#   - Its own cookie name, so it cannot collide with anything the SPA sets.
#   - SameSite=Lax: the provider sends the user back with a top-level GET, which
#     Lax still carries; a cross-site POST or subresource request does not.
#   - Ten minutes: a sign-in that takes longer simply starts again.
#   - A key derived from SECRET_KEY rather than SECRET_KEY itself, so the same
#     bytes never sign both a JWT and a cookie.
app.add_middleware(
    SessionMiddleware,
    secret_key=hashlib.sha256(b"oauth-session:" + settings.SECRET_KEY.encode()).hexdigest(),
    session_cookie="si_oauth_state",
    max_age=600,
    same_site="lax",
    https_only=settings.ENVIRONMENT == "production",
)


@app.middleware("http")
async def analytics_context(request, call_next):
    """Carries the browser's replay session onto this request's server events.

    The browser records replays but captures no product events; those are
    captured here. PostHog stitches an event to a recording by its $session_id,
    so the SPA sends its current session on every API call and the handlers that
    capture events attach it. Without this the recording and the events it
    produced never line up on one timeline.

    The header is advisory. A request without it -- the MCP connector, an API
    key, curl -- still captures its events, just with nothing to pin them to.

    The caller's IP is bound here too, and it is the only thing that gives an
    event a location. PostHog geolocates whatever address it sees, which for a
    server-side event is this pod -- so the client disables GeoIP wholesale and
    the capture path re-enables it per event, against the address bound here.

    This is also where unhandled exceptions are reported, replacing the 5xx
    reporting the browser's axios interceptor used to do. Only genuine crashes
    reach here: FastAPI turns a deliberate `raise HTTPException(...)` into a
    response further in, which is the right split -- a 400 is the app telling a
    user they got something wrong, not a fault.
    """
    bind_request(
        request.headers.get("X-PostHog-Session-Id"),
        client_kind_from_headers(request.headers),
        client_ip_from_request(request),
    )

    try:
        return await call_next(request)
    except Exception as exc:
        track_exception(
            exc,
            properties={
                "request_url": request.url.path,
                "request_method": request.method,
            },
        )
        raise

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["inventory"])
app.include_router(bom_routes.router, prefix="/api/bom", tags=["bom"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["invoices"])
app.include_router(ledgers.router, prefix="/api/ledgers", tags=["ledgers"])
app.include_router(gstr3b_routes.router, prefix="/api/ledgers/tax-ledger/gstr3b", tags=["ledgers"])
app.include_router(company.router, prefix="/api/company", tags=["company"])
app.include_router(company_accounts_routes.router, prefix="/api/company-accounts", tags=["company-accounts"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(smtp.router, prefix="/api/smtp-configs", tags=["smtp"])
app.include_router(email_routes.router, prefix="/api/email", tags=["email"])
app.include_router(shortcuts.router, prefix="/api/shortcuts", tags=["shortcuts"])
app.include_router(invoice_series_routes.router, prefix="/api/invoice-series", tags=["invoice-series"])
app.include_router(financial_years_routes.router, prefix="/api/financial-years", tags=["financial-years"])
app.include_router(credit_notes_routes.router, prefix="/api/credit-notes", tags=["credit-notes"])
app.include_router(quotations_routes.router, prefix="/api/quotations", tags=["quotations"])
app.include_router(backups_routes.router, prefix="/api/backups", tags=["backups"])
app.include_router(email_logs_routes.router, prefix="/api/email-logs", tags=["email-logs"])
app.include_router(api_keys_routes.router, prefix="/api/api-keys", tags=["api-keys"])
app.include_router(dashboard_routes.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(analytics_routes.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(marketplace_routes.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(serials_routes.router, prefix="/api/serials", tags=["serials"])
app.include_router(share_routes.router, prefix="/api/share", tags=["share"])
app.include_router(eway_bill_routes.router, prefix="/api", tags=["eway-bill"])

# Public share pages. No prefix: the URL that goes into a WhatsApp message is
# https://<tenant-host>/s/<token>, and it has to be short and typo-proof.
#
# Mounted a SECOND time under /api as cheap insurance. Every tenant already routes
# /api to this service, whereas /s depends on a per-namespace ingress rule. If that
# rule lags or gets reverted, /s/<token> falls through to the SPA, whose catch-all
# redirects to /, and the customer lands on a LOGIN SCREEN -- the worst possible
# failure mode for a link sent to someone who has no account. The page builds its
# own links from the request path, so both mounts work end to end.
app.include_router(public_share_routes.router, tags=["public-share"])
app.include_router(public_share_routes.router, prefix="/api", tags=["public-share"])
# The OAuth server exists to authorize MCP clients, so it is mounted only when MCP
# is on. Serving discovery documents while MCP is disabled would advertise an
# authorization server at whatever PUBLIC_API_BASE_URL happens to default to and
# send clients somewhere useless.
if settings.MCP_ENABLED:
    app.include_router(oauth_routes.router, prefix="/api/oauth", tags=["oauth"])
    # Discovery documents must be served from the ORIGIN ROOT, not under /api:
    # RFC 8414 / RFC 9728 anchor them at /.well-known/*, and a client that cannot
    # find them there never learns where the authorization server is. Deployments
    # route the /.well-known prefix to this service alongside /api.
    app.include_router(well_known_routes.router, tags=["well-known"])

# MCP endpoint at /mcp, /mcp/, /api/mcp, /api/mcp/. Registered with add_route rather
# than mount: mount 307s a bare /mcp to /mcp/ and several MCP clients drop the POST
# body on that redirect. add_route also bypasses OpenAPI, so no generated tool can
# ever describe -- or call -- the MCP endpoint itself.
register_mcp(app)

@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}
