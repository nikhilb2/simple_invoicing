from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, inspect
from sqlalchemy.orm import Session

from pydantic import BaseModel

from src.api.deps import (
    API_KEY_COMPANY_ATTR,
    act_for_company,
    company_required_error,
    get_active_company,
    get_current_user,
    get_requested_company_id,
    get_session_user,
    require_company_role,
)
from src.api.routes.financial_years import _seed_series_for_fy
from src.core.analytics import distinct_id_for, set_person_properties, track
from src.core.config import settings
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.company_term import CompanyTerm
from src.models.financial_year import FinancialYear
from src.models.global_settings import GlobalSettings
from src.models.user import User, UserRole
from src.services.company_access import (
    accessible_company_ids,
    add_membership,
    admin_company_count,
    can_access_company,
)
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

GSTIN_REQUIRED_MESSAGE = "Enter your GSTIN, the 15-character number on your GST registration."


def _get_max_companies(db: Session) -> int:
    settings_row = db.query(GlobalSettings).filter(GlobalSettings.id == 1).first()
    return settings_row.max_companies if settings_row else 1


def _get_company_creation_capability(db: Session, user: User) -> CompanyCreationCapOut:
    if settings.is_shared_hosting:
        # Per person, not per database: counting every tenant's companies would
        # let strangers use up each other's allowance.
        current_companies = admin_company_count(db, user)
        max_companies = settings.MAX_COMPANIES_PER_USER
    else:
        current_companies = db.query(func.count(CompanyProfile.id)).scalar() or 0
        max_companies = _get_max_companies(db)
    return CompanyCreationCapOut(
        max_companies=max_companies,
        current_companies=current_companies,
        can_create_company=current_companies < max_companies,
    )


def _require_gstin() -> None:
    raise HTTPException(
        status_code=422,
        detail={"message": GSTIN_REQUIRED_MESSAGE, "errors": [{"field": "gst", "message": GSTIN_REQUIRED_MESSAGE}]},
    )


def _create_company_profile(db: Session, payload: CompanyProfileUpdate) -> CompanyProfile:
    profile = CompanyProfile(
        name=payload.name.strip(),
        address=payload.address.strip(),
        gst=payload.gst.strip().upper(),
        phone_number=payload.phone_number.strip(),
        currency_code=payload.currency_code.strip().upper() if payload.currency_code else "INR",
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
        show_pay_qr_on_invoice=payload.show_pay_qr_on_invoice,
        show_upi_pay_button=payload.show_upi_pay_button,
    )
    db.add(profile)
    db.flush()
    return profile


def _current_indian_fy_bounds(today: date) -> tuple[str, date, date]:
    """The April-to-March financial year containing ``today``, e.g. "2026-27"."""
    start_year = today.year if today.month >= 4 else today.year - 1
    label = f"{start_year}-{str(start_year + 1)[-2:]}"
    return label, date(start_year, 4, 1), date(start_year + 1, 3, 31)


def _seed_current_financial_year(db: Session, company: CompanyProfile) -> FinancialYear:
    """Give a brand-new company an active FY and its numbering series.

    Without them its first invoice would fall back to the series-less numbering;
    with them it starts at INV-<year>-001 like any configured company.
    """
    label, start_date, end_date = _current_indian_fy_bounds(date.today())
    fy = FinancialYear(
        company_id=company.id,
        label=label,
        start_date=start_date,
        end_date=end_date,
        is_active=False,
    )
    db.add(fy)
    db.flush()
    # Seeded before activating: with no active FY yet the series get the defaults.
    _seed_series_for_fy(db, fy.id, company.id)
    fy.is_active = True
    db.flush()
    return fy


