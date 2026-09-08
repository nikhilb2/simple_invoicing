# Environment Configuration Guide

This document explains how to set up environment variables for development and production environments.

## Quick Start

### For Local Development

1. **Backend**:
   ```bash
   cd backend
   cp .env.example .env.development
   # Update .env.development if needed (defaults work for local dev)
   ```

2. **Frontend**:
   ```bash
   cd frontend
   cp .env.example .env.development
   # Update .env.development if needed (defaults work for local dev)
   ```

3. **Root** (for Docker Compose):
   ```bash
   cp .env.example .env
   # Update .env if deploying with Docker
   ```

### For Production

1. **Backend**:
   ```bash
   cd backend
   cp .env.example .env.production
   # IMPORTANT: Update SECRET_KEY with a strong random value (minimum 32 characters)
   # IMPORTANT: Set DEBUG=false
   ```

2. **Frontend**:
   ```bash
   cd frontend
   cp .env.example .env.production
   # Leave VITE_API_BASE_URL as /api (nginx will proxy to backend)
   ```

3. **Root** (for Docker Compose):
   ```bash
   cp .env.example .env
   # Update all production values
   ```

## Backend Environment Detection

The backend automatically detects which environment to use by checking the `ENVIRONMENT` environment variable.

### How It Works

**File**: [backend/src/core/config.py](backend/src/core/config.py)

```python
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")  # Check env variable, default to development
env_file_path = Path(f".env.{ENVIRONMENT}")            # Load .env.{development|production}
```

**Priority**:
1. Check `ENVIRONMENT` environment variable
2. Default to `development` if not set
3. Load `.env.{ENVIRONMENT}` file (e.g., `.env.development` or `.env.production`)
4. Fallback to `.env` if environment-specific file doesn't exist

### Quick Start

**Local Development** (automatic):
```bash
# Defaults to development mode, loads .env.development
uvicorn app_main:app --reload
```

**Local Production Testing**:
```bash
export ENVIRONMENT=production
uvicorn app_main:app
```

**Docker** (automatic):
```bash
docker-compose up -d
# Sets ENVIRONMENT=production, loads .env.production
```

### Startup Output
```
🚀 Backend running in development mode (loaded from .env.development)
```

## Environment Files by Directory

### `/frontend/.env.development`
Local frontend development with direct backend connection.

```env
VITE_API_BASE_URL=http://localhost:8000/api
VITE_APP_NAME=Simple Invoicing
VITE_LOG_LEVEL=debug
```

**When to use**: Running `npm run dev` locally, backend running on localhost:8000

### `/frontend/.env.production`
Production frontend served via Nginx with API proxy.

```env
VITE_API_BASE_URL=/api
VITE_APP_NAME=Simple Invoicing
VITE_LOG_LEVEL=error
```

**When to use**: Building with `npm run build`, served via Docker/Nginx

**Note**: Uses `/api` relative path because Nginx proxies `/api/*` requests to the backend container.

### `/backend/.env.development`
Local backend development with local PostgreSQL.

```env
DATABASE_URL=postgresql://simple_user:simple_password@localhost:5432/simple_invoicing
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
DEBUG=true
```

**When to use**: Running `uvicorn app_main:app` locally, PostgreSQL running on localhost:5432

### `/backend/.env.production`
Production backend running in Docker with remote database.

```env
DATABASE_URL=postgresql://simple_user:simple_password@db:5432/simple_invoicing
SECRET_KEY=your-secure-secret-key-here-minimum-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
DEBUG=false
```

**When to use**: Running via Docker Compose, DATABASE_URL points to internal `db` service

**Important**: 
- Replace `SECRET_KEY` with a strong, randomly generated string (minimum 32 characters)
- Set `DEBUG=false` in production
- Use strong database credentials

### `/.env`
Root-level environment file for Docker Compose orchestration.

```env
FRONTEND_PORT=5173
VITE_API_BASE_URL=http://localhost:8000/api
BACKEND_PORT=8000
DATABASE_URL=postgresql://simple_user:simple_password@localhost:5432/simple_invoicing
POSTGRES_USER=simple_user
POSTGRES_PASSWORD=simple_password
POSTGRES_DB=simple_invoicing
COMPOSE_PROJECT_NAME=simple_invoicing

# Host-side port mappings (optional — override if a port is already in use)
DB_HOST_PORT=5432
BACKEND_HOST_PORT=8000
FRONTEND_HOST_PORT=80
FRONTEND_DEV_HOST_PORT=5173
```

