import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user, require_roles
from src.core.security import decrypt_value, encrypt_value
from src.db.session import get_db
from src.models.api_key import ApiKey
from src.models.company import CompanyProfile
from src.models.user import User, UserRole
from src.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyResponse

router = APIRouter()

_KEY_PREFIX = "si_"
_KEY_BYTES = 32  # 32 random bytes → 64 hex chars


def _generate_raw_key() -> str:
    return _KEY_PREFIX + secrets.token_hex(_KEY_BYTES)


@router.post("", response_model=ApiKeyCreateResponse, include_in_schema=False)
@router.post("/", response_model=ApiKeyCreateResponse, status_code=201)
def create_api_key(
    payload: ApiKeyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
    company: CompanyProfile = Depends(get_active_company),
):
    raw_key = _generate_raw_key()
    # key_prefix: "si_" + first 9 chars of hex part, then "..."
    key_prefix = raw_key[: len(_KEY_PREFIX) + 9]

    api_key = ApiKey(
        company_id=company.id,
        created_by_user_id=current_user.id,
        name=payload.name.strip(),
        key_prefix=key_prefix,
        key_encrypted=encrypt_value(raw_key),
        expires_at=payload.expires_at,
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        expires_at=api_key.expires_at,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        created_by_user_id=api_key.created_by_user_id,
        raw_key=raw_key,
    )


@router.get("", response_model=list[ApiKeyResponse], include_in_schema=False)
@router.get("/", response_model=list[ApiKeyResponse])
def list_api_keys(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    company: CompanyProfile = Depends(get_active_company),
):
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.company_id == company.id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return keys


@router.delete("/{key_id}", response_model=dict)
def delete_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    company: CompanyProfile = Depends(get_active_company),
):
    api_key = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.company_id == company.id)
        .first()
    )
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(api_key)
    db.commit()
    return {"detail": "API key deleted"}
