from datetime import datetime
from pydantic import BaseModel


class BackupSummary(BaseModel):
    file_name: str
    size_bytes: int
    created_at: datetime
    migration_head: str | None = None


class BackupCreateResponse(BaseModel):
    file_name: str
    size_bytes: int
    created_at: datetime
    migration_head: str | None = None


class BackupPreflightResponse(BaseModel):
    valid: bool
    compatibility: str
    reason: str | None = None
    backup_created_at: datetime | None = None
    backup_migration_head: str | None = None
    current_migration_head: str | None = None
    migration_gap_count: int | None = None


class BackupRestoreResponse(BaseModel):
    detail: str
    compatibility: str
    applied_migrations: int


class BackupScheduleResponse(BaseModel):
    """State of the nightly automatic backup, for the Backups page to display."""

    enabled: bool
    email_enabled: bool = False
    schedule_time: str | None = None
    timezone: str | None = None
    keep: int = 0
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_file_name: str | None = None
    last_error: str | None = None
    # Reported apart from last_status: a backup that was written but could not be
    # mailed is a different problem from one that never got written.
    last_email_status: str | None = None
    last_email_detail: str | None = None