**When to use**: Setting up Docker Compose environment

## Environment Variables Reference

### Frontend Variables

| Variable | Development | Production | Purpose |
|----------|-------------|-----------|---------|
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | `/api` | Backend API endpoint |
| `VITE_APP_NAME` | `Simple Invoicing` | `Simple Invoicing` | App display name |
| `VITE_LOG_LEVEL` | `debug` | `error` | Console logging verbosity |
| `VITE_POSTHOG_PROJECT_TOKEN` | `phc_...` | `phc_...` | PostHog project token (session replay) |
| `VITE_POSTHOG_HOST` | `https://eu.i.posthog.com` | `https://eu.i.posthog.com` | PostHog ingestion host (`us.i.posthog.com` for US Cloud) |

**PostHog Note**: The browser records **session replays** and autocaptures
pageviews and clicks; the app's named product events (`invoice_created`,
`payment_recorded`, …) are captured by the **backend** — see
`POSTHOG_PROJECT_API_KEY` below. Point both halves at the same project: the
browser identifies the operator by email and the backend keys its events by the
same email, so a replay and the events it produced land on one person.

Both variables are optional — leave them blank and the app runs with analytics
disabled, silently and in every environment. Nothing warns you about a missing
token, so if you expect replays and see none, check these two first. The project
token is write-only and ships in the JavaScript bundle, so it is not a secret.
For container builds, pass them as
`--build-arg VITE_POSTHOG_PROJECT_TOKEN=... --build-arg VITE_POSTHOG_HOST=...`;
Vite inlines them at build time, so an already-built image cannot be
reconfigured at runtime.

**Vite Note**: All frontend variables must be prefixed with `VITE_` to be accessible in the code via `import.meta.env`.

### Backend Variables

| Variable | Development | Production | Purpose | Required |
|----------|-------------|-----------|---------|----------|
| `DATABASE_URL` | `postgresql://simple_user:simple_password@localhost:5432/simple_invoicing` | `postgresql://simple_user:simple_password@db:5432/simple_invoicing` | PostgreSQL connection string | ✓ |
| `SECRET_KEY` | `dev-secret-key-change-in-production` | Strong random string (32+ chars) | JWT signing secret | ✓ |
| `ALGORITHM` | `HS256` | `HS256` | JWT algorithm | ✓ |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | `30` | Token expiration time | ✓ |
| `DEBUG` | `true` | `false` | Debug mode (detailed error messages) | ✓ |
| `POSTHOG_PROJECT_API_KEY` | `phc_...` | `phc_...` | PostHog project key — product events are captured server-side | |
| `POSTHOG_HOST` | `https://eu.i.posthog.com` | `https://eu.i.posthog.com` | PostHog ingestion host (`us.i.posthog.com` for US Cloud) | |

**PostHog Note**: Product events live on the backend so that an event fires when
the write actually committed, not when a request appeared to succeed — and so
that the same action taken through the MCP connector or an API key is counted
identically. Every event carries a `client` property of `web`, `mcp` or `api`
saying which. Leave `POSTHOG_PROJECT_API_KEY` blank and the app runs with
analytics off, silently, in every environment. Unlike the `VITE_` pair, these are
read at runtime, so an existing image picks them up from its secret with a
restart — no rebuild.

Events carry the caller's IP as `$ip` so PostHog can resolve a location from
it. Without that they would be geolocated to whichever datacentre the pod runs
in, so GeoIP is disabled client-wide and re-enabled per event, only for events
that actually carry a caller address. The IP is read from `X-Forwarded-For`, so
an ingress that does not set that header leaves every event located at the
cluster's internal address. If you would rather PostHog not retain the address
itself, turn on "Discard client IP data" in the project's settings — the
geolocation is resolved before that discard, so country and city still work.

Public share pages (`/s/<token>`) are counted too — views, PDF downloads and
presses of the ad's WhatsApp button, the last via a redirect through
`/s/<token>/whatsapp` because that page runs no JavaScript. Those readers are the
tenant's customers, so their events are anonymous: no person profile is created
for them.

