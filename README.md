<div align="center">

# Simple Invoicing

**Modern, open-source invoicing & accounting system for small businesses**

A Tally-inspired full-stack application with dual-voucher accounting, inventory management, ledger statements, and day-book registers.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Frontend: React](https://img.shields.io/badge/Frontend-React-61DAFB?logo=react)](https://react.dev/)
[![DB: PostgreSQL](https://img.shields.io/badge/DB-PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

</div>

---

## Features

- **Dual-Voucher Accounting** — Sales and Purchase invoices with automatic inventory effects
- **Ledger Statements** — Period-based financial views per account (Tally-style)
- **Day Book Register** — Cross-ledger voucher register for reconciliation
- **Inventory Management** — Real-time stock tracking with automatic adjustments
- **PDF Invoice Generation** — Generate professional invoices with WeasyPrint
- **GST Compliance** — Built-in tax fields and GST rate support
- **Role-Based Access** — Admin, Manager, and Staff roles with JWT auth
- **Payment Tracking** — Record and track payments against invoices
- **Docker Ready** — One-command dev and production setup
- **E2E Tested** — Playwright test suite for critical workflows

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, FastAPI, SQLAlchemy 2.0 |
| **Frontend** | React 18, TypeScript, Tailwind CSS, Framer Motion |
| **Database** | PostgreSQL 16 |
| **Auth** | JWT with bcrypt password hashing |
| **PDF** | WeasyPrint |
| **Testing** | Playwright (E2E) |
| **Deploy** | Docker, Docker Compose, Kubernetes configs included |

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- Or: Python 3.11+, Node.js 20+, PostgreSQL 16+

### Option 1: Docker (recommended)

```bash
# Clone the repository
git clone https://github.com/nikhilb2/simple_invoicing.git
cd simple_invoicing

# Copy environment files
cp .env.example .env
cp backend/.env.example backend/.env.development
cp frontend/.env.example frontend/.env.development

# Start development environment
make dev

# Seed the admin user
make seed
```

The app will be available at:
- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs (Swagger)**: http://localhost:8000/docs

### Option 2: Manual Setup

<details>
<summary>Click to expand manual setup instructions</summary>

**Backend:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.development
uvicorn app_main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env.development
npm run dev
```

**Seed admin user:**

```bash
cd backend
python seed_admin.py
```

</details>

### Default Credentials

After seeding, log in with:
- **Email:** `admin@simple.dev`
- **Password:** `Admin@123`

> ⚠️ Change these immediately in production!

## Project Structure

```
simple_invoicing/
├── backend/                # FastAPI application
│   ├── src/
│   │   ├── api/routes/     # REST API endpoints
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   ├── services/       # Business logic layer
│   │   └── core/           # Config, security, database
│   ├── migrations/         # Database migrations
│   └── requirements.txt
├── frontend/               # React SPA
│   ├── src/
│   │   ├── pages/          # Route-level components
│   │   ├── components/     # Shared UI components
│   │   ├── api/            # Axios client & interceptors
│   │   ├── context/        # React context (auth)
│   │   └── types/          # TypeScript type definitions
│   ├── e2e/                # Playwright E2E tests
│   └── package.json
├── docker-compose.yml      # Multi-container orchestration
├── Makefile                # Developer shortcuts
├── DOCKER.md               # Docker guide
├── ENV.md                  # Environment variable guide
└── project.md              # Architecture and API context
```

## API Overview

| Endpoint | Description |
|----------|-------------|
| `POST /api/auth/login` | Authenticate and get JWT token |
| `GET/POST /api/products/` | Product catalog CRUD |
| `GET/POST /api/invoices/` | Create sales/purchase invoices |
| `GET/POST /api/ledgers/` | Ledger account management |
| `GET /api/ledgers/{id}/statement` | Period-based ledger statement |
| `GET /api/ledgers/day-book` | Cross-ledger voucher register |
| `GET /api/inventory/` | Stock levels and adjustments |
| `GET/POST /api/users/` | User management (admin) |

Full interactive docs available at `/docs` (Swagger UI) when the backend is running.

## Development

```bash
make dev                              # Start dev environment (Docker)
make test                             # Run all tests
make lint                             # Lint backend and frontend
make migrate                          # Run all pending migrations
make migrate-status                   # Show migration status
make migrate-down                     # Roll back last migration
make migrate-down-all                 # Roll back all migrations
make migrate-create name=<name>       # Create a new migration file
make seed                             # Seed admin user
make logs                             # Tail all service logs
make down                             # Stop all services
```

See the [Makefile](Makefile) for all available commands.

## Roadmap

- [ ] Multi-currency support
- [ ] Email invoice delivery
- [ ] Dashboard analytics and charts
- [ ] CSV/Excel export
- [ ] Recurring invoices
- [ ] Audit log
- [ ] Dark mode
- [ ] Mobile-responsive redesign

Interested in working on any of these? Check out our [Contributing Guide](CONTRIBUTING.md) and look for issues labeled **good first issue**.

## Contributing

We welcome contributions of all kinds! Whether it's bug fixes, new features, documentation, or tests — every contribution matters.

Please read our [Contributing Guide](CONTRIBUTING.md) to get started. Open the repository Issues tab for ideas on where to begin.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Inspired by [Tally](https://tallysolutions.com/) accounting software. Built with FastAPI, React, and PostgreSQL.

