import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from jose import JWTError
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.models.oauth_login_code import OAuthLoginCode
from src.models.user import User, UserRole
from src.models.user_identity import UserIdentity
from src.schemas.auth import (
    AuthConfigOut,
    ChangePasswordRequest,
    ChangePasswordResponse,
    DetailResponse,
    EmailRequest,
    LoginRequest,
    OAuthExchangeRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    Token,
    VerifyEmailDetailsOut,
    VerifyEmailDetailsRequest,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from src.schemas.user import UserOut
from src.core.config import settings
from src.services.company_access import company_role, first_accessible_company, is_platform_admin
from src.core.rate_limit import TokenBucket, client_ip
from src.core.security import (
    RESET_PASSWORD_TOKEN_TTL,
    RESET_PASSWORD_TOKEN_TYPE,
    VERIFY_EMAIL_TOKEN_TTL,
    VERIFY_EMAIL_TOKEN_TYPE,
    create_access_token,
    create_purpose_token,
    create_refresh_token,
    decode_purpose_token,
    decode_token,
    fingerprint_matches,
    get_password_hash,
    password_fingerprint,
    session_revoked,
    verify_password,
    verify_password_constant_time,
)
from src.api.deps import get_current_user, get_session_user
from src.core.analytics import distinct_id_for, track
from src.services import auth_providers, platform_mail

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _error(status_code: int, code: str, message: str, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message}, headers=headers)


def normalize_email(email: str) -> str:
    """Strip, and lowercase the ASCII letters only.

    Deliberately not str.lower(): full Unicode case mapping folds distinct
    characters together (the dotted capital I and "i", among others), and an
    address that folds onto someone else's is the classic way to take over their
    account through a "case-insensitive" lookup. ASCII case is the only case
    every mail system agrees is insignificant.
    """
    return "".join(ch.lower() if ch.isascii() else ch for ch in email.strip())


def find_user_by_email(db: Session, email: str) -> User | None:
    """The account for an address, ignoring ASCII case.

    Users created before this existed may be stored in mixed case, so an exact
    match wins, then the lowest id among case variants. SQL lower() casts the
    wider net (Postgres lowercases non-ASCII too); the ASCII-only comparison in
    Python then decides, so no Unicode case folding can ever match an account.
    """
    normalized = normalize_email(email)
    exact = db.query(User).filter(User.email == email.strip()).first()
    if exact is not None:
        return exact
    candidates = (
        db.query(User)
        .filter(func.lower(User.email) == func.lower(normalized))
        .order_by(User.id.asc())
        .all()
    )
    for candidate in candidates:
        if normalize_email(candidate.email) == normalized:
            return candidate
    return None


