from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.security import decode_token, session_revoked
from src.db.session import get_db
from src.db.tenant_context import set_tenant_context
from src.models.company import CompanyProfile
from src.models.user import User, UserRole
from src.services.company_access import (
    can_access_company,
    company_role,
    first_accessible_company,
    is_platform_admin,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# The company an `si_` API key is bound to, held on the User instance for the
# rest of this request only. A plain instance attribute, not a mapped column:
# writing active_company_id here instead would leave the user's real selection
# dirty in the session, and the next commit in the request would save it.
API_KEY_COMPANY_ATTR = "_api_key_company_id"


def _authenticate_api_key(token: str, db: Session) -> User | None:
    """Check token against company-scoped API keys stored in DB."""
    from datetime import datetime, timezone
    from src.core.security import decrypt_value
    from src.models.api_key import ApiKey

    if not token.startswith("si_"):
        return None

    # key_prefix is the first 12 chars of the raw key
    key_prefix = token[:12]
    # No company is known yet, so in shared hosting the api_keys policy admits
    # only the keys carrying this prefix -- which the caller already holds.
    set_tenant_context(db, api_key_prefix=key_prefix)
    try:
        candidates = (
            db.query(ApiKey)
            .filter(
                ApiKey.key_prefix == key_prefix,
                ApiKey.is_active.is_(True),
                ApiKey.expires_at > datetime.now(timezone.utc),
            )
            .all()
        )
    finally:
        set_tenant_context(db, api_key_prefix=None)
    for candidate in candidates:
        try:
            matches = decrypt_value(candidate.key_encrypted) == token
        except Exception:
            continue
        if not matches:
            continue

        # The key acts as the person who created it, and only while that person
        # can still reach the key's company.
        user = None
        if candidate.created_by_user_id is not None:
            user = db.query(User).filter(User.id == candidate.created_by_user_id).first()
        elif not settings.is_shared_hosting:
            # A key with no recorded creator: single tenant keeps the old
            # "first admin" behaviour. Shared hosting has no safe owner to pick.
            user = db.query(User).filter(User.role == UserRole.admin).first()
        if user is None or user.is_active is False:
            return None
        if not can_access_company(db, user, candidate.company_id):
            return None
        setattr(user, API_KEY_COMPANY_ATTR, candidate.company_id)
        return user
    return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    # Check DB-managed API keys first (company-scoped, encrypted, with expiry)
    api_key_user = _authenticate_api_key(token, db)
    if api_key_user is not None:
        return api_key_user

    # Legacy: static MCP API token via env var. It resolves to "the first admin"
    # with access to everything, which only makes sense on a single-tenant DB.
    if settings.MCP_API_TOKEN and token == settings.MCP_API_TOKEN and not settings.is_shared_hosting:
        admin_user = db.query(User).filter(User.role == UserRole.admin).first()
        if admin_user:
            return admin_user
        any_user = db.query(User).first()
        if any_user:
            return any_user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No users found for MCP token auth",
        )

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = decode_token(token)
        email: str | None = payload.get("sub")
        token_type = payload.get("type")
        if email is None or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise credentials_exception
    # A deactivated account, or a token from before a password reset, is done
    # now -- not when the access token happens to expire.
    if user.is_active is False or session_revoked(user.sessions_valid_after, payload):
        raise credentials_exception
    return user


def get_session_user(current_user: User = Depends(get_current_user)) -> User:
    """The signed-in person, for account-level actions an `si_` key must not take.

    A key is pinned to one company inside get_active_company, but a route that
    only asks for the user would otherwise act as the key's creator everywhere:
    approve an OAuth grant for another of their companies, list or switch
    companies, create new ones. In shared hosting those need a real session.
    """
    if settings.is_shared_hosting and getattr(current_user, API_KEY_COMPANY_ATTR, None) is not None:
        raise HTTPException(status_code=403, detail="API keys cannot be used for this action")
    return current_user


