from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from src.core.config import settings
import base64
import hashlib
import hmac
import logging
import secrets
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet_warned = False

def _get_fernet() -> Fernet:
    # NOTE: Changing SMTP_ENCRYPTION_KEY rotates the Fernet key. SMTP passwords
    # previously encrypted with a different key (or the SECRET_KEY fallback) will
    # fail to decrypt — re-encrypt existing records before switching keys.
    global _fernet_warned
    if settings.SMTP_ENCRYPTION_KEY:
        key = hashlib.sha256(settings.SMTP_ENCRYPTION_KEY.encode()).digest()
    else:
        if not _fernet_warned:
            logger.warning(
                "SMTP_ENCRYPTION_KEY is not set. Falling back to SECRET_KEY for deriving Fernet encryption key."
            )
            _fernet_warned = True
        key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()

def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    # An account created through Google has no password. Treat it exactly like
    # a wrong one, so login cannot tell an attacker which accounts those are.
    if not hashed_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict | None = None,
) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # extra_claims lets the MCP dispatcher mark its short-lived internal tokens
    # ({"src": "mcp", "tool": ...}) for audit. get_current_user reads only sub/type,
    # so extra claims never affect authentication -- and they are spread FIRST so
    # that no caller can ever pass a "type" or "sub" that overrides the real one.
    to_encode = {**(extra_claims or {}), "sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise JWTError("Invalid token") from exc


# ---------------------------------------------------------------------------
# Single-purpose tokens: email verification and password reset
# ---------------------------------------------------------------------------
#
# Same signing key and algorithm as the session tokens, told apart by "type".
# Every reader checks the type it expects, in both directions: get_current_user
# and /auth/refresh accept only "access" and "refresh", and the verify and reset
# endpoints accept only their own. A token minted for one purpose is therefore
# useless for every other, even though all of them carry a "sub".

VERIFY_EMAIL_TOKEN_TYPE = "verify"
RESET_PASSWORD_TOKEN_TYPE = "reset"
VERIFY_EMAIL_TOKEN_TTL = timedelta(hours=24)
RESET_PASSWORD_TOKEN_TTL = timedelta(hours=1)


def create_purpose_token(subject: str, token_type: str, expires_delta: timedelta, claims: dict | None = None) -> str:
    if token_type in ("access", "refresh"):
        raise ValueError("Session tokens are minted by create_access_token / create_refresh_token")
    expire = datetime.utcnow() + expires_delta
    to_encode = {**(claims or {}), "sub": subject, "exp": expire, "type": token_type}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_purpose_token(token: str, token_type: str) -> dict:
    """Decode and require `type == token_type`. Raises JWTError on any mismatch."""
    payload = decode_token(token)
    if payload.get("type") != token_type or not payload.get("sub"):
        raise JWTError("Wrong token type")
    return payload


def password_fingerprint(hashed_password: str | None) -> str:
    """A short, keyed fingerprint of the current password hash, or "none".

    Embedded in a reset token so the token dies the moment the password changes --
    including by being reset with that very token. Keyed with SECRET_KEY so the
    claim, which anyone holding the token can read, says nothing about the hash.
    """
    if not hashed_password:
        return "none"
    digest = hmac.new(settings.SECRET_KEY.encode(), hashed_password.encode(), hashlib.sha256)
    return digest.hexdigest()[:32]


def fingerprint_matches(expected: str | None, hashed_password: str | None) -> bool:
    return bool(expected) and hmac.compare_digest(str(expected), password_fingerprint(hashed_password))


# A real bcrypt hash of a random string, verified against when the account does
# not exist or has no password, so a login for an unknown address costs the same
# bcrypt round as one for a real address and timing does not tell them apart.
_DUMMY_PASSWORD_HASH: str | None = None


def verify_password_constant_time(plain_password: str, hashed_password: str | None) -> bool:
    global _DUMMY_PASSWORD_HASH
    if hashed_password:
        return verify_password(plain_password, hashed_password)
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = pwd_context.hash(secrets.token_urlsafe(32))
    pwd_context.verify(plain_password, _DUMMY_PASSWORD_HASH)
    return False
