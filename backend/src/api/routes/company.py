from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from pydantic import BaseModel

from src.api.deps import get_active_company, get_current_user, require_roles
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.company_term import CompanyTerm
from src.models.global_settings import GlobalSettings
from src.models.user import User, UserRole
from src.schemas.company import (
    CompanyCreationCapOut,
    CompanyListItem,
    CompanyProfileOut,
    CompanyProfileOutWithLogo,
    CompanyProfileUpdate,
    CompanySelectOut,
    CompanyTermCreate,
    CompanyTermOut,
    CompanyTermUpdate,
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
        show_sku_on_pdf=payload.show_sku_on_pdf,
        eway_enabled=payload.eway_enabled,
        eway_local_threshold=payload.eway_local_threshold,
        eway_interstate_threshold=payload.eway_interstate_threshold,
        eway_always_show_button=payload.eway_always_show_button,
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


def _serial_company_terms(company_id: int, db: Session) -> None:
    """Re-sequence serial numbers for a company's terms after any mutation."""
    terms = (
        db.query(CompanyTerm)
        .filter(CompanyTerm.company_id == company_id)
        .order_by(CompanyTerm.serial_number, CompanyTerm.id)
        .all()
    )
    for idx, term in enumerate(terms, start=1):
        if term.serial_number != idx:
            term.serial_number = idx
    db.commit()


def _company_to_out(company: CompanyProfile) -> CompanyProfileOut:
    """Convert company to output schema with terms eagerly loaded."""
    return CompanyProfileOut(
        id=company.id,
        name=company.name,
        address=company.address,
        gst=company.gst or "",
        phone_number=company.phone_number or "",
        currency_code=company.currency_code,
        email=company.email,
        website=company.website,
        bank_name=company.bank_name,
        branch_name=company.branch_name,
        account_name=company.account_name,
        account_number=company.account_number,
        ifsc_code=company.ifsc_code,
        logo_data=company.logo_data,
        logo_mime_type=company.logo_mime_type,
        additional_company_info=company.additional_company_info,
        eway_enabled=company.eway_enabled,
        eway_local_threshold=company.eway_local_threshold,
        eway_interstate_threshold=company.eway_interstate_threshold,
        eway_always_show_button=company.eway_always_show_button,
        terms=[
            CompanyTermOut(
                id=t.id,
                company_id=t.company_id,
                serial_number=t.serial_number,
                content=t.content,
            )
            for t in company.terms
        ],
    )


# ---------------------------------------------------------------------------
# Company listing & selection
# ---------------------------------------------------------------------------

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
    return _company_to_out(profile)


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
        company = get_active_company(db=db, current_user=current_user, requested_company_id=None)
        return _company_to_out(company)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        profile = _create_blank_company_profile(db)
        _set_active_company(db, current_user, profile.id)
        return _company_to_out(profile)


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
    profile.additional_company_info = payload.additional_company_info
    profile.show_sku_on_pdf = payload.show_sku_on_pdf
    profile.eway_enabled = payload.eway_enabled
    profile.eway_local_threshold = payload.eway_local_threshold
    profile.eway_interstate_threshold = payload.eway_interstate_threshold
    profile.eway_always_show_button = payload.eway_always_show_button
    db.commit()
    db.refresh(profile)
    return _company_to_out(profile)


# ---------------------------------------------------------------------------
# Logo upload / remove
# ---------------------------------------------------------------------------

try:
    from PIL import Image, UnidentifiedImageError
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

import base64
import io


class LogoUpload(BaseModel):
    data: str  # base64-encoded image data (without data URI prefix)
    mime_type: str  # e.g. "image/png", "image/jpeg"


_MAX_LOGO_WIDTH = 400
_MAX_LOGO_HEIGHT = 150
_LOGO_QUALITY = 85


def _optimize_logo_image(data: str, mime_type: str) -> tuple[str, str]:
    """Resize and compress a base64-encoded logo image.

    Returns (optimized_base64_data, output_mime_type).
    Always outputs JPEG for best compression.
    """
    if not _HAS_PIL:
        return data, mime_type

    try:
        raw_bytes = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw_bytes))

        # Convert RGBA/P to RGB for JPEG output
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize down if larger than max dimensions
        original_width, original_height = img.size
        if original_width > _MAX_LOGO_WIDTH or original_height > _MAX_LOGO_HEIGHT:
            ratio = min(_MAX_LOGO_WIDTH / original_width, _MAX_LOGO_HEIGHT / original_height)
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_LOGO_QUALITY, optimize=True)
        optimized = base64.b64encode(buf.getvalue()).decode()
        return optimized, "image/jpeg"
    except (UnidentifiedImageError, Exception):
        # If anything goes wrong, fall through to store as-is
        return data, mime_type


