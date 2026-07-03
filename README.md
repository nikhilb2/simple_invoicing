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
- **Credit Notes** — Issue credit notes against invoices with linked ledger and stock reversals
- **Ledger Statements** — Period-based financial views per account (Tally-style)
- **Day Book Register** — Cross-ledger voucher register for reconciliation
- **Inventory Management** — Real-time stock tracking with automatic adjustments
- **Manufacturing / Bill of Materials** — Define BOMs and record production transactions that consume raw materials and produce finished goods
- **Cash & Bank** — Manage cash and bank accounts with company-account mappings
- **Dashboard Analytics** — Server-side metrics with monthly trend, payment-status, and top-product charts
- **Payment Tracking** — Record and track payments against invoices, with due/receivables views
- **PDF Invoice Generation** — Generate professional invoices with WeasyPrint
- **Email Delivery** — Send invoices over SMTP with per-company config and full email history/logs
- **Custom Invoice Numbering** — Configurable invoice series per financial year
- **Financial Years** — Period management for scoping vouchers and reports
- **GST Compliance** — Built-in tax fields and GST rate support
- **GSTR-1 Export** — Generate and validate GSTR-1 returns with government-ready JSON (plus CSV/PDF) export
- **Role-Based Access** — Admin, Manager, and Staff roles with JWT auth
- **Backups** — On-demand database backups from the admin UI
- **Keyboard Shortcuts** — Configurable shortcuts for power users
- **Docker Ready** — One-command dev and production setup
- **E2E Tested** — Playwright test suite for critical workflows

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2 |
| **Frontend** | React 18, TypeScript 5.6, Vite 5, Tailwind CSS, TanStack Query 5, Framer Motion |
| **Database** | PostgreSQL 16 |
| **Auth** | JWT with bcrypt password hashing |
| **PDF** | WeasyPrint |
| **Email** | SMTP (per-company configuration) |
| **Testing** | Playwright (E2E), pytest (backend) |
| **Deploy** | Docker, Docker Compose, Kubernetes (Kaniko) configs included |

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
│   │   ├── api/routes/     # REST API endpoints (one module per resource)
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   ├── services/       # Business logic layer
│   │   ├── db/             # Engine, session, and declarative base
│   │   └── core/           # Config and security
│   ├── migrations/         # Database migrations
│   ├── seed_admin.py       # Seed the initial admin user
│   ├── seed_demo.py        # Seed demo data
│   └── requirements.txt
├── frontend/               # React SPA
│   ├── src/
│   │   ├── pages/          # Route-level components
│   │   ├── components/     # Shared UI components (incl. DashboardCharts)
│   │   ├── api/            # Axios client & interceptors
│   │   ├── context/        # React context (auth)
│   │   └── types/          # TypeScript type definitions
│   ├── e2e/                # Playwright E2E tests
│   └── package.json
├── docker-compose.yml      # Multi-container orchestration
├── Makefile                # Developer shortcuts
├── DOCKER.md               # Docker guide
├── ENV.md                  # Environment variable guide
├── MIGRATION.md            # Migration workflow
├── PDFGENERATION.md        # PDF invoice generation notes
├── CREDIT_NOTE.md          # Credit note design
├── CASH_BANK.md            # Cash & bank module notes
├── INVOICE_DUE.md          # Invoice dues / receivables notes
└── project.md              # Architecture and API context
```

## API Overview

| Endpoint | Description |
|----------|-------------|
| `POST /api/auth/login` | Authenticate and get JWT token |
| `GET/POST /api/products/` | Product catalog CRUD |
| `GET/POST /api/invoices/` | Create sales/purchase invoices |
| `GET/POST /api/credit-notes/` | Issue and manage credit notes |
| `GET/POST /api/payments/` | Record and track payments |
| `GET/POST /api/ledgers/` | Ledger account management |
| `GET /api/ledgers/{id}/statement` | Period-based ledger statement |
| `GET /api/ledgers/day-book` | Cross-ledger voucher register |
| `GET /api/ledgers/tax-ledger/gstr1/summary` | GSTR-1 summary for a period |
| `GET /api/ledgers/tax-ledger/gstr1/export-json` | Export government-ready GSTR-1 JSON |
| `GET/POST /api/inventory/` | Stock levels and adjustments |
| `GET/POST /api/bom/` | Bills of material and production transactions |
| `GET /api/dashboard/` | Server-side dashboard metrics and chart data |
| `GET/POST /api/financial-years/` | Financial year management |
| `GET/POST /api/invoice-series/` | Custom invoice numbering series |
| `GET/POST /api/company/` | Company profile and terms |
| `GET/POST /api/company-accounts/` | Cash & bank / company accounts |
| `POST /api/email/` | Send invoices via SMTP |
| `GET /api/email-logs/` | Email delivery history |
| `GET/POST /api/smtp-configs/` | Per-company SMTP configuration |
| `POST /api/backups/` | Trigger database backups |
| `GET/POST /api/users/` | User management (admin) |

Full interactive docs available at `/docs` (Swagger UI) when the backend is running.

## Development

```bash
make dev                              # Start dev environment (Docker)
make prod                             # Start production environment
make test                             # Run all tests
make lint                             # Lint backend and frontend
make migrate                          # Run all pending migrations
make migrate-status                   # Show migration status
make migrate-down                     # Roll back last migration
make migrate-down-all                 # Roll back all migrations
make migrate-create name=<name>       # Create a new migration file
make seed                             # Seed admin user
make seed-demo                        # Seed demo data
make reset-db                         # Reset DB schema, migrate, and seed admin
make reset-db-demo                    # Reset DB and seed with demo data
make backend-shell                    # Open a shell in the backend container
make frontend-shell                   # Open a shell in the frontend container
make logs                             # Tail all service logs
make down                             # Stop all services
```

See the [Makefile](Makefile) for all available commands.

## Roadmap

- [x] Email invoice delivery
- [x] Dashboard analytics and charts
- [ ] Multi-currency support
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