def _issue_tokens(user: User) -> dict:
    return {
        "access_token": create_access_token(subject=user.email),
        "refresh_token": create_refresh_token(subject=user.email),
        "token_type": "bearer",
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------
#
# Per replica, in memory -- see src/core/rate_limit.py. Every limit is keyed by
# both IP and email: the IP alone is spoofable wherever the API is reachable
# without the ingress in front, and the email alone would let one address spray
# guesses across every account.

# Every login attempt counts against the IP. Generous, because an office or a
# mobile carrier puts many honest people behind one address.
_LOGIN_BY_IP = TokenBucket(capacity=30, refill_per_second=0.5)
# Only FAILED attempts count against an account, so a correct password costs
# nothing. Two buckets: a tight one per (address, IP), which is what stops one
# source guessing, and a loose one per address across all IPs, which caps a
# distributed guess without letting one stranger lock the owner out -- ten wrong
# guesses from the attacker's IP block that IP for that address, not the owner.
_LOGIN_FAILURES_BY_EMAIL_IP = TokenBucket(capacity=10, refill_per_second=1 / 60)
_LOGIN_FAILURES_BY_EMAIL = TokenBucket(capacity=100, refill_per_second=1 / 30)
# register, resend-verification and forgot-password all send mail, so they share
# one allowance per address, which is what stops the API being used to bury a
# stranger's inbox. Same two-bucket shape as login: a tight one per (address, IP)
# stops one source, and a loose one per address caps a distributed attempt without
# letting one stranger keep the owner from ever getting a reset link.
_MAIL_BY_IP = TokenBucket(capacity=10, refill_per_second=1 / 60)
_MAIL_BY_EMAIL_IP = TokenBucket(capacity=3, refill_per_second=1 / 300)
_MAIL_BY_EMAIL = TokenBucket(capacity=20, refill_per_second=1 / 600)
_EXCHANGE_BY_IP = TokenBucket(capacity=20, refill_per_second=1 / 3)


def _too_many() -> HTTPException:
    return _error(429, "rate_limited", "Too many attempts. Please wait a few minutes and try again.", {"Retry-After": "60"})


def _limit_mail_request(request: Request, email: str) -> None:
    ip = client_ip(request)
    if _MAIL_BY_IP.hit(ip) or _MAIL_BY_EMAIL_IP.hit(f"{email}|{ip}") or _MAIL_BY_EMAIL.hit(email):
        raise _too_many()


# ---------------------------------------------------------------------------
# Verification / reset tokens
# ---------------------------------------------------------------------------

def _verify_token_for(user: User) -> str:
    # The address rides along so a token minted before an address change cannot
    # verify the new one. So does the password fingerprint, so a link stops working
    # if the account's password is set some other way first.
    return create_purpose_token(
        str(user.id),
        VERIFY_EMAIL_TOKEN_TYPE,
        VERIFY_EMAIL_TOKEN_TTL,
        {"email": user.email, "pwd": password_fingerprint(user.hashed_password)},
    )


def _reset_token_for(user: User) -> str:
    return create_purpose_token(
        str(user.id),
        RESET_PASSWORD_TOKEN_TYPE,
        RESET_PASSWORD_TOKEN_TTL,
        {"email": user.email, "pwd": password_fingerprint(user.hashed_password)},
    )


def _user_from_purpose_token(db: Session, token: str, token_type: str) -> tuple[User, dict]:
    invalid = _error(400, "invalid_token", "This link is invalid or has expired.")
    try:
        payload = decode_purpose_token(token, token_type)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        raise invalid
    user = db.get(User, user_id)
    if user is None or user.email != payload.get("email"):
        raise invalid
    return user, payload


def _user_for_verify_link(db: Session, token: str) -> User:
    user, claims = _user_from_purpose_token(db, token, VERIFY_EMAIL_TOKEN_TYPE)
    # Refused once verified, not just skipped: this link sets a password, so an old
    # one replayed from a mailbox must not be able to change it.
    if (
        user.email_verified
        or not user.is_active
        or not fingerprint_matches(claims.get("pwd"), user.hashed_password)
    ):
        raise _error(400, "invalid_token", "This link is invalid or has expired.")
    return user


# sha256 of the address a verification link was last requested for, kept in the same
# browser's session cookie. The link proves control of a mailbox but not that the
# person holding it owns that mailbox: an attacker can register their own address and
# send the link to a victim. Signing the victim straight in would leave them entering
# customers and bank details in an account the attacker can reset their way into, the
# attack _OAUTH_CODE_SESSION_KEY stops for Google sign-in. So only the browser that
# asked for the link is signed in; any other is sent to the sign-in page, where the
# victim's own address will not open the attacker's account.
_VERIFY_LINK_SESSION_KEY = "verify_link_email"


def _note_link_asked_for_here(request: Request, email: str) -> None:
    # Whether or not the address has an account, so the cookie says nothing about that.
    request.session[_VERIFY_LINK_SESSION_KEY] = _hash_code(email)


def _asked_for_link_here(request: Request, user: User) -> bool:
    expected = request.session.pop(_VERIFY_LINK_SESSION_KEY, None)
    return isinstance(expected, str) and hmac.compare_digest(expected, _hash_code(normalize_email(user.email)))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Every route added for signup and social sign-in is out of the OpenAPI schema,
# for the reason given on /logout below: the MCP registry turns each documented
# operation into a tool, and registering accounts, sending mail to an address or
# driving a browser redirect are not things an LLM should be able to do.
@router.get("/config", response_model=AuthConfigOut, include_in_schema=False)
def auth_config():
    return {
        "password_signup_enabled": settings.password_signup_enabled,
        "password_reset_enabled": platform_mail.is_configured(),
        "providers": [{"id": spec.id, "name": spec.name} for spec in auth_providers.enabled_providers()],
    }


# ---------------------------------------------------------------------------
# Email + password
# ---------------------------------------------------------------------------

@router.post("/login", response_model=Token)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    ip = client_ip(request)
    email_ip = f"{email}|{ip}"
    if _LOGIN_BY_IP.hit(ip) or _LOGIN_FAILURES_BY_EMAIL_IP.blocked(email_ip) or _LOGIN_FAILURES_BY_EMAIL.blocked(email):
        raise _too_many()

    user = find_user_by_email(db, payload.email)
    # verify_password_constant_time spends one bcrypt round even when there is no
    # account or no password, so how long this takes says nothing about which.
    if not verify_password_constant_time(payload.password, user.hashed_password if user else None):
        _LOGIN_FAILURES_BY_EMAIL_IP.hit(email_ip)
        _LOGIN_FAILURES_BY_EMAIL.hit(email)
        # Without this, a spike in failed sign-ins looks exactly like people
        # simply not showing up. The reason separates "wrong password, tell
        # support to reset it" from "typed the wrong address" -- and for an
        # address that is not an account, $process_person_profile keeps PostHog
        # from minting a person out of a stranger's typo or an enumeration probe.
        track(
            "login_failed",
            payload.email,
            {
                "reason": "unknown_email" if not user else "bad_password",
                **({} if user else {"$process_person_profile": False}),
            },
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Only after the password is proven: otherwise these would tell anyone which
    # addresses have accounts and in what state.
    if not user.is_active:
        raise _error(403, "account_inactive", "This account has been deactivated.")
    if settings.is_shared_hosting and not user.email_verified:
        raise _error(403, "email_not_verified", "Please verify your email address before signing in.")

    # $set rides along on the event rather than going out as its own person
    # update: role and active company are wanted for segmenting, and login is
    # the moment they are known to be current.
    track(
        "user_logged_in",
        distinct_id_for(user),
        {
            "method": "password",
            "$set": {
                "email": user.email,
                "role": getattr(user.role, "value", user.role),
                "active_company_id": user.active_company_id,
            },
        },
    )
    return _issue_tokens(user)


@router.post("/register", status_code=202, response_model=DetailResponse, include_in_schema=False)
def register(
    payload: RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create an unverified, password-less account and mail the verification link.

    The owner chooses their name and password on the page that link opens, so
    registering an address cannot decide its verified profile or password.

    The answer is the same 202 whether or not the address already has an account, and
    the mail goes out after the response, so this is no oracle for who is registered.
    """
    if not settings.password_signup_enabled:
        raise HTTPException(status_code=404, detail="Not Found")

    email = normalize_email(payload.email)
    _limit_mail_request(request, email)
    _note_link_asked_for_here(request, email)
    accepted = {"detail": "Check your inbox for a link to confirm your email address."}

    existing = find_user_by_email(db, email)
    if existing is not None:
        # A verified account is left exactly as it is. An unverified one is still only
        # a claim, so its profile stays as it is and it gets a fresh link, sent to
        # the address on the account, never the one just typed. Earlier links keep working: a stranger
        # registering this address must not be able to kill the owner's.
        if existing.is_active and not existing.email_verified:
            background_tasks.add_task(platform_mail.send_verification_email, existing.email, _verify_token_for(existing))
        return accepted

    user = User(
        email=email,
        full_name=payload.full_name.strip() or email,
        hashed_password=None,
        # Global role is staff; in shared hosting what a user may do in a company
        # comes from their membership there.
        role=UserRole.staff,
        email_verified_at=None,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent registration of the same address won the race. Same answer.
        db.rollback()
        return accepted
    db.refresh(user)

    track(
        "user_signed_up",
        distinct_id_for(user),
        {"method": "password", "$set": {"email": user.email, "role": UserRole.staff.value}},
    )
    background_tasks.add_task(platform_mail.send_verification_email, user.email, _verify_token_for(user))
    return accepted


@router.post("/verify-email/details", response_model=VerifyEmailDetailsOut, include_in_schema=False)
def verify_email_details(payload: VerifyEmailDetailsRequest, db: Session = Depends(get_db)):
    """The name to start the set-password form with. Reads only, so a mail scanner
    running the page changes nothing, and a POST so the token stays out of the URL.

    Registration's name is still only a claim: anyone can register anyone's address.
    The owner sees it in the form and /verify-email takes what they submit, so it
    becomes the account's name only if they keep it.
    """
    user = _user_for_verify_link(db, payload.token)
    return {"full_name": "" if user.full_name == user.email else user.full_name}


@router.post("/verify-email", response_model=VerifyEmailResponse, include_in_schema=False)
def verify_email(payload: VerifyEmailRequest, request: Request, db: Session = Depends(get_db)):
    user = _user_for_verify_link(db, payload.token)

    user.full_name = payload.full_name
    user.hashed_password = get_password_hash(payload.new_password)
    user.email_verified_at = _now()
    user.sessions_valid_after = _now()
    db.commit()
    track("email_verified", distinct_id_for(user), {"method": "link"})

    response = {"detail": "Your email address is confirmed and your password is set. You can sign in now."}
    if _asked_for_link_here(request, user):
        track(
            "user_logged_in",
            distinct_id_for(user),
            {
                "method": "email_link",
                "$set": {
                    "email": user.email,
                    "role": getattr(user.role, "value", user.role),
                    "active_company_id": user.active_company_id,
                },
            },
        )
        response.update(_issue_tokens(user))
    return response


@router.post("/resend-verification", status_code=202, response_model=DetailResponse, include_in_schema=False)
def resend_verification(
    payload: EmailRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if not platform_mail.is_configured():
        raise HTTPException(status_code=404, detail="Not Found")

    email = normalize_email(payload.email)
    _limit_mail_request(request, email)
    _note_link_asked_for_here(request, email)
    user = find_user_by_email(db, email)
    if user is not None and user.is_active and not user.email_verified:
        background_tasks.add_task(platform_mail.send_verification_email, user.email, _verify_token_for(user))
    return {"detail": "If that address is waiting to be confirmed, a new link is on its way."}


@router.post("/forgot-password", status_code=202, response_model=DetailResponse, include_in_schema=False)
def forgot_password(
    payload: EmailRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if not platform_mail.is_configured():
        raise HTTPException(status_code=404, detail="Not Found")

    email = normalize_email(payload.email)
    _limit_mail_request(request, email)
    user = find_user_by_email(db, email)
    if user is not None and user.is_active:
        # Sent to the address stored on the account, never to the one typed: the
        # lookup ignores case, and a reset link must only ever reach the inbox
        # that owns the account.
        background_tasks.add_task(platform_mail.send_password_reset_email, user.email, _reset_token_for(user))
    return {"detail": "If that address has an account, a link to reset its password is on its way."}


@router.post("/reset-password", response_model=DetailResponse, include_in_schema=False)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user, claims = _user_from_purpose_token(db, payload.token, RESET_PASSWORD_TOKEN_TYPE)
    # The token carries a fingerprint of the password it was issued against. Once
    # the password changes -- by this very token, or any other way -- it no
    # longer matches, which is what makes the link single-use.
    if not user.is_active or not fingerprint_matches(claims.get("pwd"), user.hashed_password):
        raise _error(400, "invalid_token", "This link is invalid or has expired.")

    user.hashed_password = get_password_hash(payload.new_password)
    # The link arrived in that inbox, so the address is proven too.
    if not user.email_verified:
        user.email_verified_at = _now()
        if settings.is_shared_hosting:
            user.full_name = user.email
    # A reset is what someone does when they think their password is known to
    # somebody else, so every session signed in before it stops refreshing.
    user.sessions_valid_after = _now()
    db.commit()
    return {"detail": "Your password has been reset. You can sign in with it now."}


# Deliberately out of the OpenAPI schema: the MCP registry turns every documented
# operation into a callable tool (src/mcp_server/registry.py), and "log the user
# out" is not an action an LLM should be able to take. The browser calls it so
# that signing out is counted where every other event is counted -- on the
# server -- rather than being the one event left behind in the bundle.
@router.post("/logout", status_code=204, include_in_schema=False)
def logout(current_user: User = Depends(get_current_user)):
    track("user_logged_out", distinct_id_for(current_user))
    return Response(status_code=204)


@router.post("/refresh", response_model=Token)
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        decoded = decode_token(payload.refresh_token)
    except JWTError:
        raise credentials_exception

    if decoded.get("type") != "refresh":
        raise credentials_exception

    email = decoded.get("sub")
    if not email:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    # A deactivated account stops getting new tokens, and so does a session that
    # began before the password was reset; access tokens already out run out
    # within ACCESS_TOKEN_EXPIRE_MINUTES.
    if not user or not user.is_active or session_revoked(user.sessions_valid_after, decoded):
        raise credentials_exception

    return _issue_tokens(user)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = UserOut.model_validate(current_user)
    if settings.is_shared_hosting:
        role = None
        if current_user.active_company_id is not None:
            role = company_role(db, current_user, current_user.active_company_id)
        if role is None:
            # The same fallback get_active_company takes, so this reports the role
            # in the company the next request will actually act on.
            first = first_accessible_company(db, current_user)
            if first is not None:
                out.active_company_id = first.id
                role = company_role(db, current_user, first.id)
        out.company_role = role
        out.can_manage_platform = is_platform_admin(current_user)
    else:
        out.company_role = current_user.role
        out.can_manage_platform = current_user.role == UserRole.admin
    return out


def _signed_in_interactively(request: Request) -> bool:
    """Whether the caller holds a session token from a real sign-in.

    get_current_user also accepts company API keys and MCP_API_TOKEN, and the MCP
    dispatcher mints its own access tokens marked "src". None of those is the
    account's owner sitting at a browser, so none may set its first password.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    try:
        claims = decode_token(token)
    except JWTError:
        return False
    return claims.get("type") == "access" and "src" not in claims


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    # An `si_` key acts as its creator inside one company; it must never be able
    # to replace the creator's password, which would outlive the key itself.
    current_user: User = Depends(get_session_user),
):
    user = db.query(User).filter(User.email == current_user.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # An account made through Google has no password to confirm; this is how it
    # sets its first one -- but only from a real signed-in session, never from an
    # API key, which would otherwise turn a scoped credential into a permanent
    # password. Everyone else proves the current one.
    if not user.has_password and not _signed_in_interactively(request):
        raise HTTPException(status_code=403, detail="Sign in to set a password for this account")
    if user.has_password:
        if not payload.current_password or not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

        if payload.current_password == payload.new_password:
            raise HTTPException(status_code=400, detail="New password must be different from current password")

    user.hashed_password = get_password_hash(payload.new_password)
    # Someone changing their password may well suspect it is known, so a session held
    # elsewhere must not keep refreshing, the same as after a reset.
    user.sessions_valid_after = _now()
    db.add(user)
    db.commit()

    response = {"detail": "Password updated successfully"}
    if _signed_in_interactively(request):
        response.update(_issue_tokens(user))
    return response


# ---------------------------------------------------------------------------
# Social sign-in (Authlib)
# ---------------------------------------------------------------------------
#
# The flow, end to end:
#   1. The browser navigates (not XHR) to /oauth/<provider>/login?next=/path.
#      Authlib stores state, nonce and the PKCE verifier in the signed session
#      cookie (SessionMiddleware, app_main.py) and 302s to the provider.
#   2. The provider sends the browser back to /oauth/<provider>/callback. Authlib
#      checks the state against the cookie (the CSRF check), swaps the code for
#      tokens, and verifies the ID token's signature, iss, aud, exp and nonce.
#   3. We resolve the user, and redirect to the SPA with a one-time code -- never
#      a JWT, which would land in browser history and proxy logs.
#   4. The SPA POSTs the code to /oauth/exchange and gets the usual Token.

_OAUTH_NEXT_SESSION_KEY = "oauth_next"
# sha256 of the one-time code, kept in the same browser's session cookie, so the
# code can only be exchanged by the browser that went through the flow. Without
# it an attacker could finish a sign-in to THEIR account, stop at the redirect,
# and send the /auth/callback?code=... link to a victim, who would then be
# working -- entering customers, bank details -- inside the attacker's account.
_OAUTH_CODE_SESSION_KEY = "oauth_code"
_OAUTH_CODE_TTL = timedelta(seconds=60)
# Anything a browser might reinterpret: control characters (stripped from URLs by
# browsers, so "/\t/evil.com" becomes "//evil.com") and backslashes (treated as
# "/" in special-scheme URLs, so "/\evil.com" is "//evil.com" too).
_UNSAFE_NEXT_CHARS = re.compile(r"[\x00-\x1f\x7f\\]")


def safe_next_path(value: object) -> str:
    """A same-origin path to land on after sign-in, or "/".

    Only a relative path that starts with exactly one "/" is accepted. "//host"
    is protocol-relative and "/\\host" is read as one by browsers -- both are
    open redirects -- and anything absolute is somebody else's site.
    """
    if not isinstance(value, str) or not value or len(value) > 2048:
        return "/"
    if not value.startswith("/") or value.startswith("//") or _UNSAFE_NEXT_CHARS.search(value):
        return "/"
    return value


def _app_redirect(path: str, **params: str) -> RedirectResponse:
    base = settings.PUBLIC_APP_BASE_URL.rstrip("/")
    query = f"?{urlencode(params)}" if params else ""
    response = RedirectResponse(f"{base}{path}{query}", status_code=302)
    # The callback URL carries the provider's code and state; neither should
    # follow the user to the next page in a Referer header.
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


def _login_error(code: str) -> RedirectResponse:
    return _app_redirect("/login", error=code)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


@router.get("/oauth/{provider}/login", include_in_schema=False)
async def oauth_login(provider: str, request: Request, next: str | None = None):
    client = auth_providers.get_client(provider)
    if client is None:
        raise HTTPException(status_code=404, detail="Not Found")

    request.session[_OAUTH_NEXT_SESSION_KEY] = safe_next_path(next)
    try:
        return await client.authorize_redirect(request, auth_providers.redirect_uri(provider))
    except Exception:
        # Discovery unreachable, misconfigured client, ... -- never a 500 page in
        # the middle of a sign-in; the login screen explains it.
        logger.exception("OAuth login redirect failed for provider %s", provider)
        return _login_error("oauth_failed")


def _userinfo_email_verified(userinfo: dict) -> bool:
    value = userinfo.get("email_verified")
    return value is True or (isinstance(value, str) and value.lower() == "true")


class _OAuthRejected(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _oauth_full_name(userinfo: dict, email: str) -> str:
    name = userinfo.get("name")
    return name.strip()[:120] if isinstance(name, str) and name.strip() else email


def _resolve_oauth_user(db: Session, provider: str, userinfo: dict) -> tuple[User, bool]:
    """Find or create the user for a verified provider identity.

    Returns (user, created). Raises _OAuthRejected with the /login error code.
    Order, as the plan has it: identity, then a verified email, then signup.
    """
    subject = str(userinfo.get("sub") or "")
    raw_email = userinfo.get("email")
    if not subject or not isinstance(raw_email, str) or not raw_email.strip():
        raise _OAuthRejected("oauth_failed")
    if not _userinfo_email_verified(userinfo):
        raise _OAuthRejected("email_not_verified")
    email = normalize_email(raw_email)

    # 1. A linked identity: the provider's stable subject, not the address.
    identity = (
        db.query(UserIdentity)
        .filter(UserIdentity.provider == provider, UserIdentity.provider_subject == subject)
        .first()
    )
    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is None:
            raise _OAuthRejected("oauth_failed")
        if not user.is_active:
            raise _OAuthRejected("account_inactive")
        return user, False

    # 2. An existing account with the same (provider-verified) address: link it.
    user = find_user_by_email(db, email)
    if user is not None:
        if not user.is_active:
            raise _OAuthRejected("account_inactive")
        already_linked = (
            db.query(UserIdentity)
            .filter(UserIdentity.user_id == user.id, UserIdentity.provider == provider)
            .first()
        )
        if already_linked is not None:
            # The account is linked to a DIFFERENT account at this provider. The
            # address has changed hands there (a deleted and recreated account,
            # a reassigned Workspace mailbox); linking a second one would hand the
            # new holder the old holder's data.
            logger.warning("OAuth %s: refusing to link a second identity to user %s", provider, user.id)
            raise _OAuthRejected("oauth_failed")
        if not user.email_verified:
            user.email_verified_at = _now()
            if settings.is_shared_hosting:
                # Whoever set this password never proved the address -- anyone
                # can register someone else's. Keeping it would let that person
                # sign in to the account its real owner is about to fill, or
                # keep a session they already started with it.
                user.hashed_password = None
                user.sessions_valid_after = _now()
                user.full_name = _oauth_full_name(userinfo, email)
        db.add(UserIdentity(user_id=user.id, provider=provider, provider_subject=subject, email=email))
        db.commit()
        return user, False

    # 3. Nobody: sign up, if this deployment lets strangers do that.
    spec = auth_providers.get_spec(provider)
    if spec is None or not spec.signup_allowed(settings):
        raise _OAuthRejected("signup_disabled")
    user = User(
        email=email,
        full_name=_oauth_full_name(userinfo, email),
        hashed_password=None,
        role=UserRole.staff,
        email_verified_at=_now(),
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(UserIdentity(user_id=user.id, provider=provider, provider_subject=subject, email=email))
    db.commit()
    db.refresh(user)
    return user, True


def _mint_login_code(db: Session, user: User) -> str:
    code = secrets.token_urlsafe(32)
    now = _now()
    # Housekeeping on the way in: expired codes are never read again.
    db.query(OAuthLoginCode).filter(OAuthLoginCode.expires_at < now).delete(synchronize_session=False)
    db.add(OAuthLoginCode(code_hash=_hash_code(code), user_id=user.id, expires_at=now + _OAUTH_CODE_TTL))
    db.commit()
    return code


def _complete_oauth(db: Session, provider: str, userinfo: dict) -> tuple[str | None, str | None]:
    """Resolve the user and mint a login code. Returns (code, None) or (None, error_code)."""
    try:
        user, created = _resolve_oauth_user(db, provider, userinfo)
    except _OAuthRejected as rejected:
        db.rollback()
        return None, rejected.code
    except IntegrityError:
        # Two callbacks for the same new person raced; the loser just retries.
        db.rollback()
        logger.warning("OAuth %s: integrity error resolving user", provider, exc_info=True)
        return None, "oauth_failed"

    properties = {
        "method": provider,
        "$set": {
            "email": user.email,
            "role": getattr(user.role, "value", user.role),
            "active_company_id": user.active_company_id,
        },
    }
    track("user_signed_up" if created else "user_logged_in", distinct_id_for(user), properties)
    return _mint_login_code(db, user), None


@router.get("/oauth/{provider}/callback", include_in_schema=False)
async def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db)):
    client = auth_providers.get_client(provider)
    spec = auth_providers.get_spec(provider)
    if client is None or spec is None:
        raise HTTPException(status_code=404, detail="Not Found")

    next_path = safe_next_path(request.session.pop(_OAUTH_NEXT_SESSION_KEY, "/"))
    try:
        # Raises on a missing or mismatched state (CSRF / replay), on the user
        # declining consent (?error=...), on a failed code exchange, and on an ID
        # token whose signature, issuer, expiry or nonce is wrong -- or whose
        # audience is not our client id, which Authlib checks only when told to.
        token = await client.authorize_access_token(request, claims_options=spec.id_token_claims(settings))
    except Exception:
        logger.warning("OAuth callback failed for provider %s", provider, exc_info=True)
        return _login_error("oauth_failed")

    # Only claims from the verified ID token are trusted -- never a bare userinfo
    # fetch, which is not bound to this sign-in by a nonce.
    userinfo = token.get("userinfo") if isinstance(token, dict) else None
    if not userinfo:
        logger.warning("OAuth callback for provider %s returned no ID token", provider)
        return _login_error("oauth_failed")

    code, error = await run_in_threadpool(_complete_oauth, db, provider, dict(userinfo))
    if error:
        return _login_error(error)
    request.session[_OAUTH_CODE_SESSION_KEY] = _hash_code(code)
    return _app_redirect("/auth/callback", code=code, next=next_path)


@router.post("/oauth/exchange", response_model=Token, include_in_schema=False)
def oauth_exchange(payload: OAuthExchangeRequest, request: Request, db: Session = Depends(get_db)):
    if _EXCHANGE_BY_IP.hit(client_ip(request)):
        raise _too_many()

    invalid = _error(400, "invalid_code", "This sign-in link is invalid or has expired.")
    code_hash = _hash_code(payload.code)
    # Same-origin POST, so the SameSite=Lax state cookie is sent with it.
    expected = request.session.pop(_OAUTH_CODE_SESSION_KEY, None)
    if not isinstance(expected, str) or not hmac.compare_digest(expected, code_hash):
        raise invalid
    now = _now()
    # Claimed with one conditional UPDATE, so two requests racing with the same
    # code cannot both see it unused: exactly one gets rowcount 1.
    result = db.execute(
        update(OAuthLoginCode)
        .where(
            OAuthLoginCode.code_hash == code_hash,
            OAuthLoginCode.used_at.is_(None),
            OAuthLoginCode.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise invalid
    user_id = db.query(OAuthLoginCode.user_id).filter(OAuthLoginCode.code_hash == code_hash).scalar()
    db.commit()

    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise invalid
    if not user.is_active:
        raise _error(403, "account_inactive", "This account has been deactivated.")
    return _issue_tokens(user)
