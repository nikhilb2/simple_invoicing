import smtplib
import asyncio
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from sqlalchemy.orm import Session
from src.models.smtp_config import SMTPConfig

logger = logging.getLogger(__name__)

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
) -> MIMEMultipart:
    """Builds a multipart MIME message with HTML and optional attachments."""
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to
    
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
        # Port 465 = implicit SSL; port 587 (or use_tls=True) = STARTTLS
        if config.port == 465 or not config.use_tls:
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

async def send_email(
    db: Session,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[bytes, str]] | None = None,
    cc: list[str] | None = None,
) -> None:
    """
    Asynchronously sends an email by running the blocking SMTP operations 
    in a thread executor.
    """
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

    await asyncio.to_thread(_send_sync, config, msg)
