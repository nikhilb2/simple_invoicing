import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user, require_roles
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.global_settings import GlobalSettings
from src.models.user import User, UserRole
from src.schemas.company import (
    CompanyCreationCapOut,
    CompanyListItem,
    CompanyProfileOut,
    CompanyProfileUpdate,
    CompanySelectOut,
)

router = APIRouter()

LOGO_UPLOAD_DIR = Path("uploads/logos")
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_LOGO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def _get_logo_dir() -> Path:
    LOGO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return LOGO_UPLOAD_DIR


def _get_max_companies(db: Session) -> int:
    settings_row = db.query(GlobalSettings).filter(GlobalSettings.id == 1).first()
    return settings_row.max_companies if settings_row else 1


def _get_company_creation_capability(db: Session) -> CompanyCreationCapOut:
    current_companies = db.query(func.count(CompanyProfile.id)).scalar() or 0
    max_companies = _get_max_companies(db)
    return CompanyCreationCapOut(
        max_companies=max_companies,
        current_companies=current_companies,
        can_create_company=current_companies < max_companies,
    )


def _create_company_profile(db: Session, payload: CompanyProfileUpdate) -> CompanyProfile:
    profile = CompanyProfile(
        name=payload.name.strip(),
        address=payload.address.strip(),
        gst=payload.gst.strip().upper(),
        phone_number=payload.phone_number.strip(),
        currency_code=payload.currency_code.strip().upper() if payload.currency_code else "USD",
        email=payload.email.strip() if payload.email else None,
        website=payload.website.strip() if payload.website else None,
        bank_name=payload.bank_name.strip() if payload.bank_name else None,
        branch_name=payload.branch_name.strip() if payload.branch_name else None,
        account_name=payload.account_name.strip() if payload.account_name else None,
        account_number=payload.account_number.strip() if payload.account_number else None,
        ifsc_code=payload.ifsc_code.strip().upper() if payload.ifsc_code else None,
        terms_and_conditions=[t.model_dump() for t in (payload.terms_and_conditions or [])],
        additional_company_info=payload.additional_company_info,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _create_blank_company_profile(db: Session) -> CompanyProfile:
    profile = CompanyProfile(
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
        terms_and_conditions=[],
        additional_company_info=None,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _set_active_company(db: Session, user: User, company_id: int) -> None:
    user.active_company_id = company_id
    db.commit()
    db.refresh(user)


def _apply_branding_fields(profile: CompanyProfile, payload: CompanyProfileUpdate) -> None:
    profile.name = payload.name.strip()
    profile.address = payload.address.strip()
    profile.gst = payload.gst.strip().upper()
    profile.phone_number = payload.phone_number.strip()
    profile.currency_code = payload.currency_code.strip().upper() if payload.currency_code else "USD"
    profile.email = payload.email.strip() if payload.email else None
    profile.website = payload.website.strip() if payload.website else None
    profile.bank_name = payload.bank_name.strip() if payload.bank_name else None
    profile.branch_name = payload.branch_name.strip() if payload.branch_name else None
    profile.account_name = payload.account_name.strip() if payload.account_name else None
    profile.account_number = payload.account_number.strip() if payload.account_number else None
    profile.ifsc_code = payload.ifsc_code.strip().upper() if payload.ifsc_code else None
    profile.terms_and_conditions = [t.model_dump() for t in (payload.terms_and_conditions or [])]
    profile.additional_company_info = payload.additional_company_info


@router.get("/companies", response_model=list[CompanyListItem])
def list_companies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    companies = db.query(CompanyProfile).order_by(CompanyProfile.name.asc(), CompanyProfile.id.asc()).all()
    return [
        CompanyListItem(
            id=company.id,
            name=company.name,
            gst=company.gst or "",
            currency_code=company.currency_code,
            is_active=company.id == current_user.active_company_id,
        )
        for company in companies
    ]


@router.post("/companies", response_model=CompanyProfileOut)
def create_company_profile(
    payload: CompanyProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    cap = _get_company_creation_capability(db)
    if not cap.can_create_company:
        raise HTTPException(
            status_code=403,
            detail=(
                "Company creation limit reached. "
                "Update global_settings.max_companies directly in PostgreSQL to allow more companies."
            ),
        )

    profile = _create_company_profile(db, payload)
    if current_user.active_company_id is None:
        _set_active_company(db, current_user, profile.id)
    return profile


@router.get("/companies/capability", response_model=CompanyCreationCapOut)
def get_company_creation_capability(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_company_creation_capability(db)


@router.post("/select/{company_id}", response_model=CompanySelectOut)
def select_active_company(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company = db.query(CompanyProfile).filter(CompanyProfile.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    _set_active_company(db, current_user, company.id)
    return CompanySelectOut(active_company_id=company.id)


@router.get("", response_model=CompanyProfileOut, include_in_schema=False)
@router.get("/", response_model=CompanyProfileOut)
def get_company_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return get_active_company(db=db, current_user=current_user, requested_company_id=None)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        profile = _create_blank_company_profile(db)
        _set_active_company(db, current_user, profile.id)
        return profile


@router.put("", response_model=CompanyProfileOut, include_in_schema=False)
@router.put("/", response_model=CompanyProfileOut)
def upsert_company_profile(
    payload: CompanyProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    try:
        profile = get_active_company(db=db, current_user=current_user, requested_company_id=None)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        profile = _create_blank_company_profile(db)
        _set_active_company(db, current_user, profile.id)
    _apply_branding_fields(profile, payload)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Logo endpoints
# ---------------------------------------------------------------------------

@router.post("/logo", response_model=CompanyProfileOut)
async def upload_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    """Upload or replace company logo."""
    profile = get_active_company(db=db, current_user=current_user, requested_company_id=None)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_LOGO_EXTENSIONS)}",
        )

    contents = await file.read()
    if len(contents) > MAX_LOGO_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {MAX_LOGO_SIZE_BYTES // 1024 // 1024} MB",
        )

    # Remove old logo if exists
    if profile.logo_path:
        old_path = Path(profile.logo_path)
        if old_path.exists():
            old_path.unlink()

    logo_dir = _get_logo_dir()
    logo_filename = f"company_{profile.id}{ext}"
    logo_path = logo_dir / logo_filename

    with open(logo_path, "wb") as f:
        f.write(contents)

    profile.logo_path = str(logo_path.resolve())
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/logo")
def get_logo(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve the company logo file."""
    profile = get_active_company(db=db, current_user=current_user, requested_company_id=None)

    if not profile.logo_path:
        raise HTTPException(status_code=404, detail="No logo uploaded")

    logo_path = Path(profile.logo_path)
    if not logo_path.exists():
        raise HTTPException(status_code=404, detail="Logo file not found on disk")

    return FileResponse(
        path=str(logo_path),
        media_type=f"image/{logo_path.suffix.lower().lstrip('.')}",
    )


@router.delete("/logo", response_model=CompanyProfileOut)
def delete_logo(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    """Remove the company logo."""
    profile = get_active_company(db=db, current_user=current_user, requested_company_id=None)

    if profile.logo_path:
        logo_path = Path(profile.logo_path)
        if logo_path.exists():
            logo_path.unlink()
        profile.logo_path = None
        db.commit()
        db.refresh(profile)

    return profile
