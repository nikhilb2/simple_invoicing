"""Quotations and proforma invoices. Same permissions as invoices: any company member.

Analytics are tracked after each commit, outside the try block, for the reason
explained in ``invoices.py``: a request that has committed must not be reported as
a failure because the analytics host was unreachable.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.api.deps import get_active_company, get_current_user
from src.api.routes.invoices import build_invoice_out, track_invoice_created
from src.core.analytics import distinct_id_for, track
from src.core.http_headers import content_disposition
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.product import Product
from src.models.quotation import (
    EXPIRABLE_STATUSES,
    STATUS_EXPIRED,
    Quotation,
)
from src.models.user import User
from src.schemas.invoice import InvoiceOut
from src.schemas.quotation import (
    DocumentType,
    LinkedInvoiceOut,
    PaginatedQuotationOut,
    QuotationConversionDraft,
    QuotationConvert,
    QuotationCreate,
    QuotationOut,
    QuotationStatusUpdate,
    QuotationUpdate,
    StatusFilter,
)
from src.services.company_access import company_scope
from src.services.gst_tax_service import india_today
from src.services.quotation import (
    already_converted_error,
    build_conversion_draft,
    cancel_quotation,
    convert_quotation,
    create_quotation,
    display_status,
    duplicate_quotation,
    get_quotation,
    linked_invoices,
    require_quotation,
    set_quotation_status,
    update_quotation,
)
from src.services.share_documents import render_quotation_pdf

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_out_many(db: Session, quotations: list[Quotation], company_id: int) -> list[QuotationOut]:
    product_ids = {item.product_id for quotation in quotations for item in quotation.items}
    names = {}
    if product_ids:
        names = {
            product.id: product.name
            for product in db.query(Product).filter(
                Product.id.in_(product_ids),
                company_scope(Product.company_id, company_id),
            )
        }
    invoices = linked_invoices(db, [quotation.id for quotation in quotations])
    today = date.today()

    results = []
    for quotation in quotations:
        result = QuotationOut.model_validate(quotation)
        result.is_expired = quotation.is_expired_on(today)
        result.display_status = display_status(quotation, today)
        for item in result.items:
            item.product_name = names.get(item.product_id)
        history = invoices.get(quotation.id, [])
        result.invoices = [
            LinkedInvoiceOut(id=invoice.id, invoice_number=invoice.invoice_number, status=invoice.status)
            for invoice in history
        ]
        live = next((invoice for invoice in history if invoice.status == "active"), None)
        if live is not None:
            result.converted_invoice_id = live.id
            result.converted_invoice_number = live.invoice_number
        results.append(result)
    return results


def _to_out(db: Session, quotation: Quotation, company_id: int) -> QuotationOut:
    return _to_out_many(db, [quotation], company_id)[0]


def _write(db: Session, work, *, failure: str):
    """Run ``work`` and commit it, rolling back on any failure."""
    try:
        result = work()
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        logger.exception(failure)
        db.rollback()
        raise HTTPException(status_code=500, detail=failure)


@router.post("", response_model=QuotationOut, include_in_schema=False)
@router.post("/", response_model=QuotationOut)
def create(
    payload: QuotationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    quotation = _write(
        db,
        lambda: create_quotation(db, payload, created_by=current_user.id, company=active_company),
        failure="Failed to create quotation",
    )
    db.refresh(quotation)
    track(
        "quotation_created",
        distinct_id_for(current_user),
        {
            "quotation_id": quotation.id,
            "document_type": quotation.document_type,
            "line_item_count": len(payload.items),
            "total_amount": float(quotation.total_amount or 0),
            "has_valid_until": quotation.valid_until is not None,
            "validity_days": (
                (quotation.valid_until - quotation.quotation_date).days if quotation.valid_until else None
            ),
        },
    )
    return _to_out(db, quotation, active_company.id)


@router.get("", response_model=PaginatedQuotationOut, include_in_schema=False)
@router.get("/", response_model=PaginatedQuotationOut)
def list_quotations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(""),
    status: StatusFilter | None = Query(None),
    document_type: DocumentType | None = Query(None),
    ledger_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    query = db.query(Quotation).filter(Quotation.company_id == active_company.id)
    if document_type is not None:
        query = query.filter(Quotation.document_type == document_type)
    if ledger_id is not None:
        query = query.filter(Quotation.ledger_id == ledger_id)
    if date_from is not None:
        query = query.filter(Quotation.quotation_date >= date_from)
    if date_to is not None:
        query = query.filter(Quotation.quotation_date <= date_to)
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(or_(Quotation.quotation_number.ilike(term), Quotation.ledger_name.ilike(term)))

    today = date.today()
    expired = and_(
        Quotation.valid_until.isnot(None),
        Quotation.valid_until < today,
        Quotation.status.in_(EXPIRABLE_STATUSES),
    )
    shown_status = case((expired, STATUS_EXPIRED), else_=Quotation.status)
    status_counts = {
        row[0]: row[1]
        for row in query.with_entities(shown_status, func.count(Quotation.id)).group_by(shown_status).all()
    }

    # Filters on what the list shows: "open" means still open, not open and expired.
    if status is not None:
        query = query.filter(shown_status == status)

    total = query.count()
    rows = (
        query.options(selectinload(Quotation.items))
        .order_by(Quotation.quotation_date.desc(), Quotation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedQuotationOut(
        items=_to_out_many(db, rows, active_company.id),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
        status_counts=status_counts,
    )


@router.get("/{quotation_id}", response_model=QuotationOut)
def get_one(
    quotation_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    return _to_out(db, require_quotation(db, active_company.id, quotation_id), active_company.id)


@router.put("/{quotation_id}", response_model=QuotationOut)
def update(
    quotation_id: int,
    payload: QuotationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    def work():
        quotation = require_quotation(db, active_company.id, quotation_id, lock=True)
        return update_quotation(db, quotation, payload, company=active_company)

    quotation = _write(db, work, failure="Failed to update quotation")
    db.refresh(quotation)
    track(
        "quotation_updated",
        distinct_id_for(current_user),
        {
            "quotation_id": quotation.id,
            "document_type": quotation.document_type,
            "line_item_count": len(payload.items),
            "total_amount": float(quotation.total_amount or 0),
        },
    )
    return _to_out(db, quotation, active_company.id)


@router.post("/{quotation_id}/status", response_model=QuotationOut)
def set_status(
    quotation_id: int,
    payload: QuotationStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    def work():
        quotation = require_quotation(db, active_company.id, quotation_id, lock=True)
        return quotation, set_quotation_status(quotation, payload)

    quotation, previous = _write(db, work, failure="Failed to update quotation status")
    db.refresh(quotation)
    track(
        "quotation_status_changed",
        distinct_id_for(current_user),
        {
            "quotation_id": quotation.id,
            "document_type": quotation.document_type,
            "from_status": previous,
            "to_status": quotation.status,
        },
    )
    return _to_out(db, quotation, active_company.id)


@router.post("/{quotation_id}/cancel", response_model=QuotationOut)
def cancel(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    def work():
        quotation = require_quotation(db, active_company.id, quotation_id, lock=True)
        cancel_quotation(db, quotation)
        return quotation

    quotation = _write(db, work, failure="Failed to cancel quotation")
    db.refresh(quotation)
    track(
        "quotation_cancelled",
        distinct_id_for(current_user),
        {"quotation_id": quotation.id, "document_type": quotation.document_type},
    )
    return _to_out(db, quotation, active_company.id)


@router.post("/{quotation_id}/duplicate", response_model=QuotationOut)
def duplicate(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    original = require_quotation(db, active_company.id, quotation_id)
    quotation = _write(
        db,
        lambda: duplicate_quotation(db, original, created_by=current_user.id, company=active_company),
        failure="Failed to duplicate quotation",
    )
    db.refresh(quotation)
    track(
        "quotation_created",
        distinct_id_for(current_user),
        {
            "quotation_id": quotation.id,
            "document_type": quotation.document_type,
            "line_item_count": len(quotation.items),
            "total_amount": float(quotation.total_amount or 0),
            "has_valid_until": quotation.valid_until is not None,
            "validity_days": (
                (quotation.valid_until - quotation.quotation_date).days if quotation.valid_until else None
            ),
            "duplicated_from": quotation_id,
        },
    )
    return _to_out(db, quotation, active_company.id)


@router.get("/{quotation_id}/conversion-draft", response_model=QuotationConversionDraft)
def conversion_draft(
    quotation_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    quotation = require_quotation(db, active_company.id, quotation_id)
    return build_conversion_draft(db, quotation, company=active_company)


@router.post("/{quotation_id}/convert", response_model=InvoiceOut)
def convert(
    quotation_id: int,
    payload: QuotationConvert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    try:
        quotation, invoice, warnings = convert_quotation(
            db,
            quotation_id,
            payload,
            created_by=current_user.id,
            company=active_company,
        )
        # Read before commit: expire_on_commit would make these look like fresh queries.
        # India's date, because the quotation was dated by it: the server's could make
        # days_since_quote -1 just after midnight there.
        today = india_today()
        was_expired = bool(quotation.valid_until and quotation.valid_until < today)
        quoted_total = float(quotation.total_amount or 0)
        quoted_rates = {item.product_id: float(item.gst_rate or 0) for item in quotation.items}
        days_since_quote = (today - quotation.quotation_date).days
        document_type = quotation.document_type
        db.commit()
        db.refresh(invoice)
        result = build_invoice_out(db, invoice, active_company, warnings)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        # The partial unique index, reached by something the row lock did not catch.
        if "source_quotation" not in str(exc):
            logger.exception("Error converting quotation")
            raise HTTPException(status_code=500, detail="Failed to convert quotation")
        quotation = get_quotation(db, active_company.id, quotation_id)
        live = next(
            (row for row in linked_invoices(db, [quotation_id]).get(quotation_id, []) if row.status == "active"),
            None,
        )
        raise already_converted_error(quotation, live)
    except Exception:
        logger.exception("Error converting quotation")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to convert quotation")

    track_invoice_created(current_user, invoice, payload, warnings, source="quotation")
    track(
        "quotation_converted",
        distinct_id_for(current_user),
        {
            "quotation_id": quotation_id,
            "invoice_id": invoice.id,
            "document_type": document_type,
            "days_since_quote": days_since_quote,
            "was_expired": was_expired,
            "total_changed": float(invoice.total_amount or 0) != quoted_total,
            "rate_changed": any(
                float(item.gst_rate or 0) != quoted_rates[item.product_id]
                for item in invoice.items
                if item.product_id in quoted_rates
            ),
        },
    )
    return result


@router.get("/{quotation_id}/pdf")
def download_pdf(
    quotation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    # Rendered in src/services/share_documents so the owner's copy and the one a
    # customer downloads from a share link are the same document.
    quotation = require_quotation(db, active_company.id, quotation_id)
    pdf_buffer = render_quotation_pdf(db, active_company.id, quotation_id)
    number = quotation.quotation_number.replace("/", "_")
    track(
        "quotation_pdf_downloaded",
        distinct_id_for(current_user),
        {"quotation_id": quotation.id, "document_type": quotation.document_type},
    )
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition("attachment", f"{quotation.document_type}_{number}.pdf")},
    )
