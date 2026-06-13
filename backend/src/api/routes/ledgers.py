import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
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
from src.models.ledger_address import LedgerAddress
from src.models.payment import Payment, PaymentInvoiceAllocation
from src.models.user import User, UserRole
from src.schemas.invoice import OutstandingInvoiceOut
from src.schemas.ledger import DayBookEntry, DayBookOut, Gstr1B2BInvoice, Gstr1CategorySummary, Gstr1DocSummary, Gstr1HsnSummaryItem, Gstr1JsonExport, Gstr1Summary, Gstr1ValidationError, Gstr1ValidationResult, LedgerCreate, LedgerOut, LedgerStatementEntry, LedgerStatementInvoiceAllocation, LedgerStatementOut, PaginatedLedgerOut, TaxLedgerEntry, TaxLedgerOut, TaxLedgerTotals
from src.schemas.ledger_address import LedgerAddressCreate, LedgerAddressOut, LedgerAddressUpdate
from src.services.credit_note_reporting import get_credit_note_ledger_summary
from src.services.financial_year import get_active_fy
from src.services.invoice_payments import auto_allocate_outstanding_invoices, build_invoice_payment_summaries, get_outstanding_invoices_for_ledger
from src.services.pdf_templates import _build_day_book_html, _build_statement_html
from src.services.pdf_templates.builders import _e
from src.core.validation import GSTIN_REGEX, HSN_SAC_REGEX

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
            Invoice.ledger_gst.label("ledger_gst"),
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
            Invoice.ledger_gst,
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
            Invoice.ledger_gst.label("ledger_gst"),
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
            Invoice.ledger_gst,
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
            ledger_gst=row.ledger_gst,
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
            ledger_gst=row.ledger_gst,
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


# ---------------------------------------------------------------------------
# Ledger address endpoints
# ---------------------------------------------------------------------------

def _get_ledger_or_404(db: Session, ledger_id: int, company_id: int | None) -> Ledger:
    query = db.query(Ledger).filter(Ledger.id == ledger_id)
    if company_id is not None:
        query = query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    ledger = query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")
    return ledger


