"""
Reset the database for local development.

This script drops and recreates the public schema, reapplies all migrations,
and seeds the default admin user.

Usage:
    python reset_db.py
    python reset_db.py --skip-seed
"""

import argparse
import importlib
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from src.db.base import Base
from src.db.session import engine


def reset_schema() -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO CURRENT_USER"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))


def run_script(script_name: str, *args: str) -> None:
    backend_dir = Path(__file__).resolve().parent
    cmd = [sys.executable, str(backend_dir / script_name), *args]
    subprocess.run(cmd, cwd=backend_dir, check=True)


def load_all_models() -> None:
    models_dir = Path(__file__).resolve().parent / "src" / "models"
    for model_file in sorted(models_dir.glob("*.py")):
        if model_file.name == "__init__.py":
            continue
        importlib.import_module(f"src.models.{model_file.stem}")


def create_core_tables() -> None:
    load_all_models()
    Base.metadata.create_all(bind=engine)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the database")
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Do not run admin seed after migrations",
    )
    parser.add_argument(
        "--with-demo",
        action="store_true",
        help="Seed demo data (company, buyers, products, invoices, receipts) after admin seed",
    )
    args = parser.parse_args()

    print("Resetting database schema...")
    reset_schema()
    print("Schema reset complete.")

    print("Creating core tables...")
    create_core_tables()
    print("Core tables created.")

    print("Applying migrations...")
    run_script("migrate.py", "up")
    print("Migrations applied.")

    if not args.skip_seed:
        print("Seeding admin user...")
        run_script("seed_admin.py")
        print("Seed complete.")

    if args.with_demo:
        print("Seeding demo data...")
        run_script("seed_demo.py")
        print("Demo seed complete.")

    print("Database reset finished.")


if __name__ == "__main__":
    main()
