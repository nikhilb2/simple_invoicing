"""Nightly automatic backup scheduling and retention.

Nothing here shells out to pg_dump: the parts worth pinning are when the timer
fires and which files retention is willing to delete.
"""

import asyncio
from datetime import datetime, time, timedelta, timezone

import pytest

from src.services import backup_scheduler
from src.services.backup import AUTO_BACKUP_PREFIX, MANUAL_BACKUP_PREFIX

IST = backup_scheduler.resolve_timezone("Asia/Kolkata")


def test_ist_is_utc_plus_five_thirty():
    offset = IST.utcoffset(datetime(2026, 9, 8, 12, 0))
    assert offset == timedelta(hours=5, minutes=30)


def test_unknown_timezone_falls_back_to_a_fixed_ist_offset():
    tz = backup_scheduler.resolve_timezone("Not/AZone")
    assert tz.utcoffset(datetime(2026, 9, 8, 12, 0)) == timedelta(hours=5, minutes=30)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("00:00", time(0, 0)),
        ("23:30", time(23, 30)),
        ("  02:15  ", time(2, 15)),
        ("01:02:03", time(1, 2, 3)),
    ],
)
def test_parse_schedule_time_accepts_valid_times(raw, expected):
    assert backup_scheduler.parse_schedule_time(raw) == expected


@pytest.mark.parametrize("raw", ["", "midnight", "24:00", "12", "1:2:3:4", "aa:bb"])
def test_parse_schedule_time_rejects_garbage(raw):
    assert backup_scheduler.parse_schedule_time(raw) is None


def test_midnight_ist_is_1830_utc_the_previous_day():
    # 18:35 UTC on the 8th is already 00:05 IST on the 9th, so the next midnight
    # IST is the 10th -- which lands at 18:30 UTC on the 9th.
    now = datetime(2026, 9, 8, 18, 35, tzinfo=timezone.utc)
    assert backup_scheduler.next_run_at(now, time(0, 0), IST) == datetime(
        2026, 9, 9, 18, 30, tzinfo=timezone.utc
    )


def test_next_run_is_later_today_when_the_hour_has_not_passed():
    # 10:00 UTC on the 8th is 15:30 IST, so tonight's midnight is still ahead.
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    assert backup_scheduler.next_run_at(now, time(0, 0), IST) == datetime(
        2026, 9, 8, 18, 30, tzinfo=timezone.utc
    )


def test_next_run_never_returns_the_current_instant():
    """Exactly on the mark, the answer is tomorrow -- otherwise the loop would see
    a zero-second wait, fire, and immediately schedule the same instant again."""
    now = datetime(2026, 9, 8, 18, 30, tzinfo=timezone.utc)
    assert backup_scheduler.next_run_at(now, time(0, 0), IST) == datetime(
        2026, 9, 9, 18, 30, tzinfo=timezone.utc
    )


def _write(dir_path, name):
    path = dir_path / name
    path.write_bytes(b"x")
    return path


def test_retention_keeps_the_newest_and_spares_manual_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr("src.services.backup.BACKUP_DIR", tmp_path)

    for day in range(1, 6):
        _write(tmp_path, f"{AUTO_BACKUP_PREFIX}2026090{day}_183000.enc")
    manual = _write(tmp_path, f"{MANUAL_BACKUP_PREFIX}20260901_120000.enc")

    removed = backup_scheduler.prune_auto_backups(3)

    assert sorted(removed) == [
        f"{AUTO_BACKUP_PREFIX}20260901_183000.enc",
        f"{AUTO_BACKUP_PREFIX}20260902_183000.enc",
    ]
    survivors = sorted(p.name for p in tmp_path.iterdir())
    assert survivors == [
        f"{AUTO_BACKUP_PREFIX}20260903_183000.enc",
        f"{AUTO_BACKUP_PREFIX}20260904_183000.enc",
        f"{AUTO_BACKUP_PREFIX}20260905_183000.enc",
        manual.name,
    ]


