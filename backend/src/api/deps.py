from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.security import decode_token
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _authenticate_api_key(token: str, db: Session) -> User | None:
    """Check token against company-scoped API keys stored in DB."""
    from datetime import timezone
    from src.core.security import decrypt_value
    from src.models.api_key import ApiKey

    if not token.startswith("si_"):
        return None

    # key_prefix is the first 12 chars of the raw key
    key_prefix = token[:12]
    candidates = (
        db.query(ApiKey)
        .filter(
            ApiKey.key_prefix == key_prefix,
            ApiKey.is_active.is_(True),
            ApiKey.expires_at > __import__('datetime').datetime.now(timezone.utc),
        )
        .all()
    )
    for candidate in candidates:
        try:
            if decrypt_value(candidate.key_encrypted) == token:
                # Return the admin user for this company
                admin_user = (
                    db.query(User)
                    .filter(User.role == UserRole.admin)
                    .first()
                )
                if admin_user:
                    # Bind the company context via active_company_id
                    admin_user.active_company_id = candidate.company_id
                    return admin_user
        except Exception:
            continue
    return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    # Check DB-managed API keys first (company-scoped, encrypted, with expiry)
    api_key_user = _authenticate_api_key(token, db)
    if api_key_user is not None:
        return api_key_user

    # Legacy: static MCP API token via env var
    if settings.MCP_API_TOKEN and token == settings.MCP_API_TOKEN:
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
    return user


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


def get_active_company(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    requested_company_id: int | None = Depends(get_requested_company_id),
) -> CompanyProfile:
    user_state = inspect(current_user)

    def _persist_active_company(company_id: int) -> None:
        if user_state.persistent:
            current_user.active_company_id = company_id
            db.commit()
            db.refresh(current_user)

    if requested_company_id is not None:
        requested_company = db.query(CompanyProfile).filter(CompanyProfile.id == requested_company_id).first()
        if not requested_company:
            raise HTTPException(status_code=404, detail="Company not found")
        if current_user.active_company_id != requested_company.id:
            _persist_active_company(requested_company.id)
        return requested_company

    if current_user.active_company_id is not None:
        active_company = db.query(CompanyProfile).filter(CompanyProfile.id == current_user.active_company_id).first()
        if active_company:
            return active_company

    fallback_company = db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    if fallback_company is None:
        fallback_company = CompanyProfile(
            name="",
            address="",
            gst="",
            phone_number="",
            currency_code="USD",
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
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return checker
