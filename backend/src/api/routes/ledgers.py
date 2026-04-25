import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from html import escape
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

import weasyprint

from src.api.deps import get_active_company, get_current_user, require_roles
from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.invoice import Invoice
from src.models.invoice import InvoiceItem
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.models.user import User, UserRole
from src.schemas.invoice import OutstandingInvoiceOut
from src.schemas.ledger import DayBookEntry, DayBookOut, LedgerCreate, LedgerOut, LedgerStatementEntry, LedgerStatementInvoiceAllocation, LedgerStatementOut, PaginatedLedgerOut, TaxLedgerEntry, TaxLedgerOut, TaxLedgerTotals
from src.services.credit_note_reporting import get_credit_note_ledger_summary
from src.services.financial_year import get_active_fy
from src.services.invoice_payments import auto_allocate_outstanding_invoices, build_invoice_payment_summaries, get_outstanding_invoices_for_ledger

router = APIRouter()


@dataclass
class LedgerStatementData:
    opening_balance: float
    period_debit: float
    period_credit: float
    closing_balance: float
    entries: list[LedgerStatementEntry]


@dataclass
class DayBookData:
  total_debit: float
  total_credit: float
  entries: list[DayBookEntry]


def _make_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC) for consistent sorting."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _active_invoices_query(db: Session, company_id: int | None = None):
  query = db.query(Invoice).filter(Invoice.status == "active")
  if company_id is not None:
    query = query.filter(or_(Invoice.company_id == company_id, Invoice.company_id.is_(None)))
  return query


def _active_payments_query(db: Session, company_id: int | None = None):
  query = db.query(Payment).filter(Payment.status == "active")
  if company_id is not None:
    query = query.filter(or_(Payment.company_id == company_id, Payment.company_id.is_(None)))
  return query


def _get_opening_balance_payment(db: Session, ledger_id: int, company_id: int | None = None) -> Payment | None:
  query = (
    db.query(Payment)
    .filter(
      Payment.ledger_id == ledger_id,
      Payment.voucher_type == "opening_balance",
      Payment.status == "active",
    )
  )
  if company_id is not None:
    query = query.filter(or_(Payment.company_id == company_id, Payment.company_id.is_(None)))
  return query.first()


def _serialize_ledger(db: Session, ledger: Ledger, company_id: int | None = None) -> LedgerOut:
  opening_balance_payment = _get_opening_balance_payment(db, ledger.id, company_id=company_id)
  return LedgerOut(
    id=ledger.id,
    name=ledger.name,
    address=ledger.address,
    gst=ledger.gst,
    opening_balance=float(opening_balance_payment.amount) if opening_balance_payment else None,
    phone_number=ledger.phone_number,
    email=ledger.email,
    website=ledger.website,
    bank_name=ledger.bank_name,
    branch_name=ledger.branch_name,
    account_name=ledger.account_name,
    account_number=ledger.account_number,
    ifsc_code=ledger.ifsc_code,
  )


def _default_opening_balance_date(db: Session, company_id: int | None = None) -> tuple[datetime, int | None]:
  active_fy = get_active_fy(db, company_id=company_id)
  if active_fy is not None:
    return datetime.combine(active_fy.start_date, time.min), active_fy.id
  return datetime.utcnow(), None


def _sync_opening_balance(
  db: Session,
  ledger_id: int,
  opening_balance: float | None,
  current_user_id: int,
  company_id: int | None = None,
) -> None:
  existing = _get_opening_balance_payment(db, ledger_id, company_id=company_id)
  normalized = None if opening_balance is None or opening_balance == 0 else float(opening_balance)

  if normalized is None:
    if existing is not None:
      db.delete(existing)
    return

  if existing is not None:
    existing.amount = normalized
    return

  opening_date, fy_id = _default_opening_balance_date(db, company_id=company_id)
  db.add(Payment(
    ledger_id=ledger_id,
    company_id=company_id,
    voucher_type="opening_balance",
    amount=normalized,
    date=opening_date,
    payment_number=None,
    financial_year_id=fy_id,
    created_by=current_user_id,
    status="active",
  ))


def _format_voucher_label(voucher_type: str) -> str:
  return voucher_type.replace("_", " ").title()


def _payment_debit_credit(payment: Payment) -> tuple[float, float]:
  amount = float(payment.amount)
  if payment.voucher_type == "payment":
    return amount, 0.0
  if payment.voucher_type == "receipt":
    return 0.0, amount
  if payment.voucher_type == "opening_balance":
    if amount > 0:
      return amount, 0.0
    return 0.0, abs(amount)
  return 0.0, 0.0