**Those events carry the full share URL, token included**, so a link can be
opened straight from PostHog. The token is the entire credential for the document
behind it, which makes read access to this PostHog project equivalent to read
access to every document ever shared from the app — grant it on those terms. When
grouping share traffic, break down by the `share_route` property (`/s/:token`,
`/s/:token/pdf`) rather than by URL: the raw URL is one row per link.

The browser sends its replay session id on every API call as
`X-PostHog-Session-Id`, and the backend attaches it to the events that request
produces. That header is the whole link between a recording and its events: drop
it at a proxy and both halves still work, but they no longer line up on one
timeline.

### Automatic Backup Variables

A nightly `pg_dump` written to `BACKUP_DIR`, alongside the archives created by hand from
**Settings → Backups**. It defaults to midnight IST, and **every variable here has a
default** — an existing deployment takes an image with this feature and starts backing up
nightly without touching its secret.

| Variable | Default | Purpose |
|----------|---------|---------|
| `AUTO_BACKUP_ENABLED` | `true` | Master switch. With this off, nothing is scheduled and the Backups page says so; creating a backup by hand still works. |
| `AUTO_BACKUP_TIME` | `00:00` | 24-hour `HH:MM` in `AUTO_BACKUP_TIMEZONE`. An unparseable value turns the scheduler off with an error in the log rather than crash-looping the app. |
| `AUTO_BACKUP_TIMEZONE` | `Asia/Kolkata` | IANA zone the time is read in. An unknown zone falls back to a fixed UTC+05:30 offset, which is exactly right for IST and wrong for anything else. |
| `AUTO_BACKUP_KEEP` | `7` | How many scheduled archives to keep. Pruning matches on the `autobackup_` filename prefix, so a backup **you** created is never deleted by retention. `0` disables pruning entirely. |
| `BACKUP_DIR` | `./backups` | Where archives are written. Read from the process environment, not the settings file. |
| `AUTO_BACKUP_EMAIL_ENABLED` | `true` | Mail each finished archive to the admins. Does nothing unless SMTP is set up, so this is safe to leave on. |
| `AUTO_BACKUP_EMAIL_TO` | *(blank)* | Comma-separated recipients. Blank means **every admin user's email address** — the first is the `To`, the rest are `Cc`. |
| `AUTO_BACKUP_EMAIL_MAX_MB` | `15` | Cap on the **raw** archive size. Base64 inflates an attachment by about a third, so 15 MB lands near 20 MB on the wire, under the usual 25 MB cap. Past this the email still goes out — saying the backup exists and why it is not attached — just without the archive. |

**Emailing the backup.** After each scheduled run the archive is mailed to the admins,
using the same SMTP configuration as invoice email (**Settings → SMTP**). With no active
SMTP config nothing is sent and the Backups page says so — that is a normal state, not an
error. Rows land in `email_logs` with `email_type = automatic_backup`, alongside invoice and
reminder mail.

The attachment is the encrypted archive exactly as the Backups page serves it, so a mailbox
holding it does not expose the database: restoring needs a server holding the same
`BACKUP_ENCRYPTION_KEY`. That is what makes this safe to do unattended — and it is also the
catch, because an archive mailed out of a deployment whose key is later lost is
unrecoverable. Keep `BACKUP_ENCRYPTION_KEY` somewhere you will still have it.

Delivery is reported separately from the backup itself, on the page and in
`GET /api/backups/schedule`. A mail server that is down does not make the archive on disk any
less real, and the two failures need different fixes.

**These archives are not durable storage.** `BACKUP_DIR` is a path inside the container and
nothing mounts a volume there, so every archive — scheduled or manual — is gone when the pod
restarts. Treat the nightly run as a convenience copy to download, not as a disaster-recovery
plan; for that, mount a `PersistentVolumeClaim` at `BACKUP_DIR` or ship the archives offsite.

The scheduler runs in-process, which assumes **one replica** — the deployments here all set
`replicas: 1`. Scale one out and every replica dumps at midnight to its own container-local
disk. That is wasteful rather than destructive, but a scaled-out deployment wants a
`CronJob` or a Postgres advisory lock around the run instead.

There is deliberately **no catch-up run on startup**. Since a restart clears `BACKUP_DIR`
anyway, a catch-up rule would fire on every deploy and a crash-looping pod would dump in a
tight loop. Missing one night after a restart is the cheaper failure.

