import smtplib
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.smtp_config import SMTPConfig
from src.models.email_log import EmailLog
from src.services import platform_mail

logger = logging.getLogger(__name__)

_STATUS_SENDING = "sending"
# First half of the advisory lock key, so these locks cannot collide with another use.
_DAILY_LIMIT_LOCK_NAMESPACE = 7311

def _get_active_smtp_config(db: Session) -> SMTPConfig:
    """Fetches and returns the active SMTP configuration from the database."""
    config = db.query(SMTPConfig).filter(SMTPConfig.is_active.is_(True)).first()
    if config is None:
        logger.error("No active SMTP configuration found in database")
        raise RuntimeError("No active SMTP configuration found")
    return config

def _build_message(
    to: str,
    subject: str,
    html_body: str,
    from_email: str,
    from_name: str,
    attachments: list[tuple[bytes, str]] | None = None,
    cc: list[str] | None = None,
    reply_to: str | None = None,
) -> MIMEMultipart:
    """Builds a multipart MIME message with HTML and optional attachments."""
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to

    if cc:
        msg["Cc"] = ", ".join(cc)

    # Attach HTML body
    msg.attach(MIMEText(html_body, "html"))

    # Add attachments if any
    if attachments:
        for content, filename in attachments:
            # Main use case is PDFs; add _subtype for correct content-type header
            subtype = 'pdf' if filename.lower().endswith('.pdf') else 'octet-stream'
            part = MIMEApplication(content, _subtype=subtype)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

    return msg

def _send_sync(config: SMTPConfig, msg: MIMEMultipart) -> None:
    """Synchronous function to send email via smtplib."""
    # Recipients include 'To' and 'Cc'
    recipients = [msg["To"]]
    if "Cc" in msg:
        recipients.extend([email.strip() for email in msg["Cc"].split(",")])

    try:
        # use_starttls=True  → STARTTLS (typically port 587)
        # use_starttls=False → Implicit SSL/TLS (typically port 465)
        if config.port == 465 or not config.use_starttls:
            with smtplib.SMTP_SSL(config.host, config.port, timeout=10) as server:
                server.login(config.username, config.password)
                server.send_message(msg, to_addrs=recipients)
        else:
            with smtplib.SMTP(config.host, config.port, timeout=10) as server:
                server.starttls()
                server.login(config.username, config.password)
                server.send_message(msg, to_addrs=recipients)
    except Exception:
        logger.exception("Failed to send email via SMTP %s", config.host)
        raise

