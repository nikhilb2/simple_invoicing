"""Account-lifecycle mail: address verification and password reset.

Sent through the platform mailer (PLATFORM_SMTP_*), never through a tenant's
SMTPConfig: a person who is registering has no company yet to send from, and a
password reset must not depend on the company that person works in having set up
mail. Kept apart from services/mail.py for the same reason -- that one reads its
config from the database and writes email_logs rows scoped to a company.

Every sender here is called from a FastAPI background task, after the response
has gone out. That is deliberate: if the request waited on SMTP, "this address
has an account" would take a second longer to answer than "it does not", and the
202 the routes return would leak exactly what it is there to hide. For the same
reason nothing here raises -- a failed send is logged and dropped.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader

from src.core.config import settings

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "email_templates"
# Autoescape is decided per template by extension: the .html bodies escape the
# user's own name, the .txt bodies are plain text and must not grow &amp;s.
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=lambda name: bool(name) and name.endswith(".html"),
)


def is_configured() -> bool:
    return bool(settings.PLATFORM_SMTP_HOST)


def app_link(path: str, **params: str) -> str:
    base = settings.PUBLIC_APP_BASE_URL.rstrip("/")
    return f"{base}{path}?{urlencode(params)}" if params else f"{base}{path}"


def _common_context() -> dict:
    return {
        # base.html shows the brand mark when the ad is on and this name otherwise.
        "company_name": settings.PLATFORM_SMTP_FROM_NAME,
        "ad": {"enabled": settings.SHARE_AD_ENABLED, "brand_name": settings.SHARE_AD_BRAND_NAME},
    }


def _build_message(to: str, subject: str, text_body: str, html_body: str) -> EmailMessage:
    from_email = settings.PLATFORM_SMTP_FROM_EMAIL or settings.PLATFORM_SMTP_USERNAME or ""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.PLATFORM_SMTP_FROM_NAME, from_email))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=from_email.rpartition("@")[2] or None)
    # Plain text first, HTML as the preferred alternative: a client that cannot
    # render the panel still gets a working link.
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def _deliver(msg: EmailMessage) -> None:
    """Hand one message to PLATFORM_SMTP_HOST. Raises on failure; callers log."""
    host = settings.PLATFORM_SMTP_HOST
    port = settings.PLATFORM_SMTP_PORT
    # A verifying context, unlike smtplib's default: these mails carry live
    # credentials (a reset link is one), so a forged certificate must fail the send.
    context = ssl.create_default_context()
    if port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=10, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=10)
    with server:
        if port != 465 and settings.PLATFORM_SMTP_USE_STARTTLS:
            server.starttls(context=context)
        if settings.PLATFORM_SMTP_USERNAME:
            server.login(settings.PLATFORM_SMTP_USERNAME, settings.PLATFORM_SMTP_PASSWORD or "")
        server.send_message(msg)


def _send(to: str, subject: str, template: str, context: dict) -> None:
    if not is_configured():
        logger.warning("Platform mail not sent (%s): PLATFORM_SMTP_HOST is not set", template)
        return
    try:
        ctx = {**_common_context(), **context}
        html_body = _jinja_env.get_template(f"{template}.html").render(**ctx)
        text_body = _jinja_env.get_template(f"{template}.txt").render(**ctx)
        _deliver(_build_message(to, subject, text_body, html_body))
    except Exception:
        # The address is deliberately left out: it is the one thing these routes
        # promise not to disclose, and logs travel further than the database.
        logger.exception("Failed to send %s mail via %s", template, settings.PLATFORM_SMTP_HOST)


def send_verification_email(to: str, token: str) -> None:
    _send(
        to,
        "Confirm your email address",
        "verify_email",
        {"action_url": app_link("/verify-email", token=token), "valid_for": "24 hours"},
    )


def send_password_reset_email(to: str, token: str) -> None:
    _send(
        to,
        "Reset your password",
        "reset_password",
        {"action_url": app_link("/reset-password", token=token), "valid_for": "1 hour"},
    )