Progress is visible at **Settings → Backups**: the next scheduled run, whether the last one
succeeded, and an `Automatic`/`Manual` label on each archive in the list. The same data is
served by `GET /api/backups/schedule` (admin only).

### MCP Connector / OAuth Variables

These configure the built-in MCP server and its OAuth 2.1 authorization server, which let
Claude, ChatGPT and other MCP clients connect to this instance.

| Variable | Development | Production | Purpose | Required |
|----------|-------------|-----------|---------|----------|
| `PUBLIC_API_BASE_URL` | `http://localhost:8000` | `https://<your-host>` | Public origin of this API. Doubles as the **OAuth issuer** and the base of the canonical MCP resource URI (`<base>/mcp`). | ✓ when MCP enabled |
| `PUBLIC_APP_BASE_URL` | `http://localhost:5173` | `https://<your-host>` | Public origin of the web app. Used for the OAuth consent redirect and for `search`/`fetch` citation links. | ✓ when MCP enabled |
| `MCP_ENABLED` | `true` | `true` | Mounts the `/mcp` endpoint and the OAuth discovery documents. | |
| `MCP_WRITE_ENABLED` | `false` | `false` | **Kill switch.** With this off, write tools are neither listed nor callable — even for a token that was granted `invoicing:write`. Turn it on deliberately. | |
| `MCP_DEFAULT_PROFILE` | `core` | `core` | `core` exposes a curated tool set; `all` exposes every generated tool. Clients can also request a profile in the connector URL. | |
| `OAUTH_DCR_ENABLED` | `true` | `true` | Allows RFC 7591 dynamic client registration at `POST /api/oauth/register`. Claude and ChatGPT both rely on it. | |
| `OAUTH_ACCESS_TOKEN_TTL_MINUTES` | `60` | `60` | Lifetime of an issued OAuth access token. | |
| `OAUTH_REFRESH_TOKEN_TTL_DAYS` | `30` | `30` | Lifetime of a refresh token. Refresh tokens rotate on every use. | |

**If the two public URLs are not set to `https://` origins in production, MCP and its
OAuth endpoints are automatically disabled** and the app logs a warning on startup and
serves normally. Upgrading an existing deployment to an MCP-capable image therefore never
takes it offline — you opt in by setting these two variables.

**`PUBLIC_API_BASE_URL` must be exact.** It is published in the OAuth discovery documents
and is what access tokens are audience-bound to, so it has to match the URL a user types
into their MCP client, character for character — including the scheme and any port. A
mismatch makes every token fail audience validation with a `401` that looks like a login
loop. Both public URLs must be `https://` in production; the backend refuses to start
otherwise while `MCP_ENABLED` is on.

Deployments serve these extra path prefixes from the backend, alongside `/api`:
`/mcp`, `/.well-known/` and `/s/` (see *Public Share Link Variables* below). The Kubernetes
ingresses and the Vite dev proxy already route them; any other reverse proxy in front of
this app needs the same rules, because OAuth discovery cannot be relocated under `/api`.

### Public Share Link Variables

These control the public, unauthenticated share pages at `https://<tenant-host>/s/<token>` —
the URL an owner pastes into WhatsApp so a customer can view an invoice, statement or
receipt and download its PDF without an account.

**Every variable here has a default.** An existing deployment can take an image containing
this feature without touching its secret and the feature simply works.

