"""Nightly automatic backups.

An in-process asyncio task that wakes at a fixed wall-clock time -- midnight IST
by default -- runs the same archive routine the Backups page calls, prunes old
scheduled archives down to ``AUTO_BACKUP_KEEP``, and mails the result to the
admins when the deployment has SMTP set up (see ``src.services.backup_email``).

Why in-process rather than a CronJob or an external crontab: the app already ships
as one container per tenant with ``replicas: 1``, so a scheduler thread is the only
mechanism that needs no per-namespace infrastructure and no second copy of the
database credentials. The single-replica assumption is load-bearing -- run two
replicas and both will dump at midnight. That is wasteful rather than dangerous
(each writes to its own container-local disk under its own timestamped name), but
if this ever scales out, the run needs a Postgres advisory lock around it.

Deliberately no catch-up run on startup. BACKUP_DIR is container-local, so a
restart clears every archive and a catch-up rule would fire on every single
deploy -- and a crash-looping pod would dump in a tight loop. Missing one night
after a restart is the cheaper failure.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.core.config import settings
from src.services.backup import AUTO_BACKUP_PREFIX, BACKUP_DIR, create_backup_archive, ensure_backup_dir
from src.services.backup_email import email_backup_archive

logger = logging.getLogger(__name__)

# IST is UTC+5:30 year round and has no DST, so this is exact rather than an
# approximation -- it exists only so a slim image with no tzdata still schedules
# correctly instead of taking the app down over a missing timezone database.
_IST_FALLBACK = timezone(timedelta(hours=5, minutes=30), name="IST")

# Never sleep longer than this in one go. Re-deriving the target each time is what
# keeps the schedule honest across a suspended laptop or a corrected system clock.
_MAX_SLEEP_SECONDS = 900


@dataclass
class SchedulerStatus:
    enabled: bool = False
    email_enabled: bool = False
    schedule_time: str | None = None
    timezone_name: str | None = None
    keep: int = 0
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_file_name: str | None = None
    last_error: str | None = None
    last_email_status: str | None = None
    last_email_detail: str | None = None


status = SchedulerStatus()
_task: asyncio.Task | None = None


def resolve_timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "Timezone %r is not available; falling back to a fixed UTC+05:30 offset for automatic backups.",
            name,
        )
        return _IST_FALLBACK


def parse_schedule_time(raw: str) -> time | None:
    """Parse "HH:MM" (or "HH:MM:SS"). Returns None for anything unusable."""
    try:
        parts = [int(part) for part in raw.strip().split(":")]
    except ValueError:
        return None
    if not 2 <= len(parts) <= 3:
        return None
    try:
        return time(*parts)
    except ValueError:
        return None


def next_run_at(after: datetime, at: time, tz: tzinfo) -> datetime:
    """First occurrence of ``at`` in ``tz`` strictly after ``after``, as UTC."""
    local_now = after.astimezone(tz)
    candidate = local_now.replace(
        hour=at.hour, minute=at.minute, second=at.second, microsecond=0
    )
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def prune_auto_backups(keep: int) -> list[str]:
    """Delete all but the newest ``keep`` scheduled archives.

    Only files carrying AUTO_BACKUP_PREFIX are considered, so a backup someone
    created by hand -- the one they made right before a risky import -- is never
    swept up by retention. Timestamps in the name are UTC and zero-padded, which
    makes a reverse name sort the same as newest-first.
    """
    if keep <= 0:
        return []

    ensure_backup_dir()
    archives = sorted(BACKUP_DIR.glob(f"{AUTO_BACKUP_PREFIX}*.enc"), reverse=True)

    removed: list[str] = []
    for path in archives[keep:]:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            logger.exception("Could not delete old automatic backup %s", path.name)
    return removed


def run_auto_backup() -> dict:
    """Create one scheduled archive and apply retention. Blocking; call in a thread."""
    result = create_backup_archive(file_prefix=AUTO_BACKUP_PREFIX)
    removed = prune_auto_backups(settings.AUTO_BACKUP_KEEP)
    if removed:
        logger.info("Automatic backup retention removed %d old archive(s): %s", len(removed), ", ".join(removed))
    return result


async def _run_once(tz: tzinfo) -> None:
    try:
        result = await asyncio.to_thread(run_auto_backup)
    except Exception as exc:  # noqa: BLE001 -- one bad night must not kill the loop
        status.last_run_at = datetime.now(timezone.utc)
        status.last_status = "failed"
        status.last_error = str(getattr(exc, "detail", None) or exc)
        status.last_email_status = None
        status.last_email_detail = None
        logger.exception("Automatic backup failed")
        return

    status.last_run_at = datetime.now(timezone.utc)
    status.last_status = "success"
    status.last_file_name = result["file_name"]
    status.last_error = None
    logger.info("Automatic backup created: %s", result["file_name"])

    # Reported separately from the backup itself and deliberately so: a mail server
    # that is down does not make the archive on disk any less real, and an admin
    # reading the Backups page needs to be able to tell those two failures apart.
    # Retention may already have pruned the file if AUTO_BACKUP_KEEP is 1 and a
    # newer run raced in, so this re-checks rather than trusting the name.
    archive_path = BACKUP_DIR / result["file_name"]
    if not archive_path.exists():
        status.last_email_status = "skipped"
        status.last_email_detail = "The archive was no longer on disk when the email was prepared."
        return

    outcome = await email_backup_archive(
        archive_path=archive_path,
        created_at=result["created_at"],
        migration_head=result["migration_head"],
        display_timezone=tz,
    )
    status.last_email_status = outcome.status
    status.last_email_detail = outcome.detail
    logger.info("Automatic backup email: %s -- %s", outcome.status, outcome.detail)


async def _loop(at: time, tz: tzinfo, target: datetime) -> None:
    """Wait for ``target``, back up, then re-derive the next one.

    ``target`` is passed in rather than computed here because ``create_task`` does
    not run a coroutine body until the loop next yields -- computing it here left
    ``status.next_run_at`` reading None to any request that arrived in the gap.
    """
    while True:
        remaining = (target - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            await asyncio.sleep(min(remaining, _MAX_SLEEP_SECONDS))
            continue

        await _run_once(tz)
        target = next_run_at(datetime.now(timezone.utc), at, tz)
        status.next_run_at = target


def start_scheduler() -> None:
    """Start the nightly loop. Safe to call when disabled or misconfigured."""
    global _task

    status.enabled = False
    status.schedule_time = settings.AUTO_BACKUP_TIME
    status.timezone_name = settings.AUTO_BACKUP_TIMEZONE
    status.keep = settings.AUTO_BACKUP_KEEP
    status.next_run_at = None
    status.email_enabled = settings.AUTO_BACKUP_EMAIL_ENABLED

    if not settings.AUTO_BACKUP_ENABLED:
        logger.info("Automatic backups are disabled (AUTO_BACKUP_ENABLED=false).")
        return

    at = parse_schedule_time(settings.AUTO_BACKUP_TIME)
    if at is None:
        # Same trade as disable_mcp_without_public_urls: degrade the optional
        # feature loudly, never refuse to serve invoices over it.
        logger.error(
            "AUTO_BACKUP_TIME=%r is not a valid HH:MM time. Automatic backups are off.",
            settings.AUTO_BACKUP_TIME,
        )
        return

    tz = resolve_timezone(settings.AUTO_BACKUP_TIMEZONE)
    target = next_run_at(datetime.now(timezone.utc), at, tz)
    status.enabled = True
    status.next_run_at = target
    _task = asyncio.create_task(_loop(at, tz, target))
    logger.info(
        "Automatic backups scheduled daily at %s %s (keeping %d). Next run: %s",
        settings.AUTO_BACKUP_TIME,
        settings.AUTO_BACKUP_TIMEZONE,
        settings.AUTO_BACKUP_KEEP,
        target.isoformat(),
    )


async def stop_scheduler() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    status.enabled = False
    status.next_run_at = None
