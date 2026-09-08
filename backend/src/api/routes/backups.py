from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from src.core.security import decode_token
from src.db.session import SessionLocal
from src.models.user import User, UserRole
from src.schemas.backup import (
    BackupCreateResponse,
    BackupPreflightResponse,
    BackupRestoreResponse,
    BackupScheduleResponse,
    BackupSummary,
)
from src.services.backup import (
    create_backup_archive,
    get_backup_file_path,
    list_backups,
    preflight_restore,
    restore_backup,
)
from src.services.backup_scheduler import status as scheduler_status

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def require_admin_no_session_hold(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = decode_token(token)
        email: str | None = payload.get("sub")
        token_type = payload.get("type")
        if email is None or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise credentials_exception
        if getattr(user, "role", None) != UserRole.admin:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    finally:
        db.close()


@router.post("/create", response_model=BackupCreateResponse)
def create_backup(
    _: User = Depends(require_admin_no_session_hold),
):
    return create_backup_archive()


@router.get("", response_model=list[BackupSummary], include_in_schema=False)
@router.get("/", response_model=list[BackupSummary])
def get_backups(
    _: User = Depends(require_admin_no_session_hold),
):
    return list_backups()


@router.get("/schedule", response_model=BackupScheduleResponse)
def get_backup_schedule(
    _: User = Depends(require_admin_no_session_hold),
):
    """Read-only view of the nightly automatic backup schedule.

    The schedule itself is configuration (AUTO_BACKUP_*), not per-tenant state, so
    there is no PUT here -- this exists purely so the Backups page can tell an admin
    when the next run is and whether the last one worked."""
    return BackupScheduleResponse(
        enabled=scheduler_status.enabled,
        email_enabled=scheduler_status.email_enabled,
        schedule_time=scheduler_status.schedule_time,
        timezone=scheduler_status.timezone_name,
        keep=scheduler_status.keep,
        next_run_at=scheduler_status.next_run_at,
        last_run_at=scheduler_status.last_run_at,
        last_status=scheduler_status.last_status,
        last_file_name=scheduler_status.last_file_name,
        last_error=scheduler_status.last_error,
        last_email_status=scheduler_status.last_email_status,
        last_email_detail=scheduler_status.last_email_detail,
    )


@router.get("/{file_name}/download")
def download_backup(
    file_name: str,
    _: User = Depends(require_admin_no_session_hold),
):
    path = get_backup_file_path(file_name)
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=path.name,
    )


@router.post("/preflight", response_model=BackupPreflightResponse)
def preflight_backup_restore(
    backup_file: UploadFile = File(...),
    _: User = Depends(require_admin_no_session_hold),
):
    result = preflight_restore(backup_file)
    return BackupPreflightResponse(
        valid=result.compatibility not in {"newer_than_app", "diverged"},
        compatibility=result.compatibility,
        reason=result.reason,
        backup_created_at=result.backup_created_at,
        backup_migration_head=result.backup_migration_head,
        current_migration_head=result.current_migration_head,
        migration_gap_count=result.migration_gap_count,
    )


@router.post("/restore", response_model=BackupRestoreResponse)
def execute_backup_restore(
    backup_file: UploadFile = File(...),
    confirm_text: str = Form(...),
    _: User = Depends(require_admin_no_session_hold),
):
    if confirm_text.strip().upper() != "RESTORE":
        raise HTTPException(status_code=400, detail="Type RESTORE to confirm database restore")

    compatibility, applied_migrations = restore_backup(backup_file)
    return BackupRestoreResponse(
        detail="Backup restored successfully",
        compatibility=compatibility,
        applied_migrations=applied_migrations,
    )