def _build_day_book_data(
    db: Session,
    from_date: date,
    to_date: date,
    company_id: int | None = None,
  ) -> DayBookData:
    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    invoices = (
      _active_invoices_query(db, company_id=company_id)
      .filter(Invoice.invoice_date >= period_start)
      .filter(Invoice.invoice_date <= period_end)
      .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
      .all()
    )

    payments = (
      _active_payments_query(db, company_id=company_id)
      .options(joinedload(Payment.account))
      .filter(Payment.date >= period_start)
      .filter(Payment.date <= period_end)
      .order_by(Payment.date.asc(), Payment.id.asc())
      .all()
    )

    credit_note_summary = get_credit_note_ledger_summary(
      db,
      company_id=company_id,
      created_from=period_start,
      created_to=period_end,
    )

    ledgers_by_id: dict[int, Ledger] = {}
    ledger_ids = {payment.ledger_id for payment in payments if payment.ledger_id is not None}
    if ledger_ids:
      ledger_query = db.query(Ledger).filter(Ledger.id.in_(ledger_ids))
      if company_id is not None:
        ledger_query = ledger_query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
      ledgers_by_id = {ledger.id: ledger for ledger in ledger_query.all()}

    entries: list[DayBookEntry] = []
    for invoice in invoices:
      entries.append(DayBookEntry(
        entry_id=invoice.id,
        entry_type="invoice",
        date=invoice.invoice_date,
        voucher_type=invoice.voucher_type.title(),
        reference_number=invoice.invoice_number,
        ledger_name=invoice.ledger_name or "Unknown ledger",
        particulars=f"{invoice.voucher_type.title()} Invoice #{invoice.id}",
        debit=float(invoice.total_amount) if invoice.voucher_type == "sales" else 0.0,
        credit=float(invoice.total_amount) if invoice.voucher_type == "purchase" else 0.0,
      ))
    for payment in payments:
      debit, credit = _payment_debit_credit(payment)
      payment_ledger = ledgers_by_id.get(payment.ledger_id) if payment.ledger_id is not None else None
      entries.append(DayBookEntry(
        entry_id=payment.id,
        entry_type="payment",
        date=payment.date,
        voucher_type=_format_voucher_label(payment.voucher_type),
        reference_number=payment.payment_number,
        ledger_name=payment_ledger.name if payment_ledger else "Unknown ledger",
        particulars=f"{_format_voucher_label(payment.voucher_type)} #{payment.id}" + (f" ({payment.mode})" if payment.mode else ""),
        debit=debit,
        credit=credit,
        account_display_name=payment.account.display_name if payment.account else None,
        account_type=payment.account.account_type if payment.account else None,
      ))
    for credit_note_entry in credit_note_summary.entries:
      entries.append(DayBookEntry(
        entry_id=credit_note_entry.entry_id,
        entry_type="credit_note",
        date=credit_note_entry.date,
        voucher_type=credit_note_entry.voucher_type,
        reference_number=credit_note_entry.credit_note_number,
        ledger_name=credit_note_entry.ledger_name,
        particulars=credit_note_entry.particulars,
        debit=credit_note_entry.debit,
        credit=credit_note_entry.credit,
      ))
    entries.sort(key=lambda entry: _make_aware(entry.date))

    return DayBookData(
      total_debit=sum(entry.debit for entry in entries),
      total_credit=sum(entry.credit for entry in entries),
      entries=entries,
    )


def _build_ledger_statement_data(
    db: Session,
    ledger: Ledger,
    from_date: date,
    to_date: date,
  company_id: int | None = None,
) -> LedgerStatementData:
    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    opening_totals = (
        _active_invoices_query(db, company_id=company_id)
        .with_entities(
            func.coalesce(func.sum(case((Invoice.voucher_type == "sales", Invoice.total_amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.voucher_type == "purchase", Invoice.total_amount), else_=0)), 0),
        )
        .filter(Invoice.ledger_id == ledger.id)
        .filter(Invoice.invoice_date < period_start)
        .one()
    )

    opening_payment_totals = (
        _active_payments_query(db, company_id=company_id)
        .with_entities(
            func.coalesce(func.sum(case((Payment.voucher_type == "payment", Payment.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.voucher_type == "receipt", Payment.amount), else_=0)), 0),
        func.coalesce(func.sum(case((((Payment.voucher_type == "opening_balance") & (Payment.amount > 0)), Payment.amount), else_=0)), 0),
        func.coalesce(func.sum(case((((Payment.voucher_type == "opening_balance") & (Payment.amount < 0)), -Payment.amount), else_=0)), 0),
        )
        .filter(Payment.ledger_id == ledger.id)
        .filter(Payment.date < period_start)
        .one()
    )

    opening_credit_note_summary = get_credit_note_ledger_summary(
        db,
        ledger_id=ledger.id,
      company_id=company_id,
        created_before=period_start,
    )

    period_invoices = (
        _active_invoices_query(db, company_id=company_id)
        .filter(Invoice.ledger_id == ledger.id)
        .filter(Invoice.invoice_date >= period_start)
        .filter(Invoice.invoice_date <= period_end)
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        .all()
    )

    period_payments = (
        _active_payments_query(db, company_id=company_id)
      .options(
        joinedload(Payment.account),
        joinedload(Payment.invoice_allocations).joinedload(PaymentInvoiceAllocation.invoice),
      )
        .filter(Payment.ledger_id == ledger.id)
        .filter(Payment.date >= period_start)
        .filter(Payment.date <= period_end)
        .order_by(Payment.date.asc(), Payment.id.asc())
        .all()
    )

    payment_allocation_invoices_by_id: dict[int, Invoice] = {}
    for payment in period_payments:
      for allocation in payment.invoice_allocations:
        if allocation.invoice is not None:
          payment_allocation_invoices_by_id[allocation.invoice.id] = allocation.invoice

    payment_invoice_summaries = build_invoice_payment_summaries(
      db,
      list(payment_allocation_invoices_by_id.values()),
    )

    period_credit_note_summary = get_credit_note_ledger_summary(
        db,
        ledger_id=ledger.id,
      company_id=company_id,
        created_from=period_start,
        created_to=period_end,
    )

    entries: list[LedgerStatementEntry] = []
    for invoice in period_invoices:
        entries.append(LedgerStatementEntry(
            entry_id=invoice.id,
            entry_type="invoice",
            date=invoice.invoice_date,
            voucher_type=invoice.voucher_type.title(),
            reference_number=invoice.invoice_number,
            particulars=invoice.ledger_name or ledger.name,
            debit=float(invoice.total_amount) if invoice.voucher_type == "sales" else 0.0,
            credit=float(invoice.total_amount) if invoice.voucher_type == "purchase" else 0.0,
        ))
    for payment in period_payments:
        debit, credit = _payment_debit_credit(payment)
        entry_allocations = []
        for allocation in payment.invoice_allocations:
          summary = payment_invoice_summaries.get(allocation.invoice_id)
          entry_allocations.append(
            LedgerStatementInvoiceAllocation(
              invoice_id=allocation.invoice_id,
              invoice_number=allocation.invoice.invoice_number if allocation.invoice else None,
              invoice_date=allocation.invoice.invoice_date if allocation.invoice else None,
              due_date=allocation.invoice.due_date if allocation.invoice else None,
              payment_status=summary.payment_status if summary else None,
              allocated_amount=float(allocation.allocated_amount or 0),
            )
          )
        entries.append(LedgerStatementEntry(
            entry_id=payment.id,
            entry_type="payment",
            date=payment.date,
            voucher_type=_format_voucher_label(payment.voucher_type),
            reference_number=payment.payment_number,
            particulars=f"{_format_voucher_label(payment.voucher_type)}" + (f" ({payment.mode})" if payment.mode else ""),
            debit=debit,
            credit=credit,
            account_display_name=payment.account.display_name if payment.account else None,
            account_type=payment.account.account_type if payment.account else None,
            invoice_allocations=entry_allocations,
        ))
    for credit_note_entry in period_credit_note_summary.entries:
        entries.append(LedgerStatementEntry(
            entry_id=credit_note_entry.entry_id,
            entry_type="credit_note",
            date=credit_note_entry.date,
            voucher_type=credit_note_entry.voucher_type,
            reference_number=credit_note_entry.credit_note_number,
            particulars=credit_note_entry.particulars,
            debit=credit_note_entry.debit,
            credit=credit_note_entry.credit,
        ))
    entries.sort(key=lambda entry: _make_aware(entry.date))

    period_debit = sum(entry.debit for entry in entries)
    period_credit = sum(entry.credit for entry in entries)
    opening_debit = float(opening_totals[0]) + float(opening_payment_totals[0]) + float(opening_payment_totals[2]) + opening_credit_note_summary.purchase_credit_total
    opening_credit = float(opening_totals[1]) + float(opening_payment_totals[1]) + float(opening_payment_totals[3]) + opening_credit_note_summary.sales_credit_total
    opening_balance = opening_debit - opening_credit
    closing_balance = opening_balance + period_debit - period_credit

    return LedgerStatementData(
        opening_balance=opening_balance,
        period_debit=period_debit,
        period_credit=period_credit,
        closing_balance=closing_balance,
        entries=entries,
    )


