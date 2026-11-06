from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user, require_company_role
from src.core.config import settings
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.invoice_series import InvoiceSeries
from src.models.user import User, UserRole
from src.schemas.financial_year import FinancialYearCreate, FinancialYearOut
from src.services.financial_year import activate_fy, get_active_fy
from src.services.series import gstr1_series_warning

router = APIRouter()


DEFAULT_SERIES_CONFIGS = {
    "sales": {"prefix": "INV", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    "purchase": {"prefix": "PINV", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    "payment": {"prefix": "PAY", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    "credit_note": {"prefix": "CN", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    # Notes received from suppliers number separately so the outward credit
    # note series stays contiguous for GSTR-1 Table 13.
    "debit_note": {"prefix": "DN", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    # Offers, not tax documents: separate counters so a quotation can never use up
    # an invoice number or leave a gap in the sales series.
    "quotation": {"prefix": "QT", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
    "proforma": {"prefix": "PI", "suffix": "", "include_year": True, "year_format": "YYYY", "separator": "-", "pad_digits": 3},
}


def _seed_series_for_fy(db: Session, new_fy_id: int, company_id: int | None = None) -> None:
    """Create FY-scoped series rows with reset counters and complete voucher coverage."""
    active_fy = get_active_fy(db, company_id=company_id)
    if active_fy is None:
        for voucher_type, config in DEFAULT_SERIES_CONFIGS.items():
            db.add(InvoiceSeries(
                company_id=company_id,
                voucher_type=voucher_type,
                financial_year_id=new_fy_id,
                prefix=config["prefix"],
                suffix=config["suffix"],
                include_year=config["include_year"],
                year_format=config["year_format"],
                separator=config["separator"],
                next_sequence=1,
                pad_digits=config["pad_digits"],
            ))
        return

    source_rows = (
        db.query(InvoiceSeries)
        .filter(InvoiceSeries.financial_year_id == active_fy.id)
        .all()
    )
    if company_id is not None:
        # A NULL-company row is a legacy single-tenant template; in shared
        # hosting it belongs to nobody, so only the company's own rows count.
        allowed_owners = {company_id} if settings.is_shared_hosting else {None, company_id}
        source_rows = [row for row in source_rows if row.company_id in allowed_owners]
    source_by_type = {row.voucher_type: row for row in source_rows}

    for voucher_type, default_config in DEFAULT_SERIES_CONFIGS.items():
        src = source_by_type.get(voucher_type)
        db.add(InvoiceSeries(
            company_id=company_id,
            voucher_type=voucher_type,
            financial_year_id=new_fy_id,
            prefix=src.prefix if src else default_config["prefix"],
            suffix=src.suffix if src else default_config["suffix"],
            include_year=src.include_year if src else default_config["include_year"],
            year_format=src.year_format if src else default_config["year_format"],
            separator=src.separator if src else default_config["separator"],
            next_sequence=1,
            pad_digits=src.pad_digits if src else default_config["pad_digits"],
        ))


@router.get("", response_model=list[FinancialYearOut], include_in_schema=False)
@router.get("/", response_model=list[FinancialYearOut])
def list_financial_years(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    return (
        db.query(FinancialYear)
        .filter(FinancialYear.company_id == active_company.id)
        .order_by(FinancialYear.start_date.asc())
        .all()
    )


@router.post("/", response_model=FinancialYearOut, status_code=201)
def create_financial_year(
    payload: FinancialYearCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_company_role(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    existing = db.query(FinancialYear).filter(
        FinancialYear.company_id == active_company.id,
        FinancialYear.label == payload.label,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Financial year '{payload.label}' already exists.")

    overlapping = db.query(FinancialYear).filter(
        FinancialYear.company_id == active_company.id,
        FinancialYear.start_date <= payload.end_date,
        FinancialYear.end_date >= payload.start_date,
    ).first()
    if overlapping:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Financial year '{payload.label}' overlaps '{overlapping.label}' "
                f"({overlapping.start_date} to {overlapping.end_date})."
            ),
        )

    fy = FinancialYear(
        company_id=active_company.id,
        label=payload.label,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_active=False,
    )
    db.add(fy)
    try:
        db.flush()  # get fy.id before committing
        _seed_series_for_fy(db, fy.id, active_company.id)
        db.flush()
        # A series that prints the year label takes on this new label. Nobody can
        # edit a generated label, and a year has to be there to work in, so this
        # warns rather than refuses. Settings shows the same warning on the series.
        warnings: list[str] = []
        if (active_company.gst or "").strip():
            for series in db.query(InvoiceSeries).filter(
                InvoiceSeries.financial_year_id == fy.id,
                InvoiceSeries.voucher_type.in_(("sales", "credit_note")),
                InvoiceSeries.year_format == "FY",
                InvoiceSeries.include_year.is_(True),
            ):
                warning = gstr1_series_warning(series, fy)
                if warning:
                    warnings.append(f"{series.voucher_type.replace('_', ' ').capitalize()} series: {warning}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_financial_years_label" in str(exc.orig):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Financial year '{payload.label}' already exists in another company under legacy global constraint. "
                    "Run latest migrations to enable per-company FY labels."
                ),
            )
        raise
    db.refresh(fy)
    created = FinancialYearOut.model_validate(fy)
    created.warnings = warnings
    return created


@router.put("/{fy_id}/activate", response_model=FinancialYearOut)
def activate_financial_year(
    fy_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_company_role(UserRole.admin)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    fy = activate_fy(db, fy_id, company_id=active_company.id)
    if not fy:
        raise HTTPException(status_code=404, detail=f"Financial year {fy_id} not found")
    return fy
