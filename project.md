# Simple Invoicing - Project Context

**Last Updated**: March 25, 2026  
**Project Type**: Full-stack invoicing system with Tally-style accounting ledger

## Project Overview

Simple Invoicing is a modern web application that transforms traditional buyer-based invoicing into a comprehensive accounting ledger system inspired by Tally accounting software. The application supports dual-voucher accounting (Sales and Purchase invoices) with inventory management, period-based financial reporting, and a day-book register.

**Primary Goals**:
- Provide a Tally-like minimal replica for small business invoicing and accounting
- Support both Sales and Purchase invoices with opposite inventory effects
- Enable period-based financial views (Ledger Statement per account, Day Book across all accounts)
- Maintain backward database compatibility while modernizing the API/UI terminology

## Technology Stack

### Backend
- **Framework**: FastAPI 0.115.0
- **Database**: PostgreSQL (SQLAlchemy ORM 2.0.35)
- **Authentication**: Python-Jose with bcrypt hashing
- **Server**: Uvicorn 0.30.6
- **Dependencies**: See [backend/requirements.txt](backend/requirements.txt)

### Frontend
- **Framework**: React 18.3.1 with TypeScript 5.6.2
- **Build Tool**: Vite 5.4.8
- **Styling**: Tailwind CSS 3.4.13
- **HTTP Client**: Axios 1.7.7
- **Routing**: React Router 6.26.2
- **Animation**: Framer Motion 11.11.9
- **Dependencies**: See [frontend/package.json](frontend/package.json)

### Deployment
- **Containerization**: Docker + Docker Compose
- **Web Server**: Nginx (Alpine)
- **Python Runtime**: Python 3.11 (Alpine)
- **Node Runtime**: Node 20 (Alpine)
- See [docker-compose.yml](docker-compose.yml) for full setup

## Project Structure

```
simple_invoicing/
├── backend/
│   ├── app_main.py                 # FastAPI app initialization, migrations, routes registration
│   ├── requirements.txt             # Python dependencies
│   ├── seed_admin.py                # Admin user seeding script
│   ├── Dockerfile                   # Backend container image
│   └── src/
│       ├── api/
│       │   ├── deps.py             # Dependency injection (get_db, get_current_user, etc.)
│       │   └── routes/
│       │       ├── auth.py         # Login/token endpoints
│       │       ├── users.py        # User CRUD operations
│       │       ├── products.py     # Product CRUD operations
│       │       ├── inventory.py    # Inventory adjustments
│       │       ├── invoices.py     # Invoice creation with dual-voucher support
│       │       ├── buyers.py       # Ledger CRUD (via Buyer ORM)
│       │       └── ledgers.py      # Ledger Statement & Day Book reporting
│       ├── core/
│       │   ├── config.py           # Configuration & settings
│       │   └── security.py         # Password hashing, JWT token generation
│       ├── db/
│       │   ├── base.py             # SQLAlchemy declarative base
│       │   └── session.py          # Database session factory
│       ├── models/
│       │   ├── buyer.py            # Ledger account (ORM: Buyer, API: Ledger)
│       │   ├── user.py             # User model with roles
│       │   ├── product.py          # Product catalog
│       │   ├── inventory.py        # Stock tracking per product
│       │   └── invoice.py          # Invoice records with voucher_type field
│       └── schemas/
│           ├── auth.py             # Login request/token schemas
│           ├── buyer.py            # Ledger request/response schemas
│           ├── ledger.py           # Ledger statement & day book schemas
│           ├── user.py             # User schemas
│           ├── product.py          # Product schemas
│           ├── invoice.py          # Invoice request/response schemas
│           └── inventory.py        # Inventory adjustment schemas
├── frontend/
│   ├── index.html                  # Entry point
│   ├── package.json                # Dependencies
│   ├── tsconfig.json               # TypeScript configuration
│   ├── vite.config.ts              # Vite build configuration
│   ├── tailwind.config.js          # Tailwind CSS customization
│   ├── postcss.config.js           # PostCSS plugins
│   ├── Dockerfile                  # Frontend container image (multi-stage)
│   ├── nginx.conf                  # Nginx configuration for production serving
│   └── src/
│       ├── main.tsx                # React app entry point
│       ├── App.tsx                 # Route definitions
│       ├── styles.css              # Global CSS
│       ├── api/
│       │   └── client.ts           # Axios instance with auth interceptor
│       ├── context/
│       │   └── AuthContext.tsx     # Authentication state & token management
│       ├── types/
│       │   └── api.ts              # TypeScript type definitions for API contracts
│       ├── components/
│       │   └── Layout.tsx          # Sidebar navigation and layout wrapper
│       └── pages/
│           ├── LoginPage.tsx       # Authentication page
│           ├── DashboardPage.tsx   # Summary/overview page
│           ├── ProductsPage.tsx    # Product CRUD
│           ├── InventoryPage.tsx   # Stock adjustment
│           ├── InvoicesPage.tsx    # Invoice creation & listing (dual-voucher)
│           ├── LedgersPage.tsx     # Ledger account creation & statement view
│           └── DayBookPage.tsx     # Cross-ledger voucher register
├── docker-compose.yml              # Multi-container orchestration
├── .dockerignore                   # Docker build context exclusions
├── DOCKER.md                       # Docker setup & deployment guide
├── README.md                       # Project overview & quick start
├── OPENCLAW.md                     # Feature documentation
└── project.md                      # This file - agent context guide
```