def _create_blank_company_profile(db: Session) -> CompanyProfile:
    profile = CompanyProfile(
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
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _set_active_company(db: Session, user: User, company_id: int) -> None:
    user.active_company_id = company_id
    db.commit()
    if inspect(user).persistent:
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
        show_sku_on_pdf=company.show_sku_on_pdf,
        eway_enabled=company.eway_enabled,
        eway_local_threshold=company.eway_local_threshold,
        eway_interstate_threshold=company.eway_interstate_threshold,
        eway_always_show_button=company.eway_always_show_button,
        show_pay_qr_on_invoice=company.show_pay_qr_on_invoice,
        show_upi_pay_button=company.show_upi_pay_button,
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
    query = db.query(CompanyProfile)
    allowed_ids = accessible_company_ids(db, current_user)
    if allowed_ids is not None:
        # An si_ key sees only the company it was issued for.
        pinned_id = getattr(current_user, API_KEY_COMPANY_ATTR, None)
        if pinned_id is not None:
            allowed_ids = allowed_ids & {pinned_id}
        query = query.filter(CompanyProfile.id.in_(allowed_ids))
    companies = query.order_by(CompanyProfile.name.asc(), CompanyProfile.id.asc()).all()
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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_session_user),
):
    shared = settings.is_shared_hosting
    if shared:
        # Anyone who has proven their address may start a company of their own;
        # the global role means nothing here, since the company does not exist yet.
        if current_user.email_verified_at is None or current_user.is_active is False:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    elif current_user.role not in (UserRole.admin, UserRole.manager):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if not payload.gst:
        _require_gstin()

    cap = _get_company_creation_capability(db, current_user)
    if not cap.can_create_company:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Company creation limit reached. You can create up to {cap.max_companies} companies."
                if shared
                else (
                    "Company creation limit reached. "
                    "Update global_settings.max_companies directly in PostgreSQL to allow more companies."
                )
            ),
        )

    # One transaction: a company without its admin membership would be
    # unreachable in shared hosting, so the two are created together or not at all.
    profile = _create_company_profile(db, payload)
    # The rows seeded below (and the terms read back) belong to the new company,
    # so that is the tenant row-level security must see from here on.
    act_for_company(db, profile, current_user)
    if inspect(current_user).persistent:
        add_membership(db, current_user, profile, UserRole.admin)
    if shared:
        _seed_current_financial_year(db, profile)
    db.commit()
    db.refresh(profile)

    # Tool calls use the new company only for this request. Browser creation keeps
    # its existing rule: switch in shared hosting, or fill an empty single-tenant selection.
    if "X-MCP-Tool" not in request.headers and (shared or current_user.active_company_id is None):
        _set_active_company(db, current_user, profile.id)

    track(
        "company_created",
        distinct_id_for(current_user),
        {
            "company_id": profile.id,
            "deployment_mode": settings.DEPLOYMENT_MODE,
            "has_gst": bool(profile.gst),
            "currency_code": profile.currency_code,
        },
    )
    return _company_to_out(profile)


@router.get("/companies/capability", response_model=CompanyCreationCapOut)
def get_company_creation_capability(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_company_creation_capability(db, current_user)


@router.post("/select/{company_id}", response_model=CompanySelectOut)
def select_active_company(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_session_user),
):
    if not can_access_company(db, current_user, company_id):
        raise HTTPException(status_code=403, detail="You do not have access to this company")
    company = db.query(CompanyProfile).filter(CompanyProfile.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    _set_active_company(db, current_user, company.id)

    # A person property, not an event: which company someone is looking at is a
    # dimension to break other events down by. Login sets it too; this keeps it
    # true for an operator who switches companies without signing out again.
    set_person_properties(
        distinct_id_for(current_user),
        {"active_company_id": company.id},
    )
    return CompanySelectOut(active_company_id=company.id)


@router.get("", response_model=CompanyProfileOut, include_in_schema=False)
@router.get("/", response_model=CompanyProfileOut)
def get_company_profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    requested_company_id: int | None = Depends(get_requested_company_id),
):
    # Single tenant has always ignored X-Company-Id here, and a stale header
    # must not end in the blank-company fallback below. Shared hosting honours
    # it so an MCP grant bound to one company reads that company's profile.
    if not settings.is_shared_hosting:
        requested_company_id = None
    try:
        company = get_active_company(
            request=request,
            db=db,
            current_user=current_user,
            requested_company_id=requested_company_id,
        )
        return _company_to_out(company)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        # Shared hosting never conjures a company up: the user creates one.
        if settings.is_shared_hosting:
            raise company_required_error() from exc
        profile = _create_blank_company_profile(db)
        _set_active_company(db, current_user, profile.id)
        return _company_to_out(profile)


