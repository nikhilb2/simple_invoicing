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

**Vite Note**: All frontend variables must be prefixed with `VITE_` to be accessible in the code via `import.meta.env`.

### Backend Variables

| Variable | Development | Production | Purpose | Required |
|----------|-------------|-----------|---------|----------|
| `DATABASE_URL` | `postgresql://simple_user:simple_password@localhost:5432/simple_invoicing` | `postgresql://simple_user:simple_password@db:5432/simple_invoicing` | PostgreSQL connection string | ✓ |
| `SECRET_KEY` | `dev-secret-key-change-in-production` | Strong random string (32+ chars) | JWT signing secret | ✓ |
| `ALGORITHM` | `HS256` | `HS256` | JWT algorithm | ✓ |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | `30` | Token expiration time | ✓ |
| `DEBUG` | `true` | `false` | Debug mode (detailed error messages) | ✓ |

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