## Database Schema (with Backward Compatibility)

### Key Architectural Pattern: Column Aliasing

The system uses SQLAlchemy column aliasing to maintain backward database compatibility while renaming ORM attributes and API terminology from "Buyer" to "Ledger".

**Example** (from [backend/src/models/invoice.py](backend/src/models/invoice.py)):
```python
ledger_id = Column("buyer_id", Integer, ForeignKey("buyers.id"), nullable=True)
ledger_name = Column("buyer_name", String, nullable=True)
```

This stores data in `buyer_id` / `buyer_name` columns but exposes `ledger_id` / `ledger_name` in Python and API responses.

### Core Tables

#### `users` table
- `id` (PK)
- `email` (unique)
- `hashed_password`
- `role` (enum: admin, staff)
- `created_at`

#### `buyers` table (Ledger accounts)
- `id` (PK)
- `name` (e.g., customer name)
- `address`
- `gst` (tax ID)
- `phone`
- `created_by` (FK to users)
- `created_at`
- Relationship: 1:M to `invoices`

#### `products` table
- `id` (PK)
- `name`
- `description`
- `unit_price` (decimal)
- `created_by` (FK to users)
- `created_at`
- Relationship: 1:M to `invoice_items`, 1:M to `inventory`

#### `invoices` table
- `id` (PK)
- `ledger_id` (FK to buyers.id, stored as `buyer_id`)
- `ledger_name` (snapshot, stored as `buyer_name`)
- `ledger_address` (snapshot, stored as `buyer_address`)
- `ledger_gst` (snapshot, stored as `buyer_gst`)
- `ledger_phone` (snapshot, stored as `buyer_phone`)
- `voucher_type` (ENUM: "sales" or "purchase") **[NEW]**
- `created_by` (FK to users)
- `total_amount` (decimal)
- `created_at`
- Relationships: 1:M to `invoice_items`, M:1 to `buyers` (Ledger)

#### `invoice_items` table
- `id` (PK)
- `invoice_id` (FK to invoices)
- `product_id` (FK to products)
- `quantity` (integer)
- `unit_price` (decimal)
- `line_total` (decimal)
- Relationships: M:1 to `invoices`, M:1 to `products`

#### `inventory` table
- `id` (PK)
- `product_id` (FK to products)
- `balance` (decimal, current stock)
- `created_at`
- Relationship: M:1 to `products`

## API Endpoints

### Authentication
- `POST /api/auth/login` – User login, returns JWT token
  - Request: `{email, password}`
  - Response: `{access_token, token_type, user: {id, email, role}}`

### Users
- `GET /api/users/` – List all users (admin only)
- `POST /api/users/` – Create new user (admin only)
- `GET /api/users/me` – Get current authenticated user

### Products
- `GET /api/products/` – List all products
- `POST /api/products/` – Create new product
- `GET /api/products/{id}` – Get product details
- `PUT /api/products/{id}` – Update product

### Inventory
- `GET /api/inventory/` – List all inventory rows
- `POST /api/inventory/adjust` – Adjust stock for a product
  - Request: `{product_id, adjustment}`
  - Response: Updated inventory row

### Invoices
- `GET /api/invoices/` – List all invoices with filters (ledger_id, etc.)
- `POST /api/invoices/` – Create invoice (sales or purchase)
  - Request: `{buyer_id, items: [{product_id, quantity, unit_price}], voucher_type: "sales" | "purchase"}`
  - Response: Created invoice with total_amount and items
- **Inventory Behavior**:
  - `voucher_type: "sales"` → Decreases inventory (sales reduce stock)
  - `voucher_type: "purchase"` → Increases inventory (purchase adds stock)

### Buyers (Ledger Accounts)
- `GET /api/buyers/` – List all buyers (now called Ledgers in UI)
- `POST /api/buyers/` – Create new buyer/ledger
  - Request: `{name, address, gst, phone, created_by}`
  - Response: Ledger object

