# Database Migrations

Sequelize-style migration system for managing schema changes. Each migration is a Python file with `up(conn)` and `down(conn)` functions.

## Commands

Using Make (recommended, runs inside Docker):

```bash
make migrate                              # Apply all pending migrations
make migrate-status                       # Check which migrations are applied / pending
make migrate-down                         # Roll back the last applied migration
make migrate-down-all                     # Roll back ALL migrations
make migrate-create name="add_discount_to_invoices"  # Scaffold a new migration file
```

Or directly via `migrate.py` (e.g. local development without Docker):

```bash
cd backend
python migrate.py status
python migrate.py up
python migrate.py down
python migrate.py down --all
python migrate.py create "add_discount_to_invoices"
```

## Migration file format

Each file lives in `backend/migrations/` and is named `<timestamp>_<slug>.py`:

```python
"""
Add discount column to invoices
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("ALTER TABLE invoices ADD COLUMN discount NUMERIC(10,2) DEFAULT 0"))


def down(conn) -> None:
    conn.execute(text("ALTER TABLE invoices DROP COLUMN IF EXISTS discount"))
```

## How it works

- A `_migrations` table in Postgres tracks which migrations have been applied.
- `migrate.py up` runs all files in `backend/migrations/` that aren't yet in the tracking table, in filename order.
- `migrate.py down` reverses the last applied migration by calling its `down()` function.
- Each migration runs inside a transaction — if it fails, the DB rolls back automatically.
- On app startup, `app_main.py` calls `run_pending_migrations()` which auto-applies any pending migrations, so deploys are zero-touch.

## Running against production

Port-forward to the production Postgres and override `DATABASE_URL`:

```bash
# Terminal 1: open tunnel
kubectl port-forward -n db svc/postgres 15432:5432

# Terminal 2: run migrations
cd backend
DATABASE_URL='postgresql://admin:<password>@127.0.0.1:15432/invoicing_db' python migrate.py status
DATABASE_URL='postgresql://admin:<password>@127.0.0.1:15432/invoicing_db' python migrate.py up
```

## Tips

- Always check `status` before running `up` in production.
- Migration files are idempotent by convention — use `IF NOT EXISTS` / `IF EXISTS` guards in SQL.
- Never edit a migration that has already been applied. Create a new one instead.
- Keep migrations small and focused — one concern per file.