@router.put("", response_model=CompanyProfileOut, include_in_schema=False)
@router.put("/", response_model=CompanyProfileOut)
def upsert_company_profile(
    payload: CompanyProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_company_role(UserRole.admin, UserRole.manager)),
    profile: CompanyProfile = Depends(get_active_company),
):

    # Read before the assignments below overwrite it. A profile with no name is
    # one nobody has filled in yet, so this save is the end of onboarding rather
    # than an established company correcting its address -- the same split the
    # browser event drew with `is_initial_setup`.
    is_initial_setup = not (profile.name or "").strip()

    # A company set up before GSTIN became mandatory can still save without one, so
    # nobody is locked out of their settings. Anything else needs it, and once on
    # record it cannot be blanked.
    set_up_without_gstin = bool(
        (profile.name or "").strip() and (profile.address or "").strip() and not (profile.gst or "").strip()
    )
    if not payload.gst and not set_up_without_gstin:
        _require_gstin()

    profile.name = payload.name.strip()
    profile.address = payload.address.strip()
    profile.gst = payload.gst.strip().upper()
    profile.phone_number = payload.phone_number.strip()
    profile.currency_code = payload.currency_code.strip().upper() if payload.currency_code else "INR"
    profile.email = payload.email.strip() if payload.email else None
    profile.website = payload.website.strip() if payload.website else None
    profile.bank_name = payload.bank_name.strip() if payload.bank_name else None
    profile.branch_name = payload.branch_name.strip() if payload.branch_name else None
    profile.account_name = payload.account_name.strip() if payload.account_name else None
    profile.account_number = payload.account_number.strip() if payload.account_number else None
    profile.ifsc_code = payload.ifsc_code.strip().upper() if payload.ifsc_code else None
    profile.additional_company_info = payload.additional_company_info
    profile.show_sku_on_pdf = payload.show_sku_on_pdf
    # Only what the client sent: an omitted eway_* field keeps its stored value
    # instead of snapping back to the schema default (an API client or AI
    # assistant sending a partial body must not silently change e-way settings).
    for field in ("eway_enabled", "eway_local_threshold", "eway_interstate_threshold", "eway_always_show_button"):
        if field in payload.model_fields_set:
            setattr(profile, field, getattr(payload, field))
    profile.show_pay_qr_on_invoice = payload.show_pay_qr_on_invoice
    profile.show_upi_pay_button = payload.show_upi_pay_button
    db.commit()
    db.refresh(profile)

    track(
        "company_profile_saved",
        distinct_id_for(current_user),
        {
            "company_id": profile.id,
            "is_initial_setup": is_initial_setup,
            "has_gst": bool(profile.gst),
            "has_logo": bool(profile.logo_data),
            "currency_code": profile.currency_code,
        },
    )
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
    current_user: User = Depends(require_company_role(UserRole.admin, UserRole.manager)),
    profile: CompanyProfile = Depends(get_active_company),
):

    # Decode to check file size before optimization. Strict, because this string is
    # later written into PDF markup: outside the base64 alphabet it would be HTML.
    try:
        raw_bytes = base64.b64decode(payload.data, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 data.")

    file_size_kb = len(raw_bytes) / 1024
    if file_size_kb > 100:
        raise HTTPException(
            status_code=400,
            detail="Logo size cannot exceed 100 KB.",
        )

    # The bytes decide the type, not the client: mime_type is served back on the public
    # share page, where image/svg+xml would run as a script on this origin.
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_mime = "image/png"
    elif raw_bytes.startswith(b"\xff\xd8\xff"):
        detected_mime = "image/jpeg"
    else:
        raise HTTPException(status_code=400, detail="Logo must be a PNG or JPEG image.")

    # Optimize (resize + compress)
    optimized_data, optimized_mime = _optimize_logo_image(payload.data, detected_mime)

    profile.logo_data = optimized_data
    profile.logo_mime_type = optimized_mime
    db.commit()
    db.refresh(profile)
    return _company_to_out(profile)


@router.delete("/logo", response_model=CompanyProfileOut)
def remove_logo(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_company_role(UserRole.admin, UserRole.manager)),
    profile: CompanyProfile = Depends(get_active_company),
):
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
    company: CompanyProfile = Depends(get_active_company),
):
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
    current_user: User = Depends(require_company_role(UserRole.admin, UserRole.manager)),
    company: CompanyProfile = Depends(get_active_company),
):
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
    current_user: User = Depends(require_company_role(UserRole.admin, UserRole.manager)),
    company: CompanyProfile = Depends(get_active_company),
):
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
    current_user: User = Depends(require_company_role(UserRole.admin, UserRole.manager)),
    company: CompanyProfile = Depends(get_active_company),
):
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
