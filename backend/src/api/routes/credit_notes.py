import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_active_company, get_current_user
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote, CreditNoteInvoiceRef
from src.models.user import User
from src.schemas.credit_note import CreditNoteCreate, CreditNoteOut, PaginatedCreditNoteOut
from src.services.credit_note import cancel_credit_note, create_credit_note

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
    return _to_out(cn)


@router.get("", response_model=PaginatedCreditNoteOut, include_in_schema=False)
@router.get("/", response_model=PaginatedCreditNoteOut)
def list_credit_notes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    ledger_id: Optional[int] = Query(None),
    invoice_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
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
        q = q.filter(or_(CreditNote.company_id == company_id, CreditNote.company_id.is_(None)))

    if ledger_id is not None:
        q = q.filter(CreditNote.ledger_id == ledger_id)

    if invoice_id is not None:
        q = q.join(CreditNoteInvoiceRef, CreditNoteInvoiceRef.credit_note_id == CreditNote.id).filter(
            CreditNoteInvoiceRef.invoice_id == invoice_id
        )

    if status is not None:
        q = q.filter(CreditNote.status == status)

    if search:
        q = q.filter(CreditNote.credit_note_number.ilike(f"%{search}%"))

    if date_from:
        from datetime import datetime as dt
        q = q.filter(CreditNote.created_at >= dt.fromisoformat(date_from))

    if date_to:
        from datetime import datetime as dt
        q = q.filter(CreditNote.created_at <= dt.fromisoformat(date_to))

    total = q.count()
    total_pages = math.ceil(total / page_size) if total else 1
    cns = q.order_by(CreditNote.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

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
        filters.append(or_(CreditNote.company_id == company_id, CreditNote.company_id.is_(None)))
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


@router.post("/{cn_id}/cancel", response_model=CreditNoteOut)
def cancel_credit_note_endpoint(
    cn_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    cn = cancel_credit_note(cn_id, db, company_id=company_id)
    db.refresh(cn)
    return _to_out(cn)
