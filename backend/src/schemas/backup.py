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
