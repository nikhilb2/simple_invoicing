import os
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.api.routes import auth, users, products, inventory, invoices, ledgers, company, payments
from src.db.base import Base
from src.db.session import engine

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
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["inventory"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["invoices"])
app.include_router(ledgers.router, prefix="/api/ledgers", tags=["ledgers"])
app.include_router(company.router, prefix="/api/company", tags=["company"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