def _reserve_daily_send(db: Session, company_id: int, log_entry: EmailLog) -> None:
    """Claim one of a company's emails for today, or refuse if they are used up.

    The claim is the log row itself, committed before anything is sent. Counting only
    finished sends would let parallel requests all pass while each waits on SMTP. The
    lock makes the count and the claim one step, and is released by the commit, so it
    is never held across the send. Counted from email_logs rather than in memory so it
    holds across replicas and restarts. A failed send stops counting; a process that
    dies mid-send leaves its claim for 24 hours, which errs on the safe side.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :company)"),
            {"namespace": _DAILY_LIMIT_LOCK_NAMESPACE, "company": company_id},
        )
    since = datetime.now(timezone.utc) - timedelta(days=1)
    used = (
        db.query(func.count(EmailLog.id))
        .filter(
            EmailLog.company_id == company_id,
            EmailLog.status.in_(("sent", _STATUS_SENDING)),
            EmailLog.sent_at >= since,
        )
        .scalar()
    )
    if used >= settings.TENANT_EMAIL_DAILY_LIMIT:
        db.rollback()
        raise RuntimeError(
            f"Daily email limit reached ({settings.TENANT_EMAIL_DAILY_LIMIT} per 24 hours). "
            "Please try again later."
        )
    log_entry.status = _STATUS_SENDING
    db.add(log_entry)
    db.commit()


def _build_platform_message(
    db: Session,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[bytes, str]] | None,
    cc: list[str] | None,
    company_id: int | None,
) -> MIMEMultipart:
    """A tenant's mail on the shared host, once it is allowed to go.

    Always from the platform's authenticated address, so a tenant can never send as
    someone else's domain. The name says whose document it is, and "via" keeps a
    company called "State Bank" from reading as the bank. Replies go to the company.
    """
    if not settings.PLATFORM_SMTP_HOST:
        raise RuntimeError("Email sending is not available right now.")
    company = db.query(CompanyProfile).filter(CompanyProfile.id == company_id).first()
    if company is None:
        raise RuntimeError("Email sending needs a company.")

    # One address per field: the relay delivers to everything these headers name, so
    # a comma-separated list would reach a crowd while counting as one email.
    for address in [to, *(cc or [])]:
        try:
            validate_email(address, check_deliverability=False)
        except EmailNotValidError as exc:
            raise RuntimeError(f"{address} is not a valid email address.") from exc

    company_name = " ".join((company.name or "").split())
    platform_name = settings.PLATFORM_SMTP_FROM_NAME
    reply_to = None
    if company.email:
        # Free text on the company page. A typo there should cost the reply-to
        # address, not every email the company tries to send.
        try:
            reply_to = validate_email(company.email.strip(), check_deliverability=False).normalized
        except EmailNotValidError:
            logger.info("Ignoring invalid reply-to on company %s", company.id)

    return _build_message(
        to=to,
        subject=subject,
        html_body=html_body,
        from_email=settings.PLATFORM_SMTP_FROM_EMAIL or settings.PLATFORM_SMTP_USERNAME or "",
        from_name=f"{company_name} via {platform_name}" if company_name else platform_name,
        attachments=attachments,
        cc=cc,
        reply_to=reply_to,
    )


def _deliver_platform(msg: MIMEMultipart) -> None:
    """Send through the platform relay. What it reports is about the platform (quota,
    a rejected sender), not about the tenant who pressed Send, so it goes to the log
    and they get a message safe to show them and to keep in their email history."""
    try:
        platform_mail._deliver(msg)
    except Exception as exc:
        logger.exception("Failed to send tenant email via %s", settings.PLATFORM_SMTP_HOST)
        raise RuntimeError("The email could not be sent. Please try again later.") from exc


async def send_email(
    db: Session,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[bytes, str]] | None = None,
    cc: list[str] | None = None,
    company_id: int | None = None,
    email_type: str = "other",
    reference_id: int | None = None,
    sent_by_user_id: int | None = None,
    use_smtp_config: bool = False,
) -> None:
    """
    Asynchronously sends an email by running the blocking SMTP operations
    in a thread executor. Logs the attempt to the email_logs table.

    Shared hosting sends through the platform relay and never reads SMTPConfig, unless
    the caller is the platform's own job and asks for use_smtp_config: the backup mail
    is the whole database, which has no business passing through a third-party relay.
    """
    log_entry = EmailLog(
        company_id=company_id,
        to_email=to,
        cc=", ".join(cc) if cc else None,
        subject=subject,
        email_type=email_type,
        reference_id=reference_id,
        sent_by_user_id=sent_by_user_id,
    )
    reserved = False

    if settings.is_shared_hosting and not use_smtp_config:
        msg = _build_platform_message(db, to, subject, html_body, attachments, cc, company_id)
        _reserve_daily_send(db, company_id, log_entry)
        reserved = True
        deliver_args = (_deliver_platform, msg)
    else:
        config = _get_active_smtp_config(db)
        msg = _build_message(
            to=to,
            subject=subject,
            html_body=html_body,
            from_email=config.from_email,
            from_name=config.from_name,
            attachments=attachments,
            cc=cc
        )
        deliver_args = (_send_sync, config, msg)

    exc_to_raise: Exception | None = None
    status = "sent"
    error_message: str | None = None

    try:
        await asyncio.to_thread(*deliver_args)
    except Exception as exc:
        exc_to_raise = exc
        status = "failed"
        error_message = str(exc)

    try:
        log_entry.status = status
        log_entry.error_message = error_message
        if not reserved:
            db.add(log_entry)
        db.commit()
    except Exception:
        logger.warning("Failed to write email log entry", exc_info=True)
        db.rollback()

    if exc_to_raise is not None:
        raise exc_to_raise