### Ledgers (Reporting)
- `GET /api/ledgers/` – List all ledger accounts (alias for /api/buyers/)
- `POST /api/ledgers/` – Create ledger account
- `GET /api/ledgers/{ledger_id}/statement` – Get period-based ledger statement
  - Query params: `from_date` (YYYY-MM-DD), `to_date` (YYYY-MM-DD)
  - Response: `{ledger: {...}, opening_debit, opening_credit, period_debit, period_credit, entries: [{date, invoice_id, description, debit, credit}], closing_balance}`
  - **Ledger Math**: `closing_balance = (opening_debit - opening_credit) + (period_debit - period_credit)`
- `GET /api/ledgers/day-book` – Get all vouchers across all ledgers for period
  - Query params: `from_date` (YYYY-MM-DD), `to_date` (YYYY-MM-DD)
  - Response: `{entries: [{date, ledger_name, invoice_id, voucher_type, debit, credit, running_total}], total_debit, total_credit}`
  - **Voucher Type Mapping**: Sales = Debit, Purchase = Credit

## Key Features & Implementation

### 1. Dual-Voucher Accounting System

**File**: [backend/src/api/routes/invoices.py](backend/src/api/routes/invoices.py)

- **Sales Invoices**: 
  - Reduce inventory by requested quantity
  - Record as debit entry in Ledger Statement
  - Display as "Dr" in UI
  
- **Purchase Invoices**:
  - Increase inventory by requested quantity
  - Creates inventory record if not exists
  - Record as credit entry in Ledger Statement
  - Display as "Cr" in UI

**Inventory Logic** (lines 48-72):
```python
if payload.voucher_type == "sales":
    # Check inventory availability, reduce quantity
else:  # purchase
    # Create or update inventory, increase quantity
```

### 2. Period-Based Ledger Statement

**File**: [backend/src/api/routes/ledgers.py](backend/src/api/routes/ledgers.py), lines 61-155

- Calculates opening balance from invoice history before period
- Splits sales/purchase into separate debit/credit totals
- Returns all period entries with individual Dr/Cr amounts
- Closing balance: Opening + Period Debit - Period Credit

**Opening Balance Query** (lines 108-116):
Uses SQLAlchemy `case()` to separate sales and purchase totals in the opening period query, preventing double-counting.

### 3. Day Book (Voucher Register)

**File**: [backend/src/api/routes/ledgers.py](backend/src/api/routes/ledgers.py), lines 68-79

- Shows all vouchers across all ledgers for a selected period
- Maps voucher_type to Dr/Cr (Sales=Dr, Purchase=Cr)
- Used for period reconciliation and audit trail

### 4. Frontend Invoice Form with Voucher Type

**File**: [frontend/src/pages/InvoicesPage.tsx](frontend/src/pages/InvoicesPage.tsx)

- Dropdown selector for "Sales" or "Purchase" (lines 189-198)
- State management: `const [voucherType, setVoucherType] = useState<'sales' | 'purchase'>('sales')`
- Payload includes `voucher_type: voucherType` (lines 110-112)
- Success message varies by type: "Inventory has been reduced" vs "increased" (lines 120-124)
- Invoice list shows "Sales"/"Purchase" label and "Dr"/"Cr" based on voucher_type (lines 310-316)

### 5. Frontend Ledger and Day Book Pages

**Ledger Statement** ([frontend/src/pages/LedgersPage.tsx](frontend/src/pages/LedgersPage.tsx)):
- Period date filters (from_date, to_date)
- Summary box showing opening/debit/credit/closing totals (lines 244-251)
- Entry list with voucher_type and Dr/Cr rendering (lines 265-271)

**Day Book** ([frontend/src/pages/DayBookPage.tsx](frontend/src/pages/DayBookPage.tsx)):
- Cross-ledger register for selected period
- Totals box showing total Dr and Cr (lines 100-102)
- Entry rows map debit>0 to "Dr" display (lines 121-127)

## Authentication & Security

**Default Admin Credentials** (create via `python seed_admin.py`):
- Email: `admin@simple.dev`
- Password: `Admin@123`

**JWT Token**:
- Expires after 30 minutes (configurable)
- Used in `Authorization: Bearer {token}` header
- Decoded and validated on protected endpoints

**Frontend Storage**:
- Token stored in sessionStorage (cleared on tab close)
- Retrieved via `AuthContext` hook
- Automatically included in all API calls via axios interceptor ([frontend/src/api/client.ts](frontend/src/api/client.ts))

## Common Tasks & Workflows

### 1. Adding a New API Endpoint

