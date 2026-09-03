import os
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.api.routes import auth, users, products, inventory, invoices, ledgers, company, payments, smtp, email as email_routes, shortcuts, invoice_series as invoice_series_routes, financial_years as financial_years_routes
from src.api.routes import auth, users, products, inventory, invoices, ledgers, company, payments, smtp, email as email_routes, shortcuts, invoice_series as invoice_series_routes, financial_years as financial_years_routes, credit_notes as credit_notes_routes, backups as backups_routes, company_accounts as company_accounts_routes, bom as bom_routes, email_logs as email_logs_routes, api_keys as api_keys_routes, dashboard as dashboard_routes, analytics as analytics_routes, marketplace as marketplace_routes, serials as serials_routes, oauth as oauth_routes, well_known as well_known_routes, share as share_routes, public_share as public_share_routes
from src.mcp_server import register_mcp
from src.core.config import settings
from src.db.base import Base
from src.db.session import engine
# Import all models to register them with declarative_base
import src.models  # noqa: F401

Base.metadata.create_all(bind=engine)


def run_pending_migrations() -> None:
    """Auto-apply pending migrations on startup (same as `python migrate.py up`)."""
    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        return

    with engine.begin() as conn:
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

app = FastAPI(title="Simple Invoicing API", version="0.1.0")


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

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["inventory"])
app.include_router(bom_routes.router, prefix="/api/bom", tags=["bom"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["invoices"])
app.include_router(ledgers.router, prefix="/api/ledgers", tags=["ledgers"])
app.include_router(company.router, prefix="/api/company", tags=["company"])
app.include_router(company_accounts_routes.router, prefix="/api/company-accounts", tags=["company-accounts"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(smtp.router, prefix="/api/smtp-configs", tags=["smtp"])
app.include_router(email_routes.router, prefix="/api/email", tags=["email"])
app.include_router(shortcuts.router, prefix="/api/shortcuts", tags=["shortcuts"])
app.include_router(invoice_series_routes.router, prefix="/api/invoice-series", tags=["invoice-series"])
app.include_router(financial_years_routes.router, prefix="/api/financial-years", tags=["financial-years"])
app.include_router(credit_notes_routes.router, prefix="/api/credit-notes", tags=["credit-notes"])
app.include_router(backups_routes.router, prefix="/api/backups", tags=["backups"])
app.include_router(email_logs_routes.router, prefix="/api/email-logs", tags=["email-logs"])
app.include_router(api_keys_routes.router, prefix="/api/api-keys", tags=["api-keys"])
app.include_router(dashboard_routes.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(analytics_routes.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(marketplace_routes.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(serials_routes.router, prefix="/api/serials", tags=["serials"])
app.include_router(share_routes.router, prefix="/api/share", tags=["share"])

# Public share pages. No prefix: the URL that goes into a WhatsApp message is
# https://<tenant-host>/s/<token>, and it has to be short and typo-proof.
#
# Mounted a SECOND time under /api as cheap insurance. Every tenant already routes
# /api to this service, whereas /s depends on a per-namespace ingress rule. If that
# rule lags or gets reverted, /s/<token> falls through to the SPA, whose catch-all
# redirects to /, and the customer lands on a LOGIN SCREEN -- the worst possible
# failure mode for a link sent to someone who has no account. The page builds its
# own links from the request path, so both mounts work end to end.
app.include_router(public_share_routes.router)
app.include_router(public_share_routes.router, prefix="/api")
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
    app.include_router(well_known_routes.router)

# MCP endpoint at /mcp, /mcp/, /api/mcp, /api/mcp/. Registered with add_route rather
# than mount: mount 307s a bare /mcp to /mcp/ and several MCP clients drop the POST
# body on that redirect. add_route also bypasses OpenAPI, so no generated tool can
# ever describe -- or call -- the MCP endpoint itself.
register_mcp(app)

@app.get("/api/health")
def health():
    return {"status": "ok"}