| Variable | Default | Purpose |
|----------|---------|---------|
| `SHARE_LINKS_ENABLED` | `true` | Master switch. With this off, `POST /api/share/` returns `403` and every `/s/<token>` URL returns the same uniform `404` an unknown token gets. Existing rows are left alone, so turning it back on restores every live link. |
| `UPI_QR_ENABLED` | `true` | Master switch for the pay-by-UPI block on share pages. Kept separate from `SHARE_LINKS_ENABLED` because a deployment outside India wants the share pages and has no use for the payment offer. With this off, no `upi://` link or QR is produced and `/s/<token>/upi` returns the uniform `404`. |
| `SHARE_AD_ENABLED` | `true` | Renders the Simple Invoicings panel at the bottom of the public page — brand, pitch, price, call-to-action, a restatement of the document above, and the "Powered by" line. Set to `false` for a white-label deployment: with it off the brand name appears nowhere in the response. The panel is **never** stamped into the PDF under any setting. |
| `SHARE_AD_BRAND_NAME` | `Simple Invoicings` | Wordmark shown beside the brand mark. |
| `SHARE_AD_HEADLINE` | `Invoices this clean, in two minutes.` | Headline, rendered in the lime→pink brand gradient. Deliberately contextual: the reader has just looked at a clean invoice. |
| `SHARE_AD_TAGLINE` | `GST-ready invoicing, inventory and ledgers — built for small businesses and freelancers.` | Supporting line under the headline. |
| `SHARE_AD_CHIPS` | `1 month free,No credit card,GST-ready` | Comma-separated trust chips. Blank hides the row. |
| `SHARE_AD_CTA_LABEL` | `Chat on WhatsApp` | Label on the primary gradient button. |
| `SHARE_AD_FOOTNOTE` | `Try free for 1 month` | The eyebrow above the headline — set uppercase and letterspaced in lime, the marketing site's own label treatment. Blank hides it. |
| `SHARE_AD_PRICE` | `Rs. 299` | The amount, set large in the lime→magenta gradient. Blank removes the whole price line, prefix and period with it. |
| `SHARE_AD_PRICE_PERIOD` | `/month` | Set small and muted, tight against the amount. |
| `SHARE_AD_PRICE_PREFIX` | `only` | Uppercase lead-in on the price baseline. |
| `SHARE_AD_WEBSITE` | `https://simpleinvoicings.com` | Link target for the ad. Rendered with `rel="noopener noreferrer nofollow"`, and every public response sends `Referrer-Policy: no-referrer`, so the share token is never handed to this site in a `Referer` header. Because of that the destination sees no referrer, so the link is tagged `utm_source=share_page&utm_medium=referral&utm_campaign=document_share&utm_content=<invoice\|ledger_statement\|payment\|unavailable>` — set this to a URL that already carries `utm_` params to keep your own tags instead. |
| `SHARE_AD_PHONE` | `+91 98710 52105` | Sales number, rendered as a `tel:` button. Published on simpleinvoicings.com. Blank removes the button rather than leaving an empty `tel:`. |
| `SHARE_AD_WHATSAPP` | `919871052105` | Digits for the `https://wa.me/<n>` primary CTA. Blank falls back to making the website the primary CTA. |

**`/s/` must be routed to the backend.** The share URL is deliberately short so it survives
being typed and forwarded, which means the ingress has to send `/s/` to this service rather
than to the SPA. If it does not, `/s/<token>` falls through to the frontend's catch-all and
the recipient — who has no account — lands on a login screen. As a hedge, the same routes
are also mounted under `/api/s/<token>`, which every tenant already routes; the page builds
its own links from the request path, so both forms work end to end.

**The share URL origin does not come from `PUBLIC_APP_BASE_URL` unless that is an `https://`
origin.** It defaults to `http://localhost:5173` and several tenants never set it, so
trusting it blindly would paste a localhost URL into a customer's chat. When it is not an
https origin the backend derives the origin from the request the owner's own browser made
(`X-Forwarded-Proto` and `Host`).

### Database Variables (Docker Compose)

| Variable | Purpose |
|----------|---------|
| `POSTGRES_USER` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_DB` | Default database name |
| `POSTGRES_PORT` | PostgreSQL port (5432) |
### Docker Host Port Variables

These control which **host** port each container is exposed on. They only affect how you access services from your machine — internal container-to-container communication is unaffected.

| Variable | Default | Maps to | Purpose |
|----------|---------|---------|----------|
| `DB_HOST_PORT` | `5432` | container port `5432` | Host port for the PostgreSQL service |
| `BACKEND_HOST_PORT` | `8000` | container port `8000` | Host port for the FastAPI backend |
| `FRONTEND_HOST_PORT` | `80` | container port `80` | Host port for the production frontend (Nginx) |
| `FRONTEND_DEV_HOST_PORT` | `5173` | container port `5173` | Host port for the Vite dev server |

**Override locally** when a port is already in use on your machine. Add the variable to your local `.env` file (never commit your `.env`):

```dotenv
# .env (local overrides — git-ignored)
FRONTEND_DEV_HOST_PORT=5174
DB_HOST_PORT=5433
```

All variables use Docker Compose's `${VAR:-default}` syntax, so omitting a variable from `.env` falls back silently to the default — no breakage for anyone who hasn't set them.
## How to Generate a Secure SECRET_KEY

For production, generate a cryptographically strong secret:

```bash
# Using Python
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Using OpenSSL
openssl rand -hex 32