1. Create schema in `backend/src/schemas/` (Pydantic models)
2. Create route in `backend/src/api/routes/` with `@router.get/post/put/delete`
3. Register router in `backend/app_main.py` (line 53)
4. Add TypeScript type in `frontend/src/types/api.ts`
5. Create frontend component/page consuming the endpoint

### 2. Modifying Database Schema

1. Edit model in `backend/src/models/`
2. Add migration logic to `ensure_invoice_buyer_columns()` in `backend/app_main.py` if needed
3. Restart backend: `docker-compose restart backend` or redeploy

### 3. Debugging Invoice Issues

Check these in order:
1. Inventory availability: `GET /api/inventory/?product_id=X`
2. Ledger exists: `GET /api/ledgers/` or `GET /api/buyers/`
3. Invoice payload format: Match `InvoiceCreate` schema
4. Check backend logs: `docker-compose logs backend`

### 4. Running Tests

Execute in backend container:
```bash
docker-compose exec backend python -m pytest
```

Or locally:
```bash
cd backend && .venv/bin/python -c "from fastapi.testclient import TestClient; ..."
```

### 5. Seeding Sample Data

```bash
# Create admin user
docker-compose exec backend python seed_admin.py

# Then use frontend to create products, ledgers, invoices
```

## Environment Variables

**Backend** (in `docker-compose.yml` or `.env`):
- `DATABASE_URL` – PostgreSQL connection string
- `SECRET_KEY` – JWT signing secret (change in production!)
- `ALGORITHM` – JWT algorithm (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES` – Token expiration (default: 30)

**Frontend**:
- `VITE_API_BASE_URL` – Backend API base URL (detected from window.location by default)

## Docker Commands

See [DOCKER.md](DOCKER.md) for comprehensive Docker setup guide.

**Common commands**:
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Seed admin user
docker-compose exec backend python seed_admin.py

# Stop all services
docker-compose down
```

## Recent Changes (Session Summary)

**Phase 1 – Ledger Refactor**:
- Renamed "Buyer" to "Ledger" in API/UI/types
- Maintained database backward compatibility via column aliasing
- Created LedgersPage with account management

**Phase 2 – Day Book Addition**:
- Implemented period-based Day Book endpoint
- Shows all vouchers across all ledgers
- Includes Dr/Cr split and period totals

**Phase 3 – Purchase Invoice Support**:
- Added `voucher_type` column to invoices table
- Implemented bifurcated inventory logic
  - Sales: Decreases stock
  - Purchase: Increases stock
- Updated frontend invoice form with voucher type selector
- Updated Ledger Statement to split sales/purchase totals
- Updated Day Book to map voucher type to Dr/Cr

**Phase 4 – Containerization** (Latest):
- Created Dockerfile for backend (FastAPI + Python 3.11)
- Created Dockerfile for frontend (multi-stage React + Nginx)
- Created docker-compose.yml with PostgreSQL, backend, frontend services
- Added nginx.conf for production serving with API proxy
- Added DOCKER.md documentation

## Known Limitations & Future Enhancements

**Current Limitations**:
- Separate Purchase Invoice page not yet implemented (uses same form as Sales)
- No voucher type filters in Day Book view
- Opening balance carry-forward not shown as explicit day-book entry
- No CSV export from Day Book or Ledger Statement

**Planned Enhancements**:
- Dedicated Purchase Invoice page (Tally-style separate entry form)
- Advanced filtering & search in Day Book
- Report generation & export
- Multi-user role-based access control refinement
- Database query optimization for large periods

## Verification Checklist

- ✅ Backend compiles without syntax errors
- ✅ Frontend builds successfully
- ✅ All 6 API routes registered and functional
- ✅ Docker setup tested
- ✅ Purchase/sales inventory logic validated
- ✅ Ledger accounting math verified
- ✅ Dr/Cr rendering consistent across frontend

## Agent Handoff Notes

When continuing this project:

1. **Always test** invoice creation with both `voucher_type: "sales"` and `"purchase"` to verify inventory behavior
2. **Use column aliases** when adding new ledger-related fields (ORM name ≠ DB column name)
3. **Check debit/credit math** carefully in statement calculations
4. **Validate API contracts** in `frontend/src/types/api.ts` match backend schemas
5. **Use docker-compose** for consistent development environment across machines
6. **Reference exact line numbers** from [conversation summary](CONVERSATION.md) when debugging specific features

## Useful References

- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **SQLAlchemy ORM**: https://docs.sqlalchemy.org/
- **React Hooks**: https://react.dev/reference/react
- **Vite Guide**: https://vitejs.dev/guide/
- **Nginx Config**: https://nginx.org/en/docs/

---

**For questions about specific implementation details**, refer to the code comments and line references in this document.