@router.get("/{ledger_id}/addresses/", response_model=list[LedgerAddressOut])
def list_ledger_addresses(
    ledger_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """List all saved addresses for a ledger."""
    company_id = active_company.id
    _get_ledger_or_404(db, ledger_id, company_id)
    return (
        db.query(LedgerAddress)
        .filter(LedgerAddress.ledger_id == ledger_id, LedgerAddress.company_id == company_id)
        .order_by(LedgerAddress.is_default.desc(), LedgerAddress.created_at.asc())
        .all()
    )


@router.post("/{ledger_id}/addresses/", response_model=LedgerAddressOut, status_code=201)
def create_ledger_address(
    ledger_id: int,
    payload: LedgerAddressCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Create a new saved address for a ledger."""
    company_id = active_company.id
    _get_ledger_or_404(db, ledger_id, company_id)
    addr = LedgerAddress(
        ledger_id=ledger_id,
        company_id=company_id,
        label=payload.label,
        address=payload.address,
        is_default=payload.is_default,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


@router.put("/{ledger_id}/addresses/{address_id}", response_model=LedgerAddressOut)
def update_ledger_address(
    ledger_id: int,
    address_id: int,
    payload: LedgerAddressUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Update a saved ledger address."""
    company_id = active_company.id
    _get_ledger_or_404(db, ledger_id, company_id)
    addr = db.query(LedgerAddress).filter(
        LedgerAddress.id == address_id,
        LedgerAddress.ledger_id == ledger_id,
        LedgerAddress.company_id == company_id,
    ).first()
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")
    if payload.label is not None:
        addr.label = payload.label
    if payload.address is not None:
        addr.address = payload.address
    if payload.is_default is not None:
        addr.is_default = payload.is_default
    db.commit()
    db.refresh(addr)
    return addr


@router.delete("/{ledger_id}/addresses/{address_id}", status_code=204)
def delete_ledger_address(
    ledger_id: int,
    address_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Delete a saved ledger address."""
    company_id = active_company.id
    _get_ledger_or_404(db, ledger_id, company_id)
    addr = db.query(LedgerAddress).filter(
        LedgerAddress.id == address_id,
        LedgerAddress.ledger_id == ledger_id,
        LedgerAddress.company_id == company_id,
    ).first()
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")
    db.delete(addr)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Tax Ledger CSV & PDF Exports
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/tax-ledger/csv")
def download_tax_ledger_csv(
    from_date: date = Query(...),
    to_date: date = Query(...),
    voucher_type: str | None = Query(None, pattern="^(sales|purchase)$"),
    gst_rate: float | None = Query(None, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    result = _build_full_tax_ledger(db, from_date, to_date, voucher_type, gst_rate, company_id)

    csv_buffer = StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow([
        "Date", "Voucher Number", "Voucher Type", "Party Name", "GSTIN",
        "Taxable Value", "CGST", "SGST", "IGST", "CESS", "Total Amount",
    ])

    for entry in result.entries:
        total_amount = entry.taxable_amount + entry.debit_cgst + entry.debit_sgst + entry.debit_igst + \
            entry.credit_cgst + entry.credit_sgst + entry.credit_igst
        writer.writerow([
            entry.date.date().isoformat(),
            entry.reference_number,
            entry.voucher_type,
            entry.ledger_name,
            entry.ledger_gst or "",
            f"{entry.taxable_amount:.2f}",
            f"{entry.debit_cgst + entry.credit_cgst:.2f}",
            f"{entry.debit_sgst + entry.credit_sgst:.2f}",
            f"{entry.debit_igst + entry.credit_igst:.2f}",
            "0.00",
            f"{total_amount:.2f}",
        ])

    csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")
    filename = f"tax_ledger_{from_date}_{to_date}.csv"

    return StreamingResponse(
        BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tax-ledger/pdf")
def download_tax_ledger_pdf(
    from_date: date = Query(...),
    to_date: date = Query(...),
    voucher_type: str | None = Query(None, pattern="^(sales|purchase)$"),
    gst_rate: float | None = Query(None, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    company = active_company if company_id is not None else db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    currency = company.currency_code if company and company.currency_code else "INR"
    result = _build_full_tax_ledger(db, from_date, to_date, voucher_type, gst_rate, company_id)
    totals = _build_tax_ledger_totals(result.entries)

    html = _build_tax_ledger_pdf_html(
        company=company,
        from_date=from_date,
        to_date=to_date,
        entries=result.entries,
        totals=totals,
        currency=currency,
    )

    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    buf = BytesIO(pdf_bytes)
    filename = f"tax_ledger_{from_date}_{to_date}.pdf"

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_full_tax_ledger(
    db: Session,
    from_date: date,
    to_date: date,
    voucher_type: str | None,
    gst_rate: float | None,
    company_id: int | None,
) -> TaxLedgerOut:
    """Shared builder for tax ledger data used by CSV/PDF endpoints."""
    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    invoice_query = (
        db.query(
            Invoice.id.label("entry_id"),
            Invoice.invoice_date.label("entry_date"),
            Invoice.voucher_type.label("source_voucher_type"),
            Invoice.invoice_number.label("reference_number"),
            Invoice.ledger_name.label("ledger_name"),
            Invoice.ledger_gst.label("ledger_gst"),
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
        .group_by(Invoice.id, Invoice.invoice_date, Invoice.voucher_type,
                  Invoice.invoice_number, Invoice.ledger_name, Invoice.ledger_gst,
                  InvoiceItem.gst_rate)
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc(), InvoiceItem.gst_rate.asc())
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
            ledger_gst=row.ledger_gst,
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

    # Credit notes
    cn_query = (
        db.query(
            CreditNote.id.label("entry_id"),
            CreditNote.created_at.label("entry_date"),
            Invoice.voucher_type.label("source_voucher_type"),
            CreditNote.credit_note_number.label("reference_number"),
            Invoice.ledger_name.label("ledger_name"),
            Invoice.ledger_gst.label("ledger_gst"),
            CreditNoteItem.gst_rate.label("gst_rate"),
            func.coalesce(func.sum(CreditNoteItem.taxable_amount), 0).label("taxable_amount"),
            func.coalesce(func.sum(case((func.coalesce(InvoiceItem.igst_amount, 0) > 0, 0), else_=CreditNoteItem.tax_amount / 2)), 0).label("cgst_amount"),
            func.coalesce(func.sum(case((func.coalesce(InvoiceItem.igst_amount, 0) > 0, 0), else_=CreditNoteItem.tax_amount / 2)), 0).label("sgst_amount"),
            func.coalesce(func.sum(case((func.coalesce(InvoiceItem.igst_amount, 0) > 0, CreditNoteItem.tax_amount), else_=0)), 0).label("igst_amount"),
        )
        .join(CreditNoteItem, CreditNoteItem.credit_note_id == CreditNote.id)
        .join(Invoice, Invoice.id == CreditNoteItem.invoice_id)
        .outerjoin(InvoiceItem, InvoiceItem.id == CreditNoteItem.invoice_item_id)
        .filter(CreditNote.status == "active")
        .filter(CreditNote.created_at >= period_start)
        .filter(CreditNote.created_at <= period_end)
    )
    if company_id is not None:
        cn_query = cn_query.filter(or_(CreditNote.company_id == company_id, CreditNote.company_id.is_(None)))
    if voucher_type is not None:
        cn_query = cn_query.filter(Invoice.voucher_type == voucher_type)
    if gst_rate is not None:
        cn_query = cn_query.filter(CreditNoteItem.gst_rate == gst_rate)

    cn_rows = (
        cn_query
        .group_by(CreditNote.id, CreditNote.created_at, Invoice.voucher_type,
                  CreditNote.credit_note_number, Invoice.ledger_name,
                  Invoice.ledger_gst, CreditNoteItem.gst_rate)
        .order_by(CreditNote.created_at.asc(), CreditNote.id.asc(), CreditNoteItem.gst_rate.asc())
        .all()
    )

    for row in cn_rows:
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
            ledger_gst=row.ledger_gst,
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
        from_date=from_date, to_date=to_date,
        voucher_type=voucher_type, gst_rate=gst_rate,
        entries=entries, totals=_build_tax_ledger_totals(entries),
    )


def _build_tax_ledger_pdf_html(
    *,
    company,
    from_date: date,
    to_date: date,
    entries: list[TaxLedgerEntry],
    totals: TaxLedgerTotals,
    currency: str,
) -> str:
    rows_html = ""
    for entry in entries:
        cgst = entry.debit_cgst + entry.credit_cgst
        sgst = entry.debit_sgst + entry.credit_sgst
        igst = entry.debit_igst + entry.credit_igst
        rows_html += f"""
        <tr>
            <td>{entry.date.date().isoformat()}</td>
            <td>{_e(entry.reference_number)}</td>
            <td>{_e(entry.ledger_name)}</td>
            <td>{_e(entry.ledger_gst or '')}</td>
            <td>{entry.gst_rate:.0f}%</td>
            <td style="text-align:right">₹{entry.taxable_amount:,.2f}</td>
            <td style="text-align:right">₹{cgst:,.2f}</td>
            <td style="text-align:right">₹{sgst:,.2f}</td>
            <td style="text-align:right">₹{igst:,.2f}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
    body {{ font-family: Arial, sans-serif; font-size: 11px; margin: 24px; }}
    h1 {{ font-size: 18px; margin-bottom: 4px; }}
    .meta {{ color: #555; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 5px 8px; font-size: 10px; }}
    th {{ background: #f5f5f5; text-align: left; }}
    .totals {{ margin-top: 16px; }}
    .totals table {{ width: 60%; }}
</style></head><body>
<h1>Tax Ledger</h1>
<p class="meta">
    {_e(company.name if company else '')} &mdash;
    {from_date} to {to_date} &mdash; Currency: {currency}
</p>
<table>
    <thead><tr>
        <th>Date</th><th>Voucher No.</th><th>Party</th><th>GSTIN</th>
        <th>Rate</th><th>Taxable</th><th>CGST</th><th>SGST</th><th>IGST</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
</table>
<div class="totals">
    <table>
        <tr><th>Net CGST</th><td>₹{totals.net_cgst:,.2f}</td></tr>
        <tr><th>Net SGST</th><td>₹{totals.net_sgst:,.2f}</td></tr>
        <tr><th>Net IGST</th><td>₹{totals.net_igst:,.2f}</td></tr>
        <tr><th>Net Total Tax</th><td>₹{totals.net_total_tax:,.2f}</td></tr>
    </table>
</div>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════
#  GSTR-1 Filing Endpoints
# ═══════════════════════════════════════════════════════════════════════════


def _derive_place_of_supply(company_gst: str | None) -> str:
    """Derive place of supply state code from a GSTIN (first 2 digits).

    For GSTR-1:
    - B2B: POS should be the customer's state code (ctin[:2])
    - B2CL/B2CS: POS is state of supply (use company state code as fallback)
    """
    if company_gst and len(company_gst) >= 2 and company_gst[:2].isdigit():
        return company_gst[:2]
    return "00"


def _validate_gstin(gstin: str | None) -> str | None:
    """Validate GSTIN format. Returns error message or None."""
    if not gstin or not gstin.strip():
        return "Missing GSTIN"
    gstin = gstin.strip().upper()
    if not GSTIN_REGEX.fullmatch(gstin):
        return f"Invalid GSTIN format: {gstin}"
    return None


def _validate_hsn(hsn: str | None) -> str | None:
    """Validate HSN/SAC code. Returns error message or None."""
    if not hsn or not hsn.strip():
        return "Missing HSN"
    hsn = hsn.strip()
    if not HSN_SAC_REGEX.fullmatch(hsn):
        return f"Invalid HSN: {hsn}"
    return None


def _validate_gstr1_export(db: Session, company_gstin: str | None, invoices: list[Invoice]) -> list[str]:
    """Validate GSTR-1 data before JSON/CSV export.

    Returns a list of error messages. If empty, validation passed.
    """
    errors: list[str] = []

    # 1. Company GSTIN must be set and valid
    if not company_gstin or not company_gstin.strip():
        errors.append("Company GSTIN is required to generate GSTR-1 export. Please set your company GSTIN in Settings.")
    elif not GSTIN_REGEX.fullmatch(company_gstin.strip().upper()):
        errors.append(f"Company GSTIN '{company_gstin}' is invalid. Please set a valid 15-character GSTIN in Settings.")

    # 2. Company POS must not be "00"
    company_pos = _derive_place_of_supply(company_gstin)
    if company_pos == "00":
        errors.append("Cannot determine Place of Supply from company GSTIN. Please set a valid company GSTIN in Settings.")

    # 3. Check each invoice
    seen_numbers: set[str] = set()
    for inv in invoices:
        if inv.voucher_type != "sales":
            continue

        inv_num = inv.invoice_number or f"INV-{inv.id}"
        ctin = (inv.ledger_gst or "").strip().upper()

        # B2B: customer GSTIN must be valid and POS must be valid
        if ctin:
            if not GSTIN_REGEX.fullmatch(ctin):
                errors.append(f"Invoice {inv_num}: Customer GSTIN '{ctin}' is not a valid 15-character GSTIN.")
            else:
                pos = ctin[:2]
                if pos == "00" or not pos.isdigit():
                    errors.append(f"Invoice {inv_num}: Cannot derive valid Place of Supply from customer GSTIN '{ctin}'.")

        # Check for HSN codes
        missing_hsn = [item for item in inv.items if not item.hsn_sac or not item.hsn_sac.strip()]
        if missing_hsn:
            item_ids = ", ".join(str(item.id) for item in missing_hsn)
            errors.append(f"Invoice {inv_num}: Missing HSN/SAC code for item(s) #{item_ids}.")

        # Check for duplicate invoice numbers
        if inv_num in seen_numbers:
            errors.append(f"Invoice {inv_num}: Duplicate invoice number detected.")
        else:
            seen_numbers.add(inv_num)

    return errors


def _gstr1_invoice_query(db: Session, from_date: date, to_date: date, company_id: int | None):
    """Return active invoices in the date range with items eagerly loaded."""
    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)
    query = (
        db.query(Invoice)
        .options(joinedload(Invoice.items))
        .filter(Invoice.status == "active")
        .filter(Invoice.invoice_date >= period_start)
        .filter(Invoice.invoice_date <= period_end)
    )
    if company_id is not None:
        query = query.filter(or_(Invoice.company_id == company_id, Invoice.company_id.is_(None)))
    return query.order_by(Invoice.invoice_date.asc()).all()


@router.get("/tax-ledger/gstr1/validate", response_model=Gstr1ValidationResult)
def gstr1_validate(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Validate GSTR-1 data for the given period."""
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    invoices = _gstr1_invoice_query(db, from_date, to_date, company_id)
    errors: list[Gstr1ValidationError] = []
    seen_numbers: dict[str, list[int]] = {}

    for inv in invoices:
        inv_num = inv.invoice_number or f"INV-{inv.id}"

        # Track for duplicates
        seen_numbers.setdefault(inv_num, []).append(inv.id)

        # GSTIN validation
        gstin_err = _validate_gstin(inv.ledger_gst)
        if gstin_err:
            errors.append(Gstr1ValidationError(
                invoice_number=inv_num, field="GSTIN", message=gstin_err, severity="error",
            ))

        # Taxable value check
        if inv.taxable_amount is None or float(inv.taxable_amount) <= 0:
            errors.append(Gstr1ValidationError(
                invoice_number=inv_num, field="Taxable Value",
                message="Missing or zero taxable value", severity="error",
            ))

        # HSN checks
        for item in inv.items:
            hsn_err = _validate_hsn(item.hsn_sac)
            if hsn_err:
                errors.append(Gstr1ValidationError(
                    invoice_number=inv_num,
                    field=f"HSN (item #{item.id})",
                    message=hsn_err,
                    severity="error",
                ))

        # Tax calculation checks: CGST+SGST or IGST
        total_item_tax = sum(
            (float(item.cgst_amount or 0) + float(item.sgst_amount or 0) + float(item.igst_amount or 0))
            for item in inv.items
        )
        expected_tax = float(inv.total_tax_amount or 0)
        if total_item_tax > 0 and abs(total_item_tax - expected_tax) > 0.01:
            errors.append(Gstr1ValidationError(
                invoice_number=inv_num, field="Tax Calculation",
                message=f"Item tax sum ({total_item_tax:.2f}) ≠ invoice tax total ({expected_tax:.2f})",
                severity="error",
            ))

        # Place of supply (derived from company GST)
        pos = _derive_place_of_supply(inv.company_gst)
        if pos == "00":
            errors.append(Gstr1ValidationError(
                invoice_number=inv_num, field="Place of Supply",
                message="Cannot determine Place of Supply from company GSTIN",
                severity="warning",
            ))

    # Duplicate invoice numbers
    for num, ids in seen_numbers.items():
        if len(ids) > 1:
            errors.append(Gstr1ValidationError(
                invoice_number=num, field="Invoice Number",
                message=f"Duplicate invoice number: {num}", severity="error",
            ))

    invalid_set = {e.invoice_number for e in errors if e.severity == "error"}
    return Gstr1ValidationResult(
        status="valid" if len(invalid_set) == 0 else "invalid",
        errors=errors,
        total_invoices=len(invoices),
        valid_invoices=len(invoices) - len(invalid_set),
        invalid_invoices=len(invalid_set),
    )


@router.get("/tax-ledger/gstr1/summary", response_model=Gstr1Summary)
def gstr1_summary(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """GSTR-1 filing summary."""
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    invoices = _gstr1_invoice_query(db, from_date, to_date, company_id)
    company_gstin = active_company.gst if active_company else None

    b2b = Gstr1CategorySummary()
    b2cl = Gstr1CategorySummary()
    b2cs = Gstr1CategorySummary()
    nil_rated = Gstr1CategorySummary()
    exempt = Gstr1CategorySummary()

    credit_note_q = (
        db.query(CreditNote)
        .options(joinedload(CreditNote.items))
        .filter(CreditNote.status == "active")
        .filter(CreditNote.created_at >= datetime.combine(from_date, time.min))
        .filter(CreditNote.created_at <= datetime.combine(to_date, time.max))
    )
    if company_id is not None:
        credit_note_q = credit_note_q.filter(or_(CreditNote.company_id == company_id, CreditNote.company_id.is_(None)))
    credit_notes = credit_note_q.all()

    cn_summary = Gstr1CategorySummary()
    dn_summary = Gstr1CategorySummary()

    for inv in invoices:
        taxable = float(inv.taxable_amount or 0)
        cgst = float(inv.cgst_amount or 0)
        sgst = float(inv.sgst_amount or 0)
        igst = float(inv.igst_amount or 0)
        gstin = inv.ledger_gst

        if inv.voucher_type != "sales":
            continue

        if gstin and gstin.strip():
            b2b.invoice_count += 1
            b2b.taxable_value += taxable
            b2b.cgst += cgst
            b2b.sgst += sgst
            b2b.igst += igst
            b2b.total_tax += cgst + sgst + igst
        elif taxable > 250000:
            b2cl.invoice_count += 1
            b2cl.taxable_value += taxable
            b2cl.cgst += cgst
            b2cl.sgst += sgst
            b2cl.igst += igst
            b2cl.total_tax += cgst + sgst + igst
        elif taxable > 0:
            if cgst + sgst + igst == 0:
                nil_rated.invoice_count += 1
                nil_rated.taxable_value += taxable
            else:
                b2cs.invoice_count += 1
                b2cs.taxable_value += taxable
                b2cs.cgst += cgst
                b2cs.sgst += sgst
                b2cs.igst += igst
                b2cs.total_tax += cgst + sgst + igst

    for cn in credit_notes:
        cn_taxable = float(cn.taxable_amount or 0)
        cn_cgst = float(cn.cgst_amount or 0)
        cn_sgst = float(cn.sgst_amount or 0)
        cn_igst = float(cn.igst_amount or 0)
        if cn.credit_note_type == "return":
            cn_summary.invoice_count += 1
            cn_summary.taxable_value += cn_taxable
            cn_summary.cgst += cn_cgst
            cn_summary.sgst += cn_sgst
            cn_summary.igst += cn_igst
            cn_summary.total_tax += cn_cgst + cn_sgst + cn_igst
        else:
            dn_summary.invoice_count += 1
            dn_summary.taxable_value += cn_taxable
            dn_summary.cgst += cn_cgst
            dn_summary.sgst += cn_sgst
            dn_summary.igst += cn_igst
            dn_summary.total_tax += cn_cgst + cn_sgst + cn_igst

    # HSN summary
    hsn_map: dict[str, dict] = {}
    for inv in invoices:
        if inv.voucher_type != "sales":
            continue
        for item in inv.items:
            hsn = item.hsn_sac or "----"
            if hsn not in hsn_map:
                hsn_map[hsn] = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "qty": 0.0}
            hsn_map[hsn]["taxable"] += float(item.taxable_amount or 0)
            hsn_map[hsn]["cgst"] += float(item.cgst_amount or 0)
            hsn_map[hsn]["sgst"] += float(item.sgst_amount or 0)
            hsn_map[hsn]["igst"] += float(item.igst_amount or 0)
            hsn_map[hsn]["qty"] += float(item.quantity or 0)

    hsn_items: list[Gstr1HsnSummaryItem] = []
    for hsn, data in sorted(hsn_map.items()):
        hsn_items.append(Gstr1HsnSummaryItem(
            hsn_code=hsn,
            quantity=data["qty"],
            taxable_value=data["taxable"],
            cgst=data["cgst"],
            sgst=data["sgst"],
            igst=data["igst"],
            total_tax=data["cgst"] + data["sgst"] + data["igst"],
        ))

    total_sales = sum(1 for inv in invoices if inv.voucher_type == "sales")
    doc_summary = Gstr1DocSummary(
        total_invoices=total_sales,
        total_credit_notes=sum(1 for cn in credit_notes if cn.credit_note_type == "return"),
        total_debit_notes=sum(1 for cn in credit_notes if cn.credit_note_type != "return"),
    )

    return Gstr1Summary(
        from_date=from_date,
        to_date=to_date,
        gstin=company_gstin,
        b2b=b2b,
        b2cl=b2cl,
        b2cs=b2cs,
        credit_notes=cn_summary,
        debit_notes=dn_summary,
        nil_rated=nil_rated,
        exempt=exempt,
        hsn_summary=hsn_items,
        doc_summary=doc_summary,
    )


@router.get("/tax-ledger/gstr1/export-json")
def gstr1_export_json(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Export GSTR-1 data in GSTN-compatible JSON format."""
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    invoices = _gstr1_invoice_query(db, from_date, to_date, company_id)
    company_gstin = (active_company.gst or "").strip().upper() if active_company else ""

    # Validate before export
    validation_errors = _validate_gstr1_export(db, company_gstin, invoices)
    if validation_errors:
        raise HTTPException(
            status_code=400,
            detail="GSTR-1 validation failed: " + "; ".join(validation_errors),
        )

    company_pos = _derive_place_of_supply(company_gstin)
    fp = f"{from_date.month:02d}{from_date.year}"

    # B2B: Group by customer GSTIN, POS per customer (ctin[:2])
    b2b_by_ctin: dict[str, list[dict]] = {}
    for inv in invoices:
        if inv.voucher_type != "sales" or not inv.ledger_gst or not inv.ledger_gst.strip():
            continue
        ctin = inv.ledger_gst.strip().upper()
        # POS is customer's state code for B2B
        inv_pos = ctin[:2] if len(ctin) >= 2 and ctin[:2].isdigit() else company_pos
        itms = []
        for item in inv.items:
            rate = float(item.gst_rate or 0)
            itms.append({
                "num": len(itms) + 1,
                "itm_det": {
                    "rt": rate,
                    "txval": float(item.taxable_amount or 0),
                    "camt": float(item.cgst_amount or 0),
                    "samt": float(item.sgst_amount or 0),
                    "iamt": float(item.igst_amount or 0),
                    "csamt": 0.0,
                },
            })
        entry = {
            "inum": inv.invoice_number or f"INV-{inv.id}",
            "idt": inv.invoice_date.strftime("%d-%m-%Y") if inv.invoice_date else "",
            "val": float(inv.total_amount or 0),
            "pos": inv_pos,
            "rchrg": "N",
            "inv_typ": "R",
            "itms": itms,
        }
        b2b_by_ctin.setdefault(ctin, []).append(entry)

    b2b_section = [{"ctin": ctin, "inv": invs} for ctin, invs in b2b_by_ctin.items()]

    # B2CL: Aggregate invoices without GSTIN with value > 2.5L
    b2cl_invs: list[dict] = []
    b2cl_pos_dict: dict[str, str] = {}  # pos by invoice
    for inv in invoices:
        if inv.voucher_type != "sales" or (inv.ledger_gst and inv.ledger_gst.strip()):
            continue
        if float(inv.taxable_amount or 0) <= 250000:
            continue
        # B2CL: POS = state of supply (use company state code as fallback)
        inv_pos = company_pos
        itms = []
        for item in inv.items:
            itms.append({
                "num": len(itms) + 1,
                "itm_det": {
                    "rt": float(item.gst_rate or 0),
                    "txval": float(item.taxable_amount or 0),
                    "camt": float(item.cgst_amount or 0),
                    "samt": float(item.sgst_amount or 0),
                    "iamt": float(item.igst_amount or 0),
                    "csamt": 0.0,
                },
            })
        b2cl_invs.append({
            "inum": inv.invoice_number or f"INV-{inv.id}",
            "idt": inv.invoice_date.strftime("%d-%m-%Y") if inv.invoice_date else "",
            "val": float(inv.total_amount or 0),
            "pos": inv_pos,
            "inv_typ": "R",
            "itms": itms,
        })

    # B2CS - aggregate by state and tax rate
    b2cs_by_key: dict[str, dict] = {}
    for inv in invoices:
        if inv.voucher_type != "sales" or (inv.ledger_gst and inv.ledger_gst.strip()):
            continue
        if float(inv.taxable_amount or 0) > 250000:
            continue
        for item in inv.items:
            rate = float(item.gst_rate or 0)
            if rate == 0:
                continue
            key = f"{company_pos}|{rate}"
            if key not in b2cs_by_key:
                b2cs_by_key[key] = {"txval": 0.0, "camt": 0.0, "samt": 0.0, "iamt": 0.0}
            b2cs_by_key[key]["txval"] += float(item.taxable_amount or 0)
            b2cs_by_key[key]["camt"] += float(item.cgst_amount or 0)
            b2cs_by_key[key]["samt"] += float(item.sgst_amount or 0)
            b2cs_by_key[key]["iamt"] += float(item.igst_amount or 0)

    b2cs_items: list[dict] = []
    for key, data in b2cs_by_key.items():
        sply_ty, rate_str = key.split("|")
        b2cs_items.append({
            "ty": "INTER" if data["iamt"] > 0 else "INTRA",
            "hsn_sc": "",
            "txval": data["txval"],
            "irt": float(rate_str) if data["iamt"] > 0 else 0,
            "crt": float(rate_str) / 2 if data["iamt"] == 0 else 0,
            "srt": float(rate_str) / 2 if data["iamt"] == 0 else 0,
            "iamt": data["iamt"],
            "camt": data["camt"],
            "samt": data["samt"],
        })

    # CDNR (Credit/Debit Notes)
    credit_note_q = (
        db.query(CreditNote)
        .options(joinedload(CreditNote.items))
        .filter(CreditNote.status == "active")
        .filter(CreditNote.created_at >= datetime.combine(from_date, time.min))
        .filter(CreditNote.created_at <= datetime.combine(to_date, time.max))
    )
    if company_id is not None:
        credit_note_q = credit_note_q.filter(or_(CreditNote.company_id == company_id, CreditNote.company_id.is_(None)))
    credit_notes = credit_note_q.all()

    # Pre-load all referenced invoices for CDNR ctin lookup
    invoice_ids: set[int] = set()
    for cn in credit_notes:
        for item in (cn.items or []):
            if item.invoice_id:
                invoice_ids.add(item.invoice_id)
    invoices_by_id: dict[int, Invoice] = {}
    if invoice_ids:
        inv_records = db.query(Invoice).filter(Invoice.id.in_(invoice_ids)).all()
        invoices_by_id = {inv.id: inv for inv in inv_records}

    cdnr_section: list[dict] = []
    for cn in credit_notes:
        cn_cgst = float(cn.cgst_amount or 0)
        cn_sgst = float(cn.sgst_amount or 0)
        cn_igst = float(cn.igst_amount or 0)
        item_count = len(cn.items) if cn.items else 1
        ntype = cn.credit_note_type.upper() if cn.credit_note_type else "R"
        itms = []
        for item in cn.items:
            item_cgst = cn_cgst / item_count
            item_sgst = cn_sgst / item_count
            item_igst = cn_igst / item_count
            itms.append({
                "num": len(itms) + 1,
                "itm_det": {
                    "rt": float(item.gst_rate or 0),
                    "txval": float(item.taxable_amount or 0),
                    "camt": item_cgst,
                    "samt": item_sgst,
                    "iamt": item_igst,
                    "csamt": 0.0,
                },
            })
        # Get customer GSTIN from original invoice via CreditNoteItem.invoice_id
        ctin = ""
        if cn.items:
            first_item = cn.items[0]
            if first_item.invoice_id:
                original_inv = invoices_by_id.get(first_item.invoice_id)
                if original_inv and original_inv.ledger_gst:
                    ctin = original_inv.ledger_gst.strip().upper()
        # CDNR POS uses company POS (same as original invoice's state of supply)
        cnr_pos = company_pos
        cdnr_section.append({
            "ctin": ctin,
            "ntty": "C" if ntype in ("RETURN", "R") else "D",
            "nt_num": cn.credit_note_number or f"CN-{cn.id}",
            "nt_dt": cn.created_at.strftime("%d-%m-%Y") if cn.created_at else "",
            "inum": "",
            "idt": "",
            "val": float(cn.total_amount or 0),
            "pos": cnr_pos,
            "rchrg": "N",
            "itms": itms,
        })

    # HSN summary
    hsn_map: dict[str, dict] = {}
    for inv in invoices:
        if inv.voucher_type != "sales":
            continue
        for item in inv.items:
            hsn = item.hsn_sac or "----"
            if hsn not in hsn_map:
                hsn_map[hsn] = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "qty": 0.0}
            hsn_map[hsn]["taxable"] += float(item.taxable_amount or 0)
            hsn_map[hsn]["cgst"] += float(item.cgst_amount or 0)
            hsn_map[hsn]["sgst"] += float(item.sgst_amount or 0)
            hsn_map[hsn]["igst"] += float(item.igst_amount or 0)
            hsn_map[hsn]["qty"] += float(item.quantity or 0)

    hsn_data: dict[str, list[dict]] = {"data": []}
    for hsn, data in sorted(hsn_map.items()):
        hsn_data["data"].append({
            "hsn_sc": hsn,
            "desc": "",
            "uqc": "NOS",
            "qty": data["qty"],
            "txval": data["taxable"],
            "camt": data["cgst"],
            "samt": data["sgst"],
            "iamt": data["igst"],
            "csamt": 0.0,
        })

    total_sales = sum(1 for inv in invoices if inv.voucher_type == "sales")
    total_cn = sum(1 for cn in credit_notes if cn.credit_note_type == "return")
    total_dn = sum(1 for cn in credit_notes if cn.credit_note_type != "return")

    result = {
        "gstin": company_gstin,
        "fp": fp,
        "b2b": b2b_section,
        "b2cl": b2cl_invs,
        "b2cs": b2cs_items,
        "cdnr": cdnr_section,
        "hsn": hsn_data,
        "doc_issue": {
            "doc_det": [
                {"doc_num": total_sales, "doc_typ": "INV"},
                {"doc_num": total_cn, "doc_typ": "CRN"},
                {"doc_num": total_dn, "doc_typ": "DBN"},
            ]
        },
    }

    import json as _json
    json_bytes = _json.dumps(result, indent=2, default=str).encode("utf-8")
    filename = f"gstr1_{from_date}_{to_date}.json"

    from fastapi.responses import Response
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tax-ledger/gstr1/export-csv")
def gstr1_export_csv(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Export GSTR-1 data as CSV for review and reconciliation."""
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    invoices = _gstr1_invoice_query(db, from_date, to_date, company_id)
    company_gstin = (active_company.gst or "").strip().upper() if active_company else ""

    # Validate company GSTIN
    if not company_gstin:
        raise HTTPException(
            status_code=400,
            detail="Company GSTIN is required to generate GSTR-1 CSV. Please set your company GSTIN in Settings.",
        )

    company_pos = _derive_place_of_supply(company_gstin)

    csv_buffer = StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow([
        "Section", "Date", "Invoice Number", "Party Name", "GSTIN (Customer)",
        "HSN/SAC", "Taxable Value", "CGST", "SGST", "IGST",
        "Total Invoice Value", "Place of Supply",
    ])

    for inv in invoices:
        if inv.voucher_type != "sales":
            continue
        gstin = inv.ledger_gst.strip().upper() if inv.ledger_gst else ""
        if gstin:
            section = "B2B"
            # B2B: POS = customer's state code
            pos = gstin[:2] if len(gstin) >= 2 and gstin[:2].isdigit() else company_pos
        elif float(inv.taxable_amount or 0) > 250000:
            section = "B2CL"
            pos = company_pos
        else:
            section = "B2CS"
            pos = company_pos

        hsns = ", ".join(item.hsn_sac or "" for item in inv.items if item.hsn_sac)
        writer.writerow([
            section,
            inv.invoice_date.date().isoformat() if inv.invoice_date else "",
            inv.invoice_number or f"INV-{inv.id}",
            inv.ledger_name or "",
            gstin,
            hsns,
            f"{float(inv.taxable_amount or 0):.2f}",
            f"{float(inv.cgst_amount or 0):.2f}",
            f"{float(inv.sgst_amount or 0):.2f}",
            f"{float(inv.igst_amount or 0):.2f}",
            f"{float(inv.total_amount or 0):.2f}",
            pos,
        ])

    csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")
    filename = f"gstr1_{from_date}_{to_date}.csv"

    return StreamingResponse(
        BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tax-ledger/gstr1/export-pdf")
def gstr1_export_pdf(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Export GSTR-1 summary as PDF."""
    company_id = getattr(active_company, "id", None)
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    # Reuse summary logic inline
    company = active_company if company_id is not None else db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    currency = company.currency_code if company and company.currency_code else "INR"

    invoices = _gstr1_invoice_query(db, from_date, to_date, company_id)
    b2b_count = sum(1 for inv in invoices if inv.voucher_type == "sales" and inv.ledger_gst and inv.ledger_gst.strip())
    b2cl_count = sum(1 for inv in invoices if inv.voucher_type == "sales" and (not inv.ledger_gst or not inv.ledger_gst.strip()) and float(inv.taxable_amount or 0) > 250000)
    b2cs_count = sum(1 for inv in invoices if inv.voucher_type == "sales" and (not inv.ledger_gst or not inv.ledger_gst.strip()) and float(inv.taxable_amount or 0) <= 250000 and (float(inv.cgst_amount or 0) + float(inv.sgst_amount or 0) + float(inv.igst_amount or 0)) > 0)

    nil_rated_count = sum(1 for inv in invoices if inv.voucher_type == "sales" and (not inv.ledger_gst or not inv.ledger_gst.strip()) and float(inv.cgst_amount or 0) + float(inv.sgst_amount or 0) + float(inv.igst_amount or 0) == 0)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
    body {{ font-family: Arial, sans-serif; font-size: 11px; margin: 24px; }}
    h1 {{ font-size: 18px; margin-bottom: 4px; }}
    h2 {{ font-size: 14px; margin-top: 20px; }}
    .meta {{ color: #555; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 16px; }}
    th, td {{ border: 1px solid #ccc; padding: 5px 8px; font-size: 10px; }}
    th {{ background: #f5f5f5; text-align: left; }}
    .right {{ text-align: right; }}
</style></head><body>
<h1>GSTR-1 Filing Report</h1>
<p class="meta">
    {_e(company.name if company else '')} &mdash;
    {from_date} to {to_date}
</p>
<h2>Filing Summary</h2>
<table>
    <thead><tr>
        <th>Category</th><th>Invoices</th><th>Taxable Value</th>
        <th>CGST</th><th>SGST</th><th>IGST</th><th>Total Tax</th>
    </tr></thead>
    <tbody>
        <tr><td>B2B (with GSTIN)</td><td>{b2b_count}</td>
            <td class="right">₹{sum(float(inv.taxable_amount or 0) for inv in invoices if inv.voucher_type == "sales" and inv.ledger_gst and inv.ledger_gst.strip()):,.2f}</td>
            <td class="right">₹{sum(float(inv.cgst_amount or 0) for inv in invoices if inv.voucher_type == "sales" and inv.ledger_gst and inv.ledger_gst.strip()):,.2f}</td>
            <td class="right">₹{sum(float(inv.sgst_amount or 0) for inv in invoices if inv.voucher_type == "sales" and inv.ledger_gst and inv.ledger_gst.strip()):,.2f}</td>
            <td class="right">₹{sum(float(inv.igst_amount or 0) for inv in invoices if inv.voucher_type == "sales" and inv.ledger_gst and inv.ledger_gst.strip()):,.2f}</td>
            <td class="right">₹{sum(float(inv.cgst_amount or 0) + float(inv.sgst_amount or 0) + float(inv.igst_amount or 0) for inv in invoices if inv.voucher_type == "sales" and inv.ledger_gst and inv.ledger_gst.strip()):,.2f}</td>
        </tr>
        <tr><td>B2CL (&gt;2.5L, no GSTIN)</td><td>{b2cl_count}</td>
            <td class="right">₹{sum(float(inv.taxable_amount or 0) for inv in invoices if inv.voucher_type == "sales" and (not inv.ledger_gst or not inv.ledger_gst.strip()) and float(inv.taxable_amount or 0) > 250000):,.2f}</td>
            <td colspan="4" class="right">-</td>
        </tr>
        <tr><td>B2CS (&le;2.5L, no GSTIN)</td><td>{b2cs_count}</td>
            <td class="right">₹{sum(float(inv.taxable_amount or 0) for inv in invoices if inv.voucher_type == "sales" and (not inv.ledger_gst or not inv.ledger_gst.strip()) and float(inv.taxable_amount or 0) <= 250000 and (float(inv.cgst_amount or 0) + float(inv.sgst_amount or 0) + float(inv.igst_amount or 0)) > 0):,.2f}</td>
            <td colspan="4" class="right">-</td>
        </tr>
        <tr><td>Nil Rated / Exempt</td><td>{nil_rated_count}</td>
            <td colspan="5" class="right">-</td>
        </tr>
    </tbody>
</table>
<p style="font-size: 9px; color: #888;">Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""

    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    buf = BytesIO(pdf_bytes)
    filename = f"gstr1_{from_date}_{to_date}.pdf"

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )