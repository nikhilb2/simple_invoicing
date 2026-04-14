import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException, UploadFile
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from src.core.config import settings
from src.db.session import engine


BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
logger = logging.getLogger(__name__)
_backup_key_warned = False


@dataclass
class BackupManifest:
    created_at: datetime
    app_version: str
    migration_names: list[str]
    migration_head: str | None


@dataclass
class RestorePreflight:
    compatibility: str
    reason: str | None
    backup_created_at: datetime | None
    backup_migration_head: str | None
    current_migration_head: str | None
    migration_gap_count: int | None


class _PreparedBackup:
    def __init__(self, temp_dir: TemporaryDirectory[str], dump_path: Path, manifest: BackupManifest):
        self.temp_dir = temp_dir
        self.dump_path = dump_path
        self.manifest = manifest


def _get_backup_fernet() -> Fernet:
    global _backup_key_warned
    explicit_backup_key = getattr(settings, "BACKUP_ENCRYPTION_KEY", None)
    if explicit_backup_key:
        key_material = explicit_backup_key
    elif settings.SMTP_ENCRYPTION_KEY:
        key_material = settings.SMTP_ENCRYPTION_KEY
        if not _backup_key_warned:
            logger.warning("BACKUP_ENCRYPTION_KEY is not set. Falling back to SMTP_ENCRYPTION_KEY for backup encryption.")
            _backup_key_warned = True
    else:
        key_material = settings.SECRET_KEY
        if not _backup_key_warned:
            logger.warning("BACKUP_ENCRYPTION_KEY and SMTP_ENCRYPTION_KEY are not set. Falling back to SECRET_KEY for backup encryption.")
            _backup_key_warned = True

    key = hashlib.sha256(key_material.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt_bytes(data: bytes) -> bytes:
    return _get_backup_fernet().encrypt(data)


def _decrypt_bytes(data: bytes) -> bytes:
    try:
        return _get_backup_fernet().decrypt(data)
    except InvalidToken as err:
        raise HTTPException(status_code=400, detail="Invalid encrypted backup file or encryption key") from err


def ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _db_parts() -> dict[str, str | int | None]:
    parsed = engine.url
    return {
        "host": parsed.host,
        "port": parsed.port,
        "username": parsed.username,
        "password": parsed.password,
        "database": parsed.database,
    }


def _database_dsn() -> str:
    # render_as_string(hide_password=False) is required for subprocess tools;
    # str(engine.url) masks password as *** and causes auth failures.
    return engine.url.render_as_string(hide_password=False)


def get_applied_migrations() -> list[str]:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                name VARCHAR NOT NULL UNIQUE,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        rows = conn.execute(text("SELECT name FROM _migrations ORDER BY name ASC")).fetchall()
        return [row[0] for row in rows]


def _build_manifest() -> BackupManifest:
    migrations = get_applied_migrations()
    return BackupManifest(
        created_at=datetime.now(timezone.utc),
        app_version="0.1.0",
        migration_names=migrations,
        migration_head=migrations[-1] if migrations else None,
    )


def _run_pg_dump(output_path: Path) -> None:
    db = _db_parts()
    if not db["database"]:
        raise HTTPException(status_code=500, detail="Invalid database configuration")

    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(output_path),
        "--dbname",
        _database_dsn(),
    ]

    env = os.environ.copy()
    if db["password"]:
        env["PGPASSWORD"] = str(db["password"])

    try:
        subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    except FileNotFoundError as err:
        raise HTTPException(status_code=500, detail="pg_dump is not available on the server") from err
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or err.stdout or "pg_dump failed").strip()
        raise HTTPException(status_code=500, detail=f"Backup failed: {detail}") from err


def create_backup_archive() -> dict:
    ensure_backup_dir()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_name = f"backup_{stamp}.enc"
    archive_path = BACKUP_DIR / file_name

    with TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        dump_path = temp_dir / "database.dump"
        manifest_path = temp_dir / "manifest.json"
        plain_zip_path = temp_dir / "backup.zip"

        _run_pg_dump(dump_path)

        manifest = _build_manifest()
        manifest_data = {
            "created_at": manifest.created_at.isoformat(),
            "app_version": manifest.app_version,
            "migration_names": manifest.migration_names,
            "migration_head": manifest.migration_head,
            "dump_sha256": _sha256(dump_path),
            "format": "pg_dump_custom",
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        with ZipFile(plain_zip_path, "w", compression=ZIP_DEFLATED) as zip_obj:
            zip_obj.write(dump_path, arcname="database.dump")
            zip_obj.write(manifest_path, arcname="manifest.json")

        encrypted_payload = _encrypt_bytes(plain_zip_path.read_bytes())
        archive_path.write_bytes(encrypted_payload)

    stat = archive_path.stat()
    return {
        "file_name": file_name,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        "migration_head": _build_manifest().migration_head,
    }


def list_backups() -> list[dict]:
    ensure_backup_dir()
    items: list[dict] = []

    for path in sorted(BACKUP_DIR.glob("*.enc"), key=lambda p: p.stat().st_mtime, reverse=True):
        manifest_head: str | None = None
        created_at: datetime | None = None
        try:
            encrypted_data = path.read_bytes()
            decrypted_data = _decrypt_bytes(encrypted_data)
            with ZipFile(io.BytesIO(decrypted_data), "r") as zip_obj:
                if "manifest.json" in zip_obj.namelist():
                    data = json.loads(zip_obj.read("manifest.json").decode("utf-8"))
                    manifest_head = data.get("migration_head")
                    if data.get("created_at"):
                        created_at = datetime.fromisoformat(data["created_at"])
        except Exception:
            manifest_head = None

        stat = path.stat()
        items.append(
            {
                "file_name": path.name,
                "size_bytes": stat.st_size,
                "created_at": created_at or datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "migration_head": manifest_head,
            }
        )

    return items


def get_backup_file_path(file_name: str) -> Path:
    safe_name = Path(file_name).name
    path = BACKUP_DIR / safe_name
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".enc":
        raise HTTPException(status_code=404, detail="Backup file not found")
    return path


def _prepare_uploaded_backup(upload: UploadFile) -> _PreparedBackup:
    suffix = Path(upload.filename or "backup.zip").suffix.lower()
    if suffix != ".enc":
        raise HTTPException(status_code=400, detail="Backup file must be an encrypted .enc archive")

    temp_dir = TemporaryDirectory()
    tmp_root = Path(temp_dir.name)
    encrypted_path = tmp_root / "incoming.enc"
    archive_path = tmp_root / "incoming.zip"

    with encrypted_path.open("wb") as out:
        shutil.copyfileobj(upload.file, out)

    encrypted_data = encrypted_path.read_bytes()
    decrypted_data = _decrypt_bytes(encrypted_data)
    archive_path.write_bytes(decrypted_data)

    try:
        with ZipFile(archive_path, "r") as zip_obj:
            names = set(zip_obj.namelist())
            if "database.dump" not in names or "manifest.json" not in names:
                raise HTTPException(status_code=400, detail="Invalid backup archive. Missing database.dump or manifest.json")
            zip_obj.extract("database.dump", path=tmp_root)
            zip_obj.extract("manifest.json", path=tmp_root)
    except HTTPException:
        temp_dir.cleanup()
        raise
    except Exception as err:
        temp_dir.cleanup()
        raise HTTPException(status_code=400, detail="Invalid backup archive") from err

    manifest_path = tmp_root / "manifest.json"
    dump_path = tmp_root / "database.dump"

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        migration_names = raw.get("migration_names") or []
        if not isinstance(migration_names, list):
            raise ValueError("migration_names must be a list")
        manifest = BackupManifest(
            created_at=datetime.fromisoformat(raw["created_at"]),
            app_version=str(raw.get("app_version") or "unknown"),
            migration_names=[str(x) for x in migration_names],
            migration_head=raw.get("migration_head"),
        )
        expected_sha = raw.get("dump_sha256")
        if expected_sha and expected_sha != _sha256(dump_path):
            raise HTTPException(status_code=400, detail="Backup checksum mismatch")
    except HTTPException:
        temp_dir.cleanup()
        raise
    except Exception as err:
        temp_dir.cleanup()
        raise HTTPException(status_code=400, detail="Invalid backup manifest") from err

    return _PreparedBackup(temp_dir=temp_dir, dump_path=dump_path, manifest=manifest)


def _probe_dump(dump_path: Path) -> None:
    print(f"[restore-debug] probing dump start: {dump_path}")
    command = ["pg_restore", "--list", str(dump_path)]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        print("[restore-debug] probing dump success")
    except FileNotFoundError as err:
        print("[restore-debug] probing dump failed: pg_restore not found")
        raise HTTPException(status_code=500, detail="pg_restore is not available on the server") from err
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or err.stdout or "pg_restore failed").strip()
        print(f"[restore-debug] probing dump failed: {detail}")
        raise HTTPException(status_code=400, detail=f"Backup file is not restorable: {detail}") from err