def _build_tax_ledger_totals(entries: list[TaxLedgerEntry]) -> TaxLedgerTotals:
    debit_cgst = sum(entry.debit_cgst for entry in entries)
    debit_sgst = sum(entry.debit_sgst for entry in entries)
    debit_igst = sum(entry.debit_igst for entry in entries)
    debit_total_tax = sum(entry.debit_total_tax for entry in entries)

    credit_cgst = sum(entry.credit_cgst for entry in entries)
    credit_sgst = sum(entry.credit_sgst for entry in entries)
    credit_igst = sum(entry.credit_igst for entry in entries)
    credit_total_tax = sum(entry.credit_total_tax for entry in entries)

    return TaxLedgerTotals(
        debit_cgst=debit_cgst,
        debit_sgst=debit_sgst,
        debit_igst=debit_igst,
        debit_total_tax=debit_total_tax,
        credit_cgst=credit_cgst,
        credit_sgst=credit_sgst,
        credit_igst=credit_igst,
        credit_total_tax=credit_total_tax,
        net_cgst=debit_cgst - credit_cgst,
        net_sgst=debit_sgst - credit_sgst,
        net_igst=debit_igst - credit_igst,
        net_total_tax=debit_total_tax - credit_total_tax,
    )


@router.post("", response_model=LedgerOut, include_in_schema=False)
@router.post("/", response_model=LedgerOut)
def create_ledger(
    payload: LedgerCreate,
    db: Session = Depends(get_db),
  current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
  active_company: CompanyProfile = Depends(get_active_company),
):
  company_id = getattr(active_company, "id", None)
  gst = payload.gst
  if gst:
    existing_query = db.query(Ledger).filter(Ledger.gst == gst)
    if company_id is not None:
      existing_query = existing_query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    existing_ledger = existing_query.first()
    if existing_ledger:
      raise HTTPException(status_code=400, detail="Ledger with this GST already exists")

  ledger = Ledger(
    name=payload.name.strip(),
    address=payload.address.strip(),
    gst=gst,
    phone_number=payload.phone_number.strip(),
    email=payload.email.strip() if payload.email else None,
    website=payload.website.strip() if payload.website else None,
    bank_name=payload.bank_name.strip() if payload.bank_name else None,
    branch_name=payload.branch_name.strip() if payload.branch_name else None,
    account_name=payload.account_name.strip() if payload.account_name else None,
    account_number=payload.account_number.strip() if payload.account_number else None,
    ifsc_code=payload.ifsc_code.strip().upper() if payload.ifsc_code else None,
    company_id=company_id,
  )
  db.add(ledger)
  try:
    db.flush()
    _sync_opening_balance(db, ledger.id, payload.opening_balance, current_user.id, company_id=company_id)
    db.commit()
  except IntegrityError as exc:
    db.rollback()
    if "ix_buyers_gst" in str(exc.orig) or "buyers_gst_key" in str(exc.orig):
      raise HTTPException(
        status_code=400,
        detail="Buyer with this GST already exists. Run latest migrations to enable per-company GST uniqueness.",
      )
    raise
  db.refresh(ledger)
  return _serialize_ledger(db, ledger, company_id=company_id)