# Using /dev/urandom
head -c 32 /dev/urandom | base64
```

Copy the output to `backend/.env.production`:
```env
SECRET_KEY=your-generated-string-here
```

## Development Workflow

### Running Locally without Docker

1. **Setup PostgreSQL** (install locally or use Docker for DB only):
   ```bash
   docker run -d --name postgres \
     -e POSTGRES_USER=simple_user \
     -e POSTGRES_PASSWORD=simple_password \
     -e POSTGRES_DB=simple_invoicing \
     -p 5432:5432 \
     postgres:16-alpine
   ```

2. **Backend**:
   ```bash
   cd backend
   cp .env.example .env.development
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app_main:app --reload
   ```

3. **Frontend** (new terminal):
   ```bash
   cd frontend
   cp .env.example .env.development
   npm install
   npm run dev
   ```

4. **Access**:
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

### Running with Docker Compose

1. **Setup**:
   ```bash
   cp .env.example .env
   # Edit .env if needed
   ```

2. **Start services**:
   ```bash
   docker-compose up -d
   ```

3. **Access**:
   - Frontend: http://localhost (port 80)
   - Backend API: http://localhost:8000
   - Database: localhost:5432

## Production Deployment Checklist

- [ ] Backend `.env.production`:
  - [ ] `SECRET_KEY` is strong (32+ random characters)
  - [ ] `DEBUG=false`
  - [ ] `DATABASE_URL` points to production database
  - [ ] `ACCESS_TOKEN_EXPIRE_MINUTES` is appropriate (30-120)

- [ ] Frontend `.env.production`:
  - [ ] `VITE_API_BASE_URL=/api` (or your domain)
  - [ ] `VITE_LOG_LEVEL=error`

- [ ] Docker Compose:
  - [ ] Database credentials are strong
  - [ ] `.env` file is not committed to version control
  - [ ] All services have proper resource limits
  - [ ] Health checks pass

- [ ] Security:
  - [ ] `.env` and `.env.*` files are in `.gitignore`
  - [ ] Database backups are configured
  - [ ] HTTPS is enabled (via reverse proxy/CDN)
  - [ ] CORS origins are restricted

## GitIgnore

Add these to `.gitignore` to prevent committing sensitive data:

```
# Environment files
.env
.env.*.local
.env.production
.env.development

# Node/Python
node_modules/
dist/
build/
.venv/
venv/
__pycache__/

# IDE
.vscode/
.idea/
*.swp
*.swo
```

## Troubleshooting

### Frontend can't reach backend
1. Check `VITE_API_BASE_URL` is correct
2. In dev: ensure backend is running on `localhost:8000`
3. In Docker: ensure both services are on same network
4. Check browser console for actual API URL being used

### Backend won't start
1. Check `DATABASE_URL` is correct and database is running
2. Check `SECRET_KEY` is set
3. View logs: `docker-compose logs backend`
4. Verify PostgreSQL is accessible

### Database connection failed
1. Check `POSTGRES_USER` and `POSTGRES_PASSWORD` match
2. Verify PostgreSQL is running: `docker-compose logs db`
3. Test connection: `psql postgresql://user:pass@localhost:5432/db`

## Environment-Specific Notes

### Development
- Use localhost URLs for easy debugging
- Enable debug logs for troubleshooting
- Use short token expiration for testing
- Minimal security required

### Staging
- Use subdomain/staging server URLs
- Enable limited debug logs
- Use reasonable token expiration (60 minutes)
- Use staging database credentials

### Production
- Use domain/CDN URLs
- Disable all debug logs
- Use high-security SECRET_KEY
- Use production database with backups
- Implement rate limiting
- Use HTTPS only
- Monitor logs and errors

## References

- [Vite Environment Variables](https://vitejs.dev/guide/env-and-mode.html)
- [FastAPI Settings Management](https://fastapi.tiangolo.com/advanced/settings/)
- [PostgreSQL Connection Strings](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING)
- [JWT Security Best Practices](https://tools.ietf.org/html/rfc8725)