def _classify_compatibility(backup_migrations: list[str], current_migrations: list[str]) -> tuple[str, str | None, int]:
    backup_set = set(backup_migrations)
    current_set = set(current_migrations)

    if backup_set == current_set:
        return "exact", None, 0

    if backup_set.issubset(current_set):
        gap = len(current_set - backup_set)
        return "requires_migration", "Backup is older than current schema; pending migrations will be applied after restore.", gap

    if current_set.issubset(backup_set):
        gap = len(backup_set - current_set)
        return "newer_than_app", "Backup appears to come from a newer app schema and cannot be restored safely.", gap

    return "diverged", "Backup schema history diverges from current database migrations.", abs(len(current_set) - len(backup_set))


def preflight_restore(upload: UploadFile) -> RestorePreflight:
    prepared = _prepare_uploaded_backup(upload)
    try:
        _probe_dump(prepared.dump_path)
        current = get_applied_migrations()
        compatibility, reason, gap = _classify_compatibility(prepared.manifest.migration_names, current)
        return RestorePreflight(
            compatibility=compatibility,
            reason=reason,
            backup_created_at=prepared.manifest.created_at,
            backup_migration_head=prepared.manifest.migration_head,
            current_migration_head=current[-1] if current else None,
            migration_gap_count=gap,
        )
    finally:
        prepared.temp_dir.cleanup()


