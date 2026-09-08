"""Mails a finished automatic backup to the people who administer the app.

Gated on an active SMTP configuration existing: a deployment that never set up
email is not an error here, it just means nothing is sent. The recipients default
to every admin user because the Backups page is already admin-only -- those are
the people the database is entrusted to.

The attachment is the same Fernet-encrypted archive the Backups page serves, so
putting it in a mailbox does not hand anyone the data: restoring it needs a server
holding the same BACKUP_ENCRYPTION_KEY. That is what makes this safe to do
automatically, and it is also the catch -- an archive mailed out of a deployment
whose key is later lost is unrecoverable.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.core.config import settings
from src.db.session import SessionLocal
from src.models.company import CompanyProfile
from src.models.smtp_config import SMTPConfig
from src.models.user import User, UserRole
from src.services.mail import send_email

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "email_templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)

EMAIL_TYPE = "automatic_backup"


@dataclass
class EmailOutcome:
    """What happened, in the same shape whether or not anything was sent.

    ``status`` is one of "sent", "skipped" or "failed"; ``detail`` is a sentence
    fit to show an admin on the Backups page.
    """

    status: str
    detail: str


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def resolve_recipients(db) -> list[str]:
    """AUTO_BACKUP_EMAIL_TO if set, otherwise every admin user's address.

    Deduplicated and sorted so the recipient list -- and the email_logs row that
    records it -- does not churn with database ordering.
    """
    override = settings.AUTO_BACKUP_EMAIL_TO.strip()
    if override:
        addresses = [part.strip() for part in override.split(",")]
    else:
        addresses = [
            user.email
            for user in db.query(User).filter(User.role == UserRole.admin).all()
            if user.email
        ]
    return sorted({address for address in addresses if address})


def _company_context(db) -> dict:
    """Header and footer details for base.html.

    Falls back to empty values rather than failing: an install with no company
    profile yet still gets its backup mailed, just with a bare header.
    """
    company = db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    if company is None:
        return {"company_name": "Simple Invoicing"}
    return {
        "company_name": company.name,
        "company_email": company.email,
        "company_phone": company.phone_number,
        "company_address": company.address,
    }


async def email_backup_archive(
    archive_path: Path,
    created_at: datetime,
    migration_head: str | None,
    display_timezone=timezone.utc,
) -> EmailOutcome:
    """Mail one finished archive. Never raises -- the backup itself already succeeded.

    Opens its own session: this runs on a timer, with no request and therefore no
    dependency-injected one, and it is the only thing holding it.
    """
    if not settings.AUTO_BACKUP_EMAIL_ENABLED:
        return EmailOutcome("skipped", "Backup email is turned off (AUTO_BACKUP_EMAIL_ENABLED).")

    db = SessionLocal()
    try:
        # Checked directly rather than by catching send_email's RuntimeError: an
        # install with no mail set up is an expected state, not a failure, and it
        # should not leave a scary "failed" line on the Backups page.
        if db.query(SMTPConfig).filter(SMTPConfig.is_active.is_(True)).first() is None:
            return EmailOutcome("skipped", "No active SMTP configuration, so no backup email was sent.")

        recipients = resolve_recipients(db)
        if not recipients:
            return EmailOutcome(
                "skipped",
                "No admin email address to send to. Set AUTO_BACKUP_EMAIL_TO or give an admin user an email address.",
            )

        size_bytes = archive_path.stat().st_size
        limit_bytes = max(settings.AUTO_BACKUP_EMAIL_MAX_MB, 0) * 1024 * 1024
        attached = size_bytes <= limit_bytes
        skip_reason = (
            None
            if attached
            else (
                f"It is {_format_size(size_bytes)}, over the "
                f"{settings.AUTO_BACKUP_EMAIL_MAX_MB} MB limit for mailed backups."
            )
        )

        html_body = _jinja_env.get_template("backup_email.html").render(
            file_name=archive_path.name,
            created_at=created_at.astimezone(display_timezone).strftime("%d %b %Y, %H:%M"),
            size_label=_format_size(size_bytes),
            migration_head=migration_head,
            attached=attached,
            skip_reason=skip_reason,
            keep=settings.AUTO_BACKUP_KEEP,
            **_company_context(db),
        )

        # Read only when it is actually going out -- a large archive must not be
        # pulled into memory just to be discarded.
        attachments = [(archive_path.read_bytes(), archive_path.name)] if attached else None

        subject = f"Backup {'attached' if attached else 'completed'} — {archive_path.name}"

        try:
            await send_email(
                db=db,
                to=recipients[0],
                subject=subject,
                html_body=html_body,
                attachments=attachments,
                cc=recipients[1:] or None,
                email_type=EMAIL_TYPE,
            )
        except Exception as exc:  # noqa: BLE001 -- a failed email must not fail the backup
            logger.exception("Could not email the automatic backup")
            return EmailOutcome("failed", f"Backup email to {recipients[0]} failed: {exc}")

        recipient_label = recipients[0] if len(recipients) == 1 else f"{recipients[0]} +{len(recipients) - 1}"
        if attached:
            return EmailOutcome("sent", f"Emailed to {recipient_label}.")
        return EmailOutcome("sent", f"Emailed to {recipient_label} without the archive: {skip_reason}")
    except Exception as exc:  # noqa: BLE001 -- same reason; the archive is already safely written
        logger.exception("Unexpected error while emailing the automatic backup")
        return EmailOutcome("failed", f"Backup email failed: {exc}")
    finally:
        db.close()
