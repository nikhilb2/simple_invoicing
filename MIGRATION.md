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
- Startup order matters: `Base.metadata.create_all()` can create a table with newer columns before older migrations execute. Write seed `INSERT` statements to include all current required columns (or explicit defaults), not just the columns that existed when the migration was first written.

## Common CI failure: `invoice_series.suffix` NOT NULL

If CI fails with:

```text
null value in column "suffix" of relation "invoice_series" violates not-null constraint
```

Root cause:

- `invoice_series` may already exist from model metadata with `suffix VARCHAR NOT NULL DEFAULT ''`.
- Older seed SQL in `20260409000004_create_invoice_series_table.py` inserts rows without `suffix`, causing a NOT NULL violation.

Prevention pattern:

- Keep seed inserts forward-compatible by explicitly including newly required columns.
- Example: include `suffix` in both the column list and seed values (`''` for defaults).