@router.get("", response_model=PaginatedLedgerOut, include_in_schema=False)
@router.get("/", response_model=PaginatedLedgerOut)
def list_ledgers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    query = db.query(Ledger)
    if company_id is not None:
      query = query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    if search.strip():
        query = query.filter(Ledger.name.ilike(f"%{search.strip()}%"))
    total = query.count()
    items = (
        query.order_by(Ledger.name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedLedgerOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
    )


@router.get("/day-book", response_model=DayBookOut)
def get_day_book(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    fy_label: str | None = None
    financial_year_id: int | None = None
    if from_date is None or to_date is None:
        active_fy = get_active_fy(db, company_id=company_id)
        if active_fy is None:
            raise HTTPException(
                status_code=400,
                detail="No active financial year found. Please provide from_date and to_date, or activate a financial year.",
            )
        from_date = active_fy.start_date
        to_date = active_fy.end_date
        fy_label = active_fy.label
        financial_year_id = active_fy.id

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    day_book_data = _build_day_book_data(
      db,
      from_date=from_date,
      to_date=to_date,
      company_id=company_id,
    )

    return DayBookOut(
        from_date=from_date,
        to_date=to_date,
      total_debit=day_book_data.total_debit,
      total_credit=day_book_data.total_credit,
      entries=day_book_data.entries,
        fy_label=fy_label,
        financial_year_id=financial_year_id,
    )


@router.get("/day-book/pdf")
def download_day_book_pdf(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
  ):
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
      raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    company = active_company if company_id is not None else db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    currency = company.currency_code if company and company.currency_code else "INR"

    day_book_data = _build_day_book_data(
      db,
      from_date=from_date,
      to_date=to_date,
      company_id=company_id,
    )

    html = _build_day_book_html(
      company=company,
      from_date=from_date,
      to_date=to_date,
      entries=day_book_data.entries,
      total_debit=day_book_data.total_debit,
      total_credit=day_book_data.total_credit,
      currency=currency,
    )

    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    buf = BytesIO(pdf_bytes)
    filename = f"day_book_{from_date}_{to_date}.pdf"

    return StreamingResponse(
      buf,
      media_type="application/pdf",
      headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/day-book/csv")
def download_day_book_csv(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
  ):
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
      raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    day_book_data = _build_day_book_data(
      db,
      from_date=from_date,
      to_date=to_date,
      company_id=company_id,
    )

    csv_buffer = StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(["Date", "Voucher Type", "Reference", "Ledger", "Particulars", "Debit", "Credit"])

    for entry in day_book_data.entries:
      writer.writerow([
        entry.date.date().isoformat(),
        entry.voucher_type,
        entry.reference_number or "",
        entry.ledger_name,
        entry.particulars,
        f"{entry.debit:.2f}" if entry.debit > 0 else "",
        f"{entry.credit:.2f}" if entry.credit > 0 else "",
      ])

    writer.writerow([])
    writer.writerow(["", "", "", "", "Totals", f"{day_book_data.total_debit:.2f}", f"{day_book_data.total_credit:.2f}"])

    csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")
    filename = f"day_book_{from_date}_{to_date}.csv"

    return StreamingResponse(
      BytesIO(csv_bytes),
      media_type="text/csv; charset=utf-8",
      headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tax-ledger", response_model=TaxLedgerOut, include_in_schema=False)
@router.get("/tax-ledger/", response_model=TaxLedgerOut)
def get_tax_ledger(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    voucher_type: str | None = Query(None, pattern="^(sales|purchase)$"),
    gst_rate: float | None = Query(None, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    fy_label: str | None = None
    financial_year_id: int | None = None
    if from_date is None or to_date is None:
        active_fy = get_active_fy(db, company_id=company_id)
        if active_fy is None:
            raise HTTPException(
                status_code=400,
                detail="No active financial year found. Please provide from_date and to_date, or activate a financial year.",
            )
        from_date = active_fy.start_date
        to_date = active_fy.end_date
        fy_label = active_fy.label
        financial_year_id = active_fy.id

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    invoice_query = (
        db.query(
            Invoice.id.label("entry_id"),
            Invoice.invoice_date.label("entry_date"),
            Invoice.voucher_type.label("source_voucher_type"),
            Invoice.invoice_number.label("reference_number"),
            Invoice.ledger_name.label("ledger_name"),
            InvoiceItem.gst_rate.label("gst_rate"),
            func.coalesce(func.sum(InvoiceItem.taxable_amount), 0).label("taxable_amount"),
            func.coalesce(func.sum(InvoiceItem.cgst_amount), 0).label("cgst_amount"),
            func.coalesce(func.sum(InvoiceItem.sgst_amount), 0).label("sgst_amount"),
            func.coalesce(func.sum(InvoiceItem.igst_amount), 0).label("igst_amount"),
        )
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .filter(Invoice.status == "active")
        .filter(Invoice.invoice_date >= period_start)
        .filter(Invoice.invoice_date <= period_end)
    )
    if company_id is not None:
        invoice_query = invoice_query.filter(or_(Invoice.company_id == company_id, Invoice.company_id.is_(None)))

    if voucher_type is not None:
        invoice_query = invoice_query.filter(Invoice.voucher_type == voucher_type)
    if gst_rate is not None:
        invoice_query = invoice_query.filter(InvoiceItem.gst_rate == gst_rate)

    invoice_rows = (
        invoice_query
        .group_by(
            Invoice.id,
            Invoice.invoice_date,
            Invoice.voucher_type,
            Invoice.invoice_number,
            Invoice.ledger_name,
            InvoiceItem.gst_rate,
        )
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc(), InvoiceItem.gst_rate.asc())
        .all()
    )

    credit_note_query = (
        db.query(
            CreditNote.id.label("entry_id"),
            CreditNote.created_at.label("entry_date"),
            Invoice.voucher_type.label("source_voucher_type"),
            CreditNote.credit_note_number.label("reference_number"),
            Invoice.ledger_name.label("ledger_name"),
            CreditNoteItem.gst_rate.label("gst_rate"),
            func.coalesce(func.sum(CreditNoteItem.taxable_amount), 0).label("taxable_amount"),
        func.coalesce(
          func.sum(
            case(
              (func.coalesce(InvoiceItem.igst_amount, 0) > 0, 0),
              else_=CreditNoteItem.tax_amount / 2,
            )
          ),
          0,
        ).label("cgst_amount"),
        func.coalesce(
          func.sum(
            case(
              (func.coalesce(InvoiceItem.igst_amount, 0) > 0, 0),
              else_=CreditNoteItem.tax_amount / 2,
            )
          ),
          0,
        ).label("sgst_amount"),
        func.coalesce(
          func.sum(
            case(
              (func.coalesce(InvoiceItem.igst_amount, 0) > 0, CreditNoteItem.tax_amount),
              else_=0,
            )
          ),
          0,
        ).label("igst_amount"),
        )
        .join(CreditNoteItem, CreditNoteItem.credit_note_id == CreditNote.id)
        .join(Invoice, Invoice.id == CreditNoteItem.invoice_id)
      .outerjoin(InvoiceItem, InvoiceItem.id == CreditNoteItem.invoice_item_id)
        .filter(CreditNote.status == "active")
        .filter(CreditNote.created_at >= period_start)
        .filter(CreditNote.created_at <= period_end)
    )
    if company_id is not None:
      credit_note_query = credit_note_query.filter(or_(CreditNote.company_id == company_id, CreditNote.company_id.is_(None)))

    if voucher_type is not None:
        credit_note_query = credit_note_query.filter(Invoice.voucher_type == voucher_type)
    if gst_rate is not None:
        credit_note_query = credit_note_query.filter(CreditNoteItem.gst_rate == gst_rate)

    credit_note_rows = (
        credit_note_query
        .group_by(
            CreditNote.id,
            CreditNote.created_at,
            Invoice.voucher_type,
            CreditNote.credit_note_number,
            Invoice.ledger_name,
            CreditNoteItem.gst_rate,
        )
        .order_by(CreditNote.created_at.asc(), CreditNote.id.asc(), CreditNoteItem.gst_rate.asc())
        .all()
    )

    entries: list[TaxLedgerEntry] = []
    for row in invoice_rows:
        cgst_amount = float(row.cgst_amount or 0)
        sgst_amount = float(row.sgst_amount or 0)
        igst_amount = float(row.igst_amount or 0)
        total_tax = cgst_amount + sgst_amount + igst_amount

        is_sales = row.source_voucher_type == "sales"
        entries.append(TaxLedgerEntry(
            entry_id=row.entry_id,
            entry_type="invoice",
            date=row.entry_date,
            voucher_type=row.source_voucher_type.title(),
            source_voucher_type=row.source_voucher_type,
            reference_number=row.reference_number or f"INV-{row.entry_id}",
            ledger_name=row.ledger_name or "Unknown ledger",
            particulars=f"{row.source_voucher_type.title()} Invoice",
            gst_rate=float(row.gst_rate or 0),
            taxable_amount=float(row.taxable_amount or 0),
            debit_cgst=cgst_amount if is_sales else 0.0,
            debit_sgst=sgst_amount if is_sales else 0.0,
            debit_igst=igst_amount if is_sales else 0.0,
            debit_total_tax=total_tax if is_sales else 0.0,
            credit_cgst=0.0 if is_sales else cgst_amount,
            credit_sgst=0.0 if is_sales else sgst_amount,
            credit_igst=0.0 if is_sales else igst_amount,
            credit_total_tax=0.0 if is_sales else total_tax,
        ))

    for row in credit_note_rows:
        cgst_amount = float(row.cgst_amount or 0)
        sgst_amount = float(row.sgst_amount or 0)
        igst_amount = float(row.igst_amount or 0)
        total_tax = cgst_amount + sgst_amount + igst_amount

        source_is_sales = row.source_voucher_type == "sales"
        entries.append(TaxLedgerEntry(
            entry_id=row.entry_id,
            entry_type="credit_note",
            date=row.entry_date,
            voucher_type="Credit Note",
            source_voucher_type=row.source_voucher_type,
            reference_number=row.reference_number or f"CN-{row.entry_id}",
            ledger_name=row.ledger_name or "Unknown ledger",
            particulars=f"Credit Note against {row.source_voucher_type.title()} Invoice",
            gst_rate=float(row.gst_rate or 0),
            taxable_amount=float(row.taxable_amount or 0),
            debit_cgst=0.0 if source_is_sales else cgst_amount,
            debit_sgst=0.0 if source_is_sales else sgst_amount,
            debit_igst=0.0 if source_is_sales else igst_amount,
            debit_total_tax=0.0 if source_is_sales else total_tax,
            credit_cgst=cgst_amount if source_is_sales else 0.0,
            credit_sgst=sgst_amount if source_is_sales else 0.0,
            credit_igst=igst_amount if source_is_sales else 0.0,
            credit_total_tax=total_tax if source_is_sales else 0.0,
        ))

    entries.sort(key=lambda entry: (_make_aware(entry.date), entry.entry_id, entry.gst_rate))

    return TaxLedgerOut(
        from_date=from_date,
        to_date=to_date,
        voucher_type=voucher_type,
        gst_rate=gst_rate,
        entries=entries,
        totals=_build_tax_ledger_totals(entries),
        fy_label=fy_label,
        financial_year_id=financial_year_id,
    )


@router.get("/{ledger_id}", response_model=LedgerOut)
def get_ledger(
    ledger_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    query = db.query(Ledger).filter(Ledger.id == ledger_id)
    if company_id is not None:
        query = query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    ledger = query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")
    return _serialize_ledger(db, ledger, company_id=company_id)

@router.get("/{ledger_id}/unpaid-invoices", response_model=list[OutstandingInvoiceOut])
def list_unpaid_invoices(
    ledger_id: int,
    voucher_type: str = Query("receipt", pattern="^(receipt|payment)$"),
    amount: float | None = Query(None, gt=0),
    payment_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    ledger_query = db.query(Ledger).filter(Ledger.id == ledger_id)
    if company_id is not None:
      ledger_query = ledger_query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    ledger = ledger_query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    rows = get_outstanding_invoices_for_ledger(
        db,
        ledger_id,
        voucher_type=voucher_type,
        exclude_payment_id=payment_id,
        company_id=company_id,
    )
    suggestions = auto_allocate_outstanding_invoices(rows, amount) if amount is not None else {}

    return [
        OutstandingInvoiceOut(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            total_amount=float(invoice.total_amount or 0),
            paid_amount=summary.paid_amount,
            remaining_amount=summary.remaining_amount,
            outstanding_amount=summary.outstanding_amount,
            payment_status=summary.payment_status,
            due_in_days=summary.due_in_days,
            suggested_allocation_amount=suggestions.get(invoice.id),
        )
        for invoice, summary in rows
    ]


@router.put("/{ledger_id}", response_model=LedgerOut)
def update_ledger(
    ledger_id: int,
    payload: LedgerCreate,
    db: Session = Depends(get_db),
  current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
  active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    ledger_query = db.query(Ledger).filter(Ledger.id == ledger_id)
    if company_id is not None:
        ledger_query = ledger_query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    ledger = ledger_query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    gst = payload.gst
    if gst:
        gst_owner_query = db.query(Ledger).filter(Ledger.gst == gst, Ledger.id != ledger_id)
        if company_id is not None:
          gst_owner_query = gst_owner_query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
        gst_owner = gst_owner_query.first()
        if gst_owner:
            raise HTTPException(status_code=400, detail="Ledger with this GST already exists")

    ledger.name = payload.name.strip()
    ledger.address = payload.address.strip()
    ledger.gst = gst
    ledger.phone_number = payload.phone_number.strip()
    ledger.email = payload.email.strip() if payload.email else None
    ledger.website = payload.website.strip() if payload.website else None
    ledger.bank_name = payload.bank_name.strip() if payload.bank_name else None
    ledger.branch_name = payload.branch_name.strip() if payload.branch_name else None
    ledger.account_name = payload.account_name.strip() if payload.account_name else None
    ledger.account_number = payload.account_number.strip() if payload.account_number else None
    ledger.ifsc_code = payload.ifsc_code.strip().upper() if payload.ifsc_code else None
    _sync_opening_balance(db, ledger.id, payload.opening_balance, current_user.id, company_id=company_id)

    try:
      db.commit()
    except IntegrityError as exc:
      db.rollback()
      if "ix_buyers_gst" in str(exc.orig) or "buyers_gst_key" in str(exc.orig):
        raise HTTPException(
          status_code=400,
          detail="Buyer with this GST already exists. Run latest migrations to enable per-company GST uniqueness.",
        )
      raise
    db.refresh(ledger)
    return _serialize_ledger(db, ledger, company_id=company_id)


@router.delete("/{ledger_id}")
def delete_ledger(
    ledger_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    ledger_query = db.query(Ledger).filter(Ledger.id == ledger_id)
    if company_id is not None:
        ledger_query = ledger_query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    ledger = ledger_query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    has_invoices_query = db.query(Invoice.id).filter(Invoice.ledger_id == ledger_id)
    if company_id is not None:
        has_invoices_query = has_invoices_query.filter(or_(Invoice.company_id == company_id, Invoice.company_id.is_(None)))
    has_invoices = has_invoices_query.first()
    if has_invoices:
        raise HTTPException(status_code=400, detail="Cannot delete ledger linked to invoices")

    has_payments_query = db.query(Payment.id).filter(Payment.ledger_id == ledger_id)
    if company_id is not None:
        has_payments_query = has_payments_query.filter(or_(Payment.company_id == company_id, Payment.company_id.is_(None)))
    has_payments = has_payments_query.first()
    if has_payments:
        raise HTTPException(status_code=400, detail="Cannot delete ledger linked to payments")

    db.delete(ledger)
    db.commit()
    return {"message": "Ledger deleted"}


@router.get("/{ledger_id}/statement", response_model=LedgerStatementOut)
def get_ledger_statement(
    ledger_id: int,
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    fy_label: str | None = None
    financial_year_id: int | None = None
    if from_date is None or to_date is None:
        active_fy = get_active_fy(db, company_id=company_id)
        if active_fy is None:
            raise HTTPException(
                status_code=400,
                detail="No active financial year found. Please provide from_date and to_date, or activate a financial year.",
            )
        from_date = active_fy.start_date
        to_date = active_fy.end_date
        fy_label = active_fy.label
        financial_year_id = active_fy.id

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    ledger_query = db.query(Ledger).filter(Ledger.id == ledger_id)
    if company_id is not None:
      ledger_query = ledger_query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    ledger = ledger_query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    statement_data = _build_ledger_statement_data(db, ledger, from_date, to_date, company_id=company_id)

    return LedgerStatementOut(
        ledger=ledger,
        from_date=from_date,
        to_date=to_date,
        opening_balance=statement_data.opening_balance,
        period_debit=statement_data.period_debit,
        period_credit=statement_data.period_credit,
        closing_balance=statement_data.closing_balance,
        entries=statement_data.entries,
        fy_label=fy_label,
        financial_year_id=financial_year_id,
    )


# ---------------------------------------------------------------------------
# Ledger statement PDF
# ---------------------------------------------------------------------------

def _e(text: str | None) -> str:
    return escape(text or "")


def _fmt_inr(value: float, currency: str = "INR") -> str:
    try:
        if currency == "INR":
            # Indian grouping: 1,23,456.78
            neg = value < 0
            value = abs(value)
            integer_part = int(value)
            decimal_part = f"{value - integer_part:.2f}"[1:]  # ".xx"
            s = str(integer_part)
            if len(s) > 3:
                last3 = s[-3:]
                rest = s[:-3]
                groups = []
                while rest:
                    groups.append(rest[-2:])
                    rest = rest[:-2]
                groups.reverse()
                s = ",".join(groups) + "," + last3
            result = f"\u20b9{s}{decimal_part}"
            return f"-{result}" if neg else result
        else:
            return f"{value:,.2f} {currency}"
    except Exception:
        return f"{value:,.2f}"


def _build_day_book_html(
    company: CompanyProfile | None,
    from_date: date,
    to_date: date,
    entries: list[DayBookEntry],
    total_debit: float,
    total_credit: float,
    currency: str = "INR",
) -> str:
    entry_rows = ""
    for entry in entries:
        entry_date = entry.date.strftime("%d %b %Y") if entry.date else "N/A"
        dr = _fmt_inr(entry.debit, currency) if entry.debit > 0 else ""
        cr = _fmt_inr(entry.credit, currency) if entry.credit > 0 else ""
        reference = _e(entry.reference_number) if entry.reference_number else f"{_e(entry.voucher_type)} #{entry.entry_id}"
        entry_rows += f"""
        <tr>
          <td>{_e(entry_date)}</td>
          <td>{_e(entry.voucher_type)}</td>
          <td>{reference}</td>
          <td>{_e(entry.ledger_name)}</td>
          <td>{_e(entry.particulars)}</td>
          <td class=\"right\">{dr}</td>
          <td class=\"right\">{cr}</td>
        </tr>"""

    company_name = _e(company.name) if company else "Company"
    company_address = _e(company.address) if company else ""
    company_gst = f"GST: {_e(company.gst)}" if company and company.gst else ""
    company_phone = f"Phone: {_e(company.phone_number)}" if company and company.phone_number else ""
    company_details = " &middot; ".join(p for p in [company_gst, company_phone] if p)
    logo_url = _e(str(getattr(company, "logo_url", ""))) if company and getattr(company, "logo_url", None) else ""
    logo_markup = f'<img src="{logo_url}" alt="Company logo" class="company-logo" />' if logo_url else '<div class="logo-slot">Logo</div>'

    closing_balance = total_debit - total_credit

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\">
<style>
  @page {{
    size: A4;
    margin: 15mm 18mm;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 10px;
    color: #1f2937;
    line-height: 1.45;
  }}
  .eyebrow {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .sheet {{ width: 100%; }}
  .sheet__header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    padding-bottom: 14px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 14px;
  }}
  .sheet__company {{
    display: flex;
    gap: 10px;
    align-items: flex-start;
  }}
  .company-logo,
  .logo-slot {{
    width: 56px;
    height: 56px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 8px;
    color: #9ca3af;
    object-fit: contain;
    background: #f9fafb;
  }}
  .sheet__header h3 {{
    font-size: 15px;
    font-weight: 700;
    margin-bottom: 3px;
  }}
  .sheet__header p {{
    font-size: 9px;
    color: #6b7280;
    margin-bottom: 1px;
  }}
  .sheet__meta {{ text-align: right; }}
  .sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #1a56db;
    background: #eff6ff;
    margin-bottom: 6px;
  }}
  .summary {{
    display: flex;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 14px;
  }}
  .summary-item {{
    flex: 1;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 10px 12px;
    text-align: center;
  }}
  .summary-item .label {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .summary-item .value {{
    font-size: 13px;
    font-weight: 700;
    color: #1f2937;
  }}
  .summary-item.highlight .value {{
    color: #1a56db;
    font-size: 15px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 14px;
    font-size: 9px;
  }}
  thead th {{
    background: #f3f4f6;
    color: #374151;
    font-weight: 600;
    font-size: 8px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 7px 8px;
    border-bottom: 2px solid #d1d5db;
    text-align: left;
  }}
  thead th.right {{ text-align: right; }}
  tbody td {{
    padding: 6px 8px;
    border-bottom: 1px solid #e5e7eb;
    vertical-align: top;
  }}
  tbody td.right {{ text-align: right; }}
  tbody tr:last-child td {{ border-bottom: 2px solid #d1d5db; }}
  .footer {{
    margin-top: 8px;
    text-align: right;
  }}
  .footer .total-label {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .footer .total-value {{
    font-size: 18px;
    font-weight: 700;
    color: #1a56db;
  }}
  .muted {{ font-size: 8px; color: #9ca3af; }}
</style>
</head>
<body>
<div class=\"sheet\">
  <header class=\"sheet__header\">
    <div class=\"sheet__company\">
      {logo_markup}
      <div>
        <p class=\"eyebrow\">Issued by</p>
        <h3>{company_name}</h3>
        <p>{company_address}</p>
        <p>{company_details}</p>
      </div>
    </div>
    <div class=\"sheet__meta\">
      <span class=\"badge\">Day Book</span>
      <h2>{from_date.strftime('%d %b %Y')} &ndash; {to_date.strftime('%d %b %Y')}</h2>
      <p>{len(entries)} voucher entries</p>
    </div>
  </header>

  <section class=\"summary\">
    <div class=\"summary-item\">
      <p class=\"label\">Total Debit</p>
      <p class=\"value\">{_fmt_inr(total_debit, currency)}</p>
    </div>
    <div class=\"summary-item\">
      <p class=\"label\">Total Credit</p>
      <p class=\"value\">{_fmt_inr(total_credit, currency)}</p>
    </div>
    <div class=\"summary-item highlight\">
      <p class=\"label\">Net Movement</p>
      <p class=\"value\">{_fmt_inr(closing_balance, currency)}</p>
    </div>
  </section>

  <section>
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Voucher</th>
          <th>Reference</th>
          <th>Ledger</th>
          <th>Particulars</th>
          <th class=\"right\">Debit</th>
          <th class=\"right\">Credit</th>
        </tr>
      </thead>
      <tbody>
        {entry_rows if entry_rows else '<tr><td colspan="7" style="text-align:center;color:#9ca3af;">No entries in this period</td></tr>'}
      </tbody>
    </table>
  </section>

  <section class=\"footer\">
    <p class=\"total-label\">Net Movement</p>
    <p class=\"total-value\">{_fmt_inr(closing_balance, currency)}</p>
    <p class=\"muted\">Generated on {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}</p>
  </section>
</div>
</body>
</html>"""
    return html


def _build_statement_html(
    ledger: Ledger,
    company: CompanyProfile | None,
    from_date: date,
    to_date: date,
    opening_balance: float,
    period_debit: float,
    period_credit: float,
    closing_balance: float,
    entries: list[LedgerStatementEntry],
    currency: str = "INR",
) -> str:
    entry_rows = ""
    for entry in entries:
        entry_date = entry.date.strftime("%d %b %Y") if entry.date else "N/A"
        dr = _fmt_inr(entry.debit, currency) if entry.debit > 0 else ""
        cr = _fmt_inr(entry.credit, currency) if entry.credit > 0 else ""
        vtype = _e(entry.voucher_type)
        ref_number = _e(entry.reference_number) if entry.reference_number else f"#{entry.entry_id}"
        entry_rows += f"""
        <tr>
          <td>{_e(entry_date)}</td>
          <td>{ref_number}</td>
          <td>{_e(entry.particulars)}</td>
          <td class="right">{dr}</td>
          <td class="right">{cr}</td>
        </tr>"""

    company_name = _e(company.name) if company else "Company"
    company_address = _e(company.address) if company else ""
    company_gst = f"GST: {_e(company.gst)}" if company and company.gst else ""
    company_phone = f"Phone: {_e(company.phone_number)}" if company and company.phone_number else ""
    company_details = " &middot; ".join(p for p in [company_gst, company_phone] if p)
    ledger_gst = f"GST: {_e(ledger.gst)}" if ledger.gst else ""
    ledger_phone = f"Phone: {_e(ledger.phone_number)}" if ledger.phone_number else ""
    ledger_details = " &middot; ".join(p for p in [ledger_gst, ledger_phone] if p)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: A4;
    margin: 15mm 18mm;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 10px;
    color: #1f2937;
    line-height: 1.5;
  }}
  .eyebrow {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .sheet {{ width: 100%; }}
  .sheet__header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 16px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 16px;
  }}
  .sheet__header h3 {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .sheet__header p {{
    font-size: 9px;
    color: #6b7280;
    margin-bottom: 1px;
  }}
  .sheet__meta {{
    text-align: right;
  }}
  .sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .sheet__meta p {{
    font-size: 9px;
    color: #6b7280;
  }}
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #1a56db;
    background: #eff6ff;
    margin-bottom: 6px;
  }}
  .ledger-info {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 16px;
  }}
  .ledger-info h4 {{
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 2px;
  }}
  .ledger-info p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .summary {{
    display: flex;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
  }}
  .summary-item {{
    flex: 1;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 10px 12px;
    text-align: center;
  }}
  .summary-item .label {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .summary-item .value {{
    font-size: 13px;
    font-weight: 700;
    color: #1f2937;
  }}
  .summary-item.highlight .value {{
    color: #1a56db;
    font-size: 15px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 16px;
    font-size: 9px;
  }}
  thead th {{
    background: #f3f4f6;
    color: #374151;
    font-weight: 600;
    font-size: 8px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 7px 8px;
    border-bottom: 2px solid #d1d5db;
    text-align: left;
  }}
  thead th.right {{ text-align: right; }}
  tbody td {{
    padding: 6px 8px;
    border-bottom: 1px solid #e5e7eb;
    vertical-align: middle;
  }}
  tbody td.right {{ text-align: right; }}
  tbody tr:last-child td {{
    border-bottom: 2px solid #d1d5db;
  }}
  .footer {{
    margin-top: 8px;
    text-align: right;
  }}
  .footer .total-label {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .footer .total-value {{
    font-size: 20px;
    font-weight: 700;
    color: #1a56db;
  }}
  .muted {{ font-size: 8px; color: #9ca3af; }}
</style>
</head>
<body>
<div class="sheet">
  <header class="sheet__header">
    <div>
      <p class="eyebrow">Issued by</p>
      <h3>{company_name}</h3>
      <p>{company_address}</p>
      <p>{company_details}</p>
    </div>
    <div class="sheet__meta">
      <span class="badge">Ledger Statement</span>
      <h2>{_e(ledger.name)}</h2>
      <p>{from_date.strftime('%d %b %Y')} &ndash; {to_date.strftime('%d %b %Y')}</p>
    </div>
  </header>

  <section class="ledger-info">
    <p class="eyebrow">Ledger</p>
    <h4>{_e(ledger.name)}</h4>
    <p>{_e(ledger.address)}</p>
    <p>{ledger_details}</p>
  </section>

  <section class="summary">
    <div class="summary-item">
      <p class="label">Opening Balance</p>
      <p class="value">{_fmt_inr(opening_balance, currency)}</p>
    </div>
    <div class="summary-item">
      <p class="label">Period Debit</p>
      <p class="value">{_fmt_inr(period_debit, currency)}</p>
    </div>
    <div class="summary-item">
      <p class="label">Period Credit</p>
      <p class="value">{_fmt_inr(period_credit, currency)}</p>
    </div>
    <div class="summary-item highlight">
      <p class="label">Closing Balance</p>
      <p class="value">{_fmt_inr(closing_balance, currency)}</p>
    </div>
  </section>

  <section>
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Voucher</th>
          <th>Particulars</th>
          <th class="right">Debit</th>
          <th class="right">Credit</th>
        </tr>
      </thead>
      <tbody>
        {entry_rows if entry_rows else '<tr><td colspan="5" style="text-align:center;color:#9ca3af;">No entries in this period</td></tr>'}
      </tbody>
    </table>
  </section>

  <section class="footer">
    <p class="total-label">Closing Balance</p>
    <p class="total-value">{_fmt_inr(closing_balance, currency)}</p>
    <p class="muted">Generated on {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}</p>
  </section>
</div>
</body>
</html>"""
    return html


@router.get("/{ledger_id}/statement/pdf")
def download_ledger_statement_pdf(
    ledger_id: int,
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    ledger_query = db.query(Ledger).filter(Ledger.id == ledger_id)
    if company_id is not None:
        ledger_query = ledger_query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    ledger = ledger_query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    company = active_company if company_id is not None else db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    currency = company.currency_code if company and company.currency_code else "INR"

    statement_data = _build_ledger_statement_data(db, ledger, from_date, to_date, company_id=company_id)

    html = _build_statement_html(
        ledger=ledger,
        company=company,
        from_date=from_date,
        to_date=to_date,
        opening_balance=statement_data.opening_balance,
        period_debit=statement_data.period_debit,
        period_credit=statement_data.period_credit,
        closing_balance=statement_data.closing_balance,
        entries=statement_data.entries,
        currency=currency,
    )

    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    buf = BytesIO(pdf_bytes)
    safe_name = ledger.name.replace(" ", "_").replace("/", "_")[:30]
    filename = f"statement_{safe_name}_{from_date}_{to_date}.pdf"

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )