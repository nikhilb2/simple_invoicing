from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.core.security import decode_token
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
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
