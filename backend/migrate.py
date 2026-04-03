"""
Sequelize-style database migration runner.

Usage:
    python migrate.py up          # Run all pending migrations
    python migrate.py down        # Roll back last applied migration
    python migrate.py down --all  # Roll back all migrations
    python migrate.py status      # Show migration status
    python migrate.py create <name>  # Create a new migration file
"""

import argparse
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATIONS_TABLE = "_migrations"


def get_engine():
    from src.db.session import engine
    return engine


def ensure_migrations_table(conn) -> None:
    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def get_applied_migrations(conn) -> list[str]:
    rows = conn.execute(
        text(f"SELECT name FROM {MIGRATIONS_TABLE} ORDER BY id ASC")
    ).fetchall()
    return [row[0] for row in rows]


def discover_migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    files = sorted(
        f for f in MIGRATIONS_DIR.iterdir()
        if f.suffix == ".py" and f.name != "__init__.py"
    )
    return files


def load_migration_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_up(args) -> None:
    with get_engine().begin() as conn:
        ensure_migrations_table(conn)
        applied = set(get_applied_migrations(conn))
        files = discover_migration_files()
        pending = [f for f in files if f.stem not in applied]

        if not pending:
            print("✓ All migrations are already applied.")
            return

        for migration_file in pending:
            module = load_migration_module(migration_file)
            print(f"  ▸ Applying {migration_file.stem}...", end=" ")
            module.up(conn)
            conn.execute(
                text(f"INSERT INTO {MIGRATIONS_TABLE} (name) VALUES (:name)"),
                {"name": migration_file.stem},
            )
            print("done")

        print(f"✓ Applied {len(pending)} migration(s).")


def cmd_down(args) -> None:
    with get_engine().begin() as conn:
        ensure_migrations_table(conn)
        applied = get_applied_migrations(conn)

        if not applied:
            print("✓ No migrations to roll back.")
            return

        targets = list(reversed(applied)) if args.all else [applied[-1]]

        for name in targets:
            migration_file = MIGRATIONS_DIR / f"{name}.py"
            if not migration_file.exists():
                print(f"  ⚠ Migration file {name}.py not found, skipping rollback.")
                continue

            module = load_migration_module(migration_file)
            print(f"  ◂ Rolling back {name}...", end=" ")
            module.down(conn)
            conn.execute(
                text(f"DELETE FROM {MIGRATIONS_TABLE} WHERE name = :name"),
                {"name": name},
            )
            print("done")

        print(f"✓ Rolled back {len(targets)} migration(s).")


def cmd_status(args) -> None:
    with get_engine().begin() as conn:
        ensure_migrations_table(conn)
        applied = set(get_applied_migrations(conn))
        files = discover_migration_files()

        if not files:
            print("No migration files found.")
            return

        for f in files:
            status = "✓ applied" if f.stem in applied else "○ pending"
            print(f"  {status}  {f.stem}")

        pending_count = sum(1 for f in files if f.stem not in applied)
        print(f"\n  {len(files)} total, {len(files) - pending_count} applied, {pending_count} pending")


def cmd_create(args) -> None:
    MIGRATIONS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    slug = args.name.lower().replace(" ", "_").replace("-", "_")
    filename = f"{timestamp}_{slug}.py"
    filepath = MIGRATIONS_DIR / filename

    filepath.write_text(f'''"""
{args.name}
"""

from sqlalchemy import text


def up(conn) -> None:
    """Apply migration."""
    # conn.execute(text("ALTER TABLE ... ADD COLUMN ..."))
    pass


def down(conn) -> None:
    """Reverse migration."""
    # conn.execute(text("ALTER TABLE ... DROP COLUMN ..."))
    pass
''')
    print(f"✓ Created {filepath.relative_to(Path(__file__).parent)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Database migration runner")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("up", help="Apply all pending migrations")

    down_parser = sub.add_parser("down", help="Roll back migrations")
    down_parser.add_argument("--all", action="store_true", help="Roll back all migrations")

    sub.add_parser("status", help="Show migration status")

    create_parser = sub.add_parser("create", help="Create a new migration file")
    create_parser.add_argument("name", help="Migration name (e.g. 'add_hsn_to_products')")

    args = parser.parse_args()

    if args.command == "up":
        cmd_up(args)
    elif args.command == "down":
        cmd_down(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "create":
        cmd_create(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
