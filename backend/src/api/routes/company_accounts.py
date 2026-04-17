from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.deps import get_current_user, require_roles
from src.db.session import get_db
from src.models.company_account import CompanyAccount
from src.models.user import User, UserRole
from src.schemas.company_account import CompanyAccountCreate, CompanyAccountOut, CompanyAccountUpdate

router = APIRouter()


@router.post("", response_model=CompanyAccountOut, include_in_schema=False)
@router.post("/", response_model=CompanyAccountOut)
def create_company_account(
    payload: CompanyAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    account = CompanyAccount(
        account_type=payload.account_type,
        display_name=payload.display_name,
        bank_name=payload.bank_name.strip() if payload.bank_name else None,
        branch_name=payload.branch_name.strip() if payload.branch_name else None,
        account_name=payload.account_name.strip() if payload.account_name else None,
        account_number=payload.account_number.strip() if payload.account_number else None,
        ifsc_code=payload.ifsc_code.strip().upper() if payload.ifsc_code else None,
        display_on_invoice=payload.display_on_invoice if payload.account_type == "bank" else False,
        opening_balance=payload.opening_balance,
        is_active=payload.is_active,
        created_by=current_user.id,
        updated_at=datetime.utcnow(),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("", response_model=list[CompanyAccountOut], include_in_schema=False)
@router.get("/", response_model=list[CompanyAccountOut])
def list_company_accounts(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(CompanyAccount)
    if not include_inactive:
        query = query.filter(CompanyAccount.is_active.is_(True))
    return query.order_by(CompanyAccount.display_name.asc(), CompanyAccount.id.asc()).all()


@router.get("/{account_id}", response_model=CompanyAccountOut)
def get_company_account(
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    account = db.query(CompanyAccount).filter(CompanyAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.put("/{account_id}", response_model=CompanyAccountOut)
def update_company_account(
    account_id: int,
    payload: CompanyAccountUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    account = db.query(CompanyAccount).filter(CompanyAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if payload.account_type is not None:
        account.account_type = payload.account_type
        if account.account_type == "cash":
            account.display_on_invoice = False
    if payload.display_name is not None:
        account.display_name = payload.display_name
    if payload.bank_name is not None:
        account.bank_name = payload.bank_name.strip() or None
    if payload.branch_name is not None:
        account.branch_name = payload.branch_name.strip() or None
    if payload.account_name is not None:
        account.account_name = payload.account_name.strip() or None
    if payload.account_number is not None:
        account.account_number = payload.account_number.strip() or None
    if payload.ifsc_code is not None:
        account.ifsc_code = payload.ifsc_code.strip().upper() or None
    if payload.display_on_invoice is not None:
        account.display_on_invoice = payload.display_on_invoice if account.account_type == "bank" else False
    if payload.opening_balance is not None:
        account.opening_balance = payload.opening_balance
    if payload.is_active is not None:
        account.is_active = payload.is_active

    account.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}")
def deactivate_company_account(
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    account = db.query(CompanyAccount).filter(CompanyAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.is_active = False
    account.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Account deactivated"}
