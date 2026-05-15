import math
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, require_roles
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.email_log import EmailLog
from src.models.user import User, UserRole

router = APIRouter()


class EmailLogItem(BaseModel):
    id: int
    company_id: Optional[int]
    to_email: str
    cc: Optional[str]
    subject: str
    email_type: str
    reference_id: Optional[int]
    status: str
    error_message: Optional[str]
    sent_by_user_id: Optional[int]
    sent_at: str

    class Config:
        from_attributes = True


class PaginatedEmailLogs(BaseModel):
    items: list[EmailLogItem]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("/", response_model=PaginatedEmailLogs)
def list_email_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    email_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)

    query = db.query(EmailLog)

    if company_id is not None:
        query = query.filter(EmailLog.company_id == company_id)

    if email_type:
        query = query.filter(EmailLog.email_type == email_type)

    if status:
        query = query.filter(EmailLog.status == status)

    if from_date:
        query = query.filter(EmailLog.sent_at >= from_date)

    if to_date:
        query = query.filter(EmailLog.sent_at < to_date + timedelta(days=1))

    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))

    logs = (
        query.order_by(EmailLog.sent_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        EmailLogItem(
            id=log.id,
            company_id=log.company_id,
            to_email=log.to_email,
            cc=log.cc,
            subject=log.subject,
            email_type=log.email_type,
            reference_id=log.reference_id,
            status=log.status,
            error_message=log.error_message,
            sent_by_user_id=log.sent_by_user_id,
            sent_at=log.sent_at.isoformat() if log.sent_at else "",
        )
        for log in logs
    ]

    return PaginatedEmailLogs(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