def _apply_pending_migrations() -> int:
    if not MIGRATIONS_DIR.exists():
        print("[restore-debug] no migrations directory, skipping pending migrations")
        return 0

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
            f for f in MIGRATIONS_DIR.iterdir()
            if f.suffix == ".py" and f.name != "__init__.py"
        )

        applied_count = 0
        for migration_file in files:
            if migration_file.stem in applied:
                continue

            spec = importlib.util.spec_from_file_location(migration_file.stem, migration_file)
            if spec is None or spec.loader is None:
                raise HTTPException(status_code=500, detail=f"Unable to load migration module {migration_file.name}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.up(conn)
            conn.execute(
                text("INSERT INTO _migrations (name) VALUES (:name)"),
                {"name": migration_file.stem},
            )
            applied_count += 1
            print(f"[restore-debug] applied migration after restore: {migration_file.stem}")

        print(f"[restore-debug] pending migrations applied count: {applied_count}")
    return applied_count


def _terminate_other_db_sessions(env: dict[str, str]) -> None:
    print("[restore-debug] terminating other DB sessions before restore")
    terminate_sql = (
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        "WHERE datname = current_database() "
        "AND pid <> pg_backend_pid();"
    )
    cmd = [
        "psql",
        "--set", "ON_ERROR_STOP=1",
        "--dbname", _database_dsn(),
        "-c", terminate_sql,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        print("[restore-debug] terminate sessions success")
    except FileNotFoundError as err:
        print("[restore-debug] terminate sessions failed: psql not found")
        raise HTTPException(status_code=500, detail="psql is not available on the server") from err
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or err.stdout or "failed to terminate active DB sessions").strip()
        print(f"[restore-debug] terminate sessions failed: {detail}")
        raise HTTPException(status_code=500, detail=f"Restore failed: {detail}") from err


def restore_backup(upload: UploadFile) -> tuple[str, int]:
    print(f"[restore-debug] restore start: filename={upload.filename}")
    prepared = _prepare_uploaded_backup(upload)
    try:
        print(f"[restore-debug] backup prepared: dump={prepared.dump_path}")
        _probe_dump(prepared.dump_path)

        current = get_applied_migrations()
        print(f"[restore-debug] current migration count before restore: {len(current)}")
        compatibility, reason, _ = _classify_compatibility(prepared.manifest.migration_names, current)
        print(f"[restore-debug] compatibility={compatibility}, reason={reason}")
        if compatibility in {"newer_than_app", "diverged"}:
            raise HTTPException(status_code=400, detail=reason or "Backup is not compatible with current app")

        env = os.environ.copy()
        parts = _db_parts()
        if parts["password"]:
            env["PGPASSWORD"] = str(parts["password"])

        # Ensure app-side pooled connections don't hold stale state.
        print("[restore-debug] disposing SQLAlchemy engine before restore")
        engine.dispose()
        _terminate_other_db_sessions(env)
        engine.dispose()

        # Step 1: extract plain SQL from the custom-format dump.
        # --clean --if-exists generates DROP … IF EXISTS before each object.
        # -f - writes SQL to stdout instead of directly to the DB so we can
        # filter version-specific SET commands that older server versions reject
        # (e.g. "SET transaction_timeout" was added in pg_dump 17 but PG 16 rejects it).
        extract_cmd = [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "-f", "-",
            str(prepared.dump_path),
        ]
        try:
            extracted = subprocess.run(
                extract_cmd, check=True, capture_output=True, text=True, env=env
            )
            print(f"[restore-debug] extracted SQL bytes={len(extracted.stdout.encode('utf-8'))}")
        except FileNotFoundError as err:
            print("[restore-debug] extract failed: pg_restore not found")
            raise HTTPException(status_code=500, detail="pg_restore is not available on the server") from err
        except subprocess.CalledProcessError as err:
            detail = (err.stderr or err.stdout or "pg_restore failed").strip()
            print(f"[restore-debug] extract failed: {detail}")
            raise HTTPException(status_code=500, detail=f"Restore failed: {detail}") from err

        # Step 2: filter out session-level SET commands that the target server may
        # not support (e.g. transaction_timeout introduced in PostgreSQL 17).
        _UNSUPPORTED_SET_PREFIXES = ("SET transaction_timeout",)
        filtered_lines = [
            line for line in extracted.stdout.splitlines()
            if not any(line.strip().startswith(p) for p in _UNSUPPORTED_SET_PREFIXES)
        ]
        filtered_sql = "\n".join(filtered_lines)
        print(f"[restore-debug] filtered SQL lines={len(filtered_lines)}")

        # Step 3: apply via psql in a single transaction; ON_ERROR_STOP=1 rolls
        # back and surfaces the first error (equivalent to --exit-on-error).
        psql_cmd = [
            "psql",
            "--single-transaction",
            "--set", "ON_ERROR_STOP=1",
            "--dbname", _database_dsn(),
        ]
        try:
            subprocess.run(
                psql_cmd,
                input=filtered_sql,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            print("[restore-debug] psql restore apply success")
        except FileNotFoundError as err:
            print("[restore-debug] restore apply failed: psql not found")
            raise HTTPException(status_code=500, detail="psql is not available on the server") from err
        except subprocess.CalledProcessError as err:
            detail = (err.stderr or err.stdout or "psql restore failed").strip()
            print(f"[restore-debug] restore apply failed: {detail}")
            raise HTTPException(status_code=500, detail=f"Restore failed: {detail}") from err

        # Discard all pooled connections — they point to the pre-restore state.
        # SQLAlchemy will open fresh connections on the next request.
        print("[restore-debug] disposing SQLAlchemy engine after restore")
        engine.dispose()

        applied_count = _apply_pending_migrations()
        print(f"[restore-debug] restore completed: compatibility={compatibility}, applied_migrations={applied_count}")
        return compatibility, applied_count
    finally:
        print("[restore-debug] cleanup temp dir and dispose engine")
        prepared.temp_dir.cleanup()
        # On both success and failure, force pool reset so new requests reconnect cleanly.
        engine.dispose()