def test_retention_is_a_no_op_below_the_keep_count(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr("src.services.backup.BACKUP_DIR", tmp_path)
    _write(tmp_path, f"{AUTO_BACKUP_PREFIX}20260901_183000.enc")

    assert backup_scheduler.prune_auto_backups(7) == []
    assert len(list(tmp_path.iterdir())) == 1


def test_retention_of_zero_deletes_nothing(tmp_path, monkeypatch):
    """A misconfigured AUTO_BACKUP_KEEP=0 must not wipe the directory."""
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr("src.services.backup.BACKUP_DIR", tmp_path)
    _write(tmp_path, f"{AUTO_BACKUP_PREFIX}20260901_183000.enc")

    assert backup_scheduler.prune_auto_backups(0) == []
    assert len(list(tmp_path.iterdir())) == 1


# --- the run step, including the email hand-off ----------------------------

class _Outcome:
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def _reset_status():
    backup_scheduler.status.last_status = None
    backup_scheduler.status.last_error = None
    backup_scheduler.status.last_file_name = None
    backup_scheduler.status.last_email_status = None
    backup_scheduler.status.last_email_detail = None


def test_a_successful_run_emails_the_archive_it_just_wrote(tmp_path, monkeypatch):
    _reset_status()
    archive = tmp_path / f"{AUTO_BACKUP_PREFIX}20260909_183000.enc"
    archive.write_bytes(b"x")
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(
        backup_scheduler,
        "run_auto_backup",
        lambda: {
            "file_name": archive.name,
            "created_at": datetime(2026, 9, 9, 18, 30, tzinfo=timezone.utc),
            "migration_head": "head",
        },
    )

    seen = {}

    async def fake_email(**kwargs):
        seen.update(kwargs)
        return _Outcome("sent", "Emailed to ops@example.com.")

    monkeypatch.setattr(backup_scheduler, "email_backup_archive", fake_email)
    asyncio.run(backup_scheduler._run_once(IST))

    assert backup_scheduler.status.last_status == "success"
    assert backup_scheduler.status.last_email_status == "sent"
    assert seen["archive_path"] == archive
    # The timestamp in the email reads in the schedule's own timezone, not UTC --
    # a backup labelled 18:30 would be baffling to someone who set it for midnight.
    assert seen["display_timezone"] is IST


def test_a_failed_backup_does_not_attempt_an_email(tmp_path, monkeypatch):
    _reset_status()
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", tmp_path)

    def boom():
        raise RuntimeError("pg_dump exploded")

    monkeypatch.setattr(backup_scheduler, "run_auto_backup", boom)

    async def fail(**_kwargs):
        raise AssertionError("must not email when there is no backup")

    monkeypatch.setattr(backup_scheduler, "email_backup_archive", fail)
    asyncio.run(backup_scheduler._run_once(IST))

    assert backup_scheduler.status.last_status == "failed"
    assert "pg_dump exploded" in backup_scheduler.status.last_error
    assert backup_scheduler.status.last_email_status is None


def test_a_failed_email_leaves_the_backup_reported_as_successful(tmp_path, monkeypatch):
    """The archive on disk is real whether or not the mail server answered."""
    _reset_status()
    archive = tmp_path / f"{AUTO_BACKUP_PREFIX}20260909_183000.enc"
    archive.write_bytes(b"x")
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(
        backup_scheduler,
        "run_auto_backup",
        lambda: {"file_name": archive.name, "created_at": datetime.now(timezone.utc), "migration_head": None},
    )

    async def fake_email(**_kwargs):
        return _Outcome("failed", "Backup email to ops@example.com failed: connection refused")

    monkeypatch.setattr(backup_scheduler, "email_backup_archive", fake_email)
    asyncio.run(backup_scheduler._run_once(IST))

    assert backup_scheduler.status.last_status == "success"
    assert backup_scheduler.status.last_email_status == "failed"


def test_email_is_skipped_when_the_archive_is_already_gone(tmp_path, monkeypatch):
    _reset_status()
    monkeypatch.setattr(backup_scheduler, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(
        backup_scheduler,
        "run_auto_backup",
        lambda: {
            "file_name": f"{AUTO_BACKUP_PREFIX}20260909_183000.enc",
            "created_at": datetime.now(timezone.utc),
            "migration_head": None,
        },
    )

    async def fail(**_kwargs):
        raise AssertionError("must not read an archive that is not there")

    monkeypatch.setattr(backup_scheduler, "email_backup_archive", fail)
    asyncio.run(backup_scheduler._run_once(IST))

    assert backup_scheduler.status.last_status == "success"
    assert backup_scheduler.status.last_email_status == "skipped"