@router.put("/logo", response_model=CompanyProfileOut)
def upload_logo(
    payload: LogoUpload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    profile = get_active_company(db=db, current_user=current_user, requested_company_id=None)

    # Decode to check file size before optimization
    try:
        raw_bytes = base64.b64decode(payload.data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 data.")

    file_size_kb = len(raw_bytes) / 1024
    if file_size_kb > 100:
        raise HTTPException(
            status_code=400,
            detail="Logo size cannot exceed 100 KB.",
        )

    # Optimize (resize + compress)
    optimized_data, optimized_mime = _optimize_logo_image(payload.data, payload.mime_type)

    profile.logo_data = optimized_data
    profile.logo_mime_type = optimized_mime
    db.commit()
    db.refresh(profile)
    return _company_to_out(profile)


@router.delete("/logo", response_model=CompanyProfileOut)
def remove_logo(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    profile = get_active_company(db=db, current_user=current_user, requested_company_id=None)
    profile.logo_data = None
    profile.logo_mime_type = None
    db.commit()
    db.refresh(profile)
    return _company_to_out(profile)


# ---------------------------------------------------------------------------
# Terms & Conditions CRUD
# ---------------------------------------------------------------------------

@router.get("/terms", response_model=list[CompanyTermOut])
def list_terms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company = get_active_company(db=db, current_user=current_user, requested_company_id=None)
    terms = (
        db.query(CompanyTerm)
        .filter(CompanyTerm.company_id == company.id)
        .order_by(CompanyTerm.serial_number)
        .all()
    )
    return [
        CompanyTermOut(id=t.id, company_id=t.company_id, serial_number=t.serial_number, content=t.content)
        for t in terms
    ]


@router.post("/terms", response_model=CompanyTermOut)
def create_term(
    payload: CompanyTermCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    company = get_active_company(db=db, current_user=current_user, requested_company_id=None)
    max_serial = (
        db.query(func.coalesce(func.max(CompanyTerm.serial_number), 0))
        .filter(CompanyTerm.company_id == company.id)
        .scalar()
    )
    term = CompanyTerm(
        company_id=company.id,
        serial_number=max_serial + 1,
        content=payload.content.strip(),
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return CompanyTermOut(id=term.id, company_id=term.company_id, serial_number=term.serial_number, content=term.content)


@router.put("/terms/{term_id}", response_model=CompanyTermOut)
def update_term(
    term_id: int,
    payload: CompanyTermUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    company = get_active_company(db=db, current_user=current_user, requested_company_id=None)
    term = (
        db.query(CompanyTerm)
        .filter(CompanyTerm.id == term_id, CompanyTerm.company_id == company.id)
        .first()
    )
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    term.content = payload.content.strip()
    db.commit()
    db.refresh(term)
    return CompanyTermOut(id=term.id, company_id=term.company_id, serial_number=term.serial_number, content=term.content)


@router.delete("/terms/{term_id}", response_model=list[CompanyTermOut])
def delete_term(
    term_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    company = get_active_company(db=db, current_user=current_user, requested_company_id=None)
    term = (
        db.query(CompanyTerm)
        .filter(CompanyTerm.id == term_id, CompanyTerm.company_id == company.id)
        .first()
    )
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    db.delete(term)
    db.commit()
    # Re-sequence serial numbers
    _serial_company_terms(company.id, db)
    # Return updated list
    terms = (
        db.query(CompanyTerm)
        .filter(CompanyTerm.company_id == company.id)
        .order_by(CompanyTerm.serial_number)
        .all()
    )
    return [
        CompanyTermOut(id=t.id, company_id=t.company_id, serial_number=t.serial_number, content=t.content)
        for t in terms
    ]