def get_requested_company_id(x_company_id: str | None = Header(default=None, alias="X-Company-Id")) -> int | None:
    if x_company_id is None:
        return None
    try:
        company_id = int(x_company_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-Company-Id header") from exc
    if company_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid X-Company-Id header")
    return company_id


def company_required_error() -> HTTPException:
    """409 for a shared-hosting user who belongs to no company yet.

    The frontend reads the code and sends them to company setup.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "company_required",
            "message": "Create a company to get started.",
        },
    )


def _company_forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="You do not have access to this company")


def act_for_company(db: Session, company: CompanyProfile, user: User | None = None) -> CompanyProfile:
    """Make ``company`` the tenant for the rest of this session, and return it.

    Every row a shared-hosting query sees is filtered by row-level security to
    this company (src/db/tenant_context.py), from this transaction on and in
    every later one -- a handler's mid-request commit does not lose it.
    """
    set_tenant_context(db, company_id=company.id, user_id=getattr(user, "id", None))
    return company


def get_active_company(
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    requested_company_id: int | None = Depends(get_requested_company_id),
) -> CompanyProfile:
    company = _resolve_active_company(request, db, current_user, requested_company_id)
    return act_for_company(db, company, current_user)


def _resolve_active_company(
    request: Request | None,
    db: Session,
    current_user: User,
    requested_company_id: int | None,
) -> CompanyProfile:
    shared = settings.is_shared_hosting
    user_state = inspect(current_user)
    # An MCP tool call addresses a company via X-Company-Id for the duration of that call
    # only. Without this guard a read-only tool would commit a new active_company_id and
    # silently change which company the human sees in the web UI on their next page load.
    ephemeral = request is not None and "X-MCP-Tool" in request.headers

    # An `si_` API key is pinned to the company it was issued for. It never
    # changes the creator's own selection, and it cannot be pointed elsewhere.
    api_key_company_id = getattr(current_user, API_KEY_COMPANY_ATTR, None)
    if api_key_company_id is not None:
        if requested_company_id is not None and requested_company_id != api_key_company_id:
            raise _company_forbidden()
        company = db.query(CompanyProfile).filter(CompanyProfile.id == api_key_company_id).first()
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found")
        return company

    def _persist_active_company(company_id: int) -> None:
        if user_state.persistent and not ephemeral:
            current_user.active_company_id = company_id
            db.commit()
            db.refresh(current_user)

    if requested_company_id is not None:
        # Shared hosting answers 403 before looking the id up, so a missing
        # company and someone else's company are indistinguishable.
        if shared and not can_access_company(db, current_user, requested_company_id):
            raise _company_forbidden()
        requested_company = db.query(CompanyProfile).filter(CompanyProfile.id == requested_company_id).first()
        if not requested_company:
            raise HTTPException(status_code=404, detail="Company not found")
        if current_user.active_company_id != requested_company.id:
            _persist_active_company(requested_company.id)
        return requested_company

    if current_user.active_company_id is not None and (
        not shared or can_access_company(db, current_user, current_user.active_company_id)
    ):
        active_company = db.query(CompanyProfile).filter(CompanyProfile.id == current_user.active_company_id).first()
        if active_company:
            return active_company

    if shared:
        # Never another tenant's company, and never a blank one conjured up on
        # the user's behalf: no membership means they must create a company.
        fallback_company = first_accessible_company(db, current_user)
        if fallback_company is None:
            raise company_required_error()
        _persist_active_company(fallback_company.id)
        return fallback_company

    fallback_company = db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    if fallback_company is None:
        fallback_company = CompanyProfile(
            name="",
            address="",
            gst="",
            phone_number="",
            currency_code="INR",
            email="",
            website="",
            bank_name="",
            branch_name="",
            account_name="",
            account_number="",
            ifsc_code="",
        )
        db.add(fallback_company)
        db.commit()
        db.refresh(fallback_company)

    _persist_active_company(fallback_company.id)
    return fallback_company


def require_roles(*roles: UserRole):
    """Check the user's global role. For deployment-wide checks only.

    Anything that acts inside a company wants require_company_role, which reads
    the membership role in shared hosting.
    """
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return checker


def require_company_role(*roles: UserRole):
    """Require one of ``roles`` inside the active company.

    Single tenant: exactly require_roles -- the global role, nothing else
    resolved. Shared hosting: the user's membership role in the company this
    request acts on (X-Company-Id, else the selected one), so being an admin of
    your own company grants nothing in anyone else's.
    """
    def checker(
        request: Request = None,  # type: ignore[assignment]
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        requested_company_id: int | None = Depends(get_requested_company_id),
    ):
        if not settings.is_shared_hosting:
            if current_user.role not in roles:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return current_user

        company = get_active_company(
            request=request,
            db=db,
            current_user=current_user,
            requested_company_id=requested_company_id,
        )
        if company_role(db, current_user, company.id) not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return checker


def require_platform_admin(*roles: UserRole):
    """Guard a surface that spans every company: backups, SMTP, users, sync-all.

    Single tenant: the deployment is one customer's, so ``roles`` (the global
    role check each route already had) still decides. Shared hosting: only the
    operators listed in PLATFORM_ADMIN_EMAILS, whatever their role -- a tenant's
    admin administers their company, not the platform.
    """
    def checker(current_user: User = Depends(get_current_user)):
        if settings.is_shared_hosting:
            if not is_platform_admin(current_user):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return current_user
        if roles and current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return checker
