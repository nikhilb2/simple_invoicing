import math
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_active_company, get_current_user
from src.core.analytics import distinct_id_for, track
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote, CreditNoteInvoiceRef
from src.models.user import User
from src.schemas.credit_note import CreditNoteCreate, CreditNoteOut, PaginatedCreditNoteOut
from src.services.credit_note import cancel_credit_note, create_credit_note
from src.services.share_documents import render_credit_note_pdf
from src.services.company_access import company_scope

router = APIRouter()


def _to_out(cn: CreditNote) -> CreditNoteOut:
    data = CreditNoteOut.model_validate(cn)
    data.invoice_ids = [ref.invoice_id for ref in cn.invoice_refs]
    return data


@router.post("", response_model=CreditNoteOut, status_code=201, include_in_schema=False)
@router.post("/", response_model=CreditNoteOut, status_code=201)
def create_credit_note_endpoint(
    payload: CreditNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    cn = create_credit_note(payload, db, current_user.id, company_id=company_id)
    db.refresh(cn)
    result = _to_out(cn)

    track(
        "credit_note_created",
        distinct_id_for(current_user),
        {
            "credit_note_id": cn.id,
            "credit_note_type": cn.credit_note_type,
            "direction": result.direction,
            "invoice_count": len(result.invoice_ids),
            "line_item_count": len(result.items),
            "total_amount": float(cn.total_amount or 0),
            "has_reason": bool(cn.reason and cn.reason.strip()),
        },
    )
    return result


@router.get("", response_model=PaginatedCreditNoteOut, include_in_schema=False)
@router.get("/", response_model=PaginatedCreditNoteOut)
def list_credit_notes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    ledger_id: Optional[int] = Query(None),
    invoice_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    q = (
        db.query(CreditNote)
        .options(
            joinedload(CreditNote.invoice_refs),
            joinedload(CreditNote.items),
        )
    )
    if company_id is not None:
        q = q.filter(company_scope(CreditNote.company_id, company_id))

    if ledger_id is not None:
        q = q.filter(CreditNote.ledger_id == ledger_id)

    if invoice_id is not None:
        q = q.join(CreditNoteInvoiceRef, CreditNoteInvoiceRef.credit_note_id == CreditNote.id).filter(
            CreditNoteInvoiceRef.invoice_id == invoice_id
        )

    if status is not None:
        q = q.filter(CreditNote.status == status)

    if direction is not None:
        # Rows predating the column are all outward.
        if direction == "outward":
            q = q.filter(or_(CreditNote.direction == "outward", CreditNote.direction.is_(None)))
        else:
            q = q.filter(CreditNote.direction == direction)

    if search:
        # A supplier's note is looked up by their number, not the one we gave it.
        q = q.filter(
            or_(
                CreditNote.credit_note_number.ilike(f"%{search}%"),
                CreditNote.supplier_credit_note_number.ilike(f"%{search}%"),
            )
        )

    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be before or equal to date_to")

    if date_from:
        q = q.filter(CreditNote.credit_note_date >= date_from)

    if date_to:
        # Whole-day semantics: credit_note_date is a timestamp, so the end of the
        # selected day is midnight of the day after date_to, as email_logs does.
        q = q.filter(CreditNote.credit_note_date < date_to + timedelta(days=1))

    total = q.count()
    total_pages = math.ceil(total / page_size) if total else 1
    cns = q.order_by(CreditNote.credit_note_date.desc(), CreditNote.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return PaginatedCreditNoteOut(
        items=[_to_out(cn) for cn in cns],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{cn_id}", response_model=CreditNoteOut)
def get_credit_note(
    cn_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    filters = [CreditNote.id == cn_id]
    if company_id is not None:
        filters.append(company_scope(CreditNote.company_id, company_id))
    cn = (
        db.query(CreditNote)
        .options(
            joinedload(CreditNote.invoice_refs),
            joinedload(CreditNote.items),
        )
        .filter(*filters)
        .first()
    )
    if not cn:
        raise HTTPException(status_code=404, detail="Credit note not found")
    return _to_out(cn)


@router.get("/{cn_id}/pdf")
def download_credit_note_pdf(
    cn_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    # Rendered in src/services/share_documents, like invoices and receipts, so the
    # owner's copy and the one a customer opens from a share link are the same
    # document. 404s for an inward note: that one is the supplier's to issue.
    company_id = active_company.id
    cn = (
        db.query(CreditNote)
        .filter(CreditNote.id == cn_id)
        .filter(company_scope(CreditNote.company_id, company_id))
        .first()
    )
    if not cn:
        raise HTTPException(status_code=404, detail="Credit note not found")

    buf = render_credit_note_pdf(db, company_id, cn_id)

    filename = f"credit_note_{cn.credit_note_number.replace('/', '_')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{cn_id}/cancel", response_model=CreditNoteOut)
def cancel_credit_note_endpoint(
    cn_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    return cancel_credit_note(cn_id, db, company_id=company_id)
