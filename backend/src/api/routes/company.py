from fastapi import APIRouter, Depends, HTTPException
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
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _set_active_company(db: Session, user: User, company_id: int) -> None:
    user.active_company_id = company_id
    db.commit()
    db.refresh(user)


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
    db.commit()
    db.refresh(profile)
    return profile