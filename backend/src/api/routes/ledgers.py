from datetime import date, datetime, time, timezone
from html import escape
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session

import weasyprint

from src.api.deps import get_current_user, require_roles
from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.payment import Payment
from src.models.user import User, UserRole
from src.schemas.ledger import DayBookEntry, DayBookOut, LedgerCreate, LedgerOut, LedgerStatementEntry, LedgerStatementOut, PaginatedLedgerOut

router = APIRouter()


def _make_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC) for consistent sorting."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@router.post("", response_model=LedgerOut, include_in_schema=False)
@router.post("/", response_model=LedgerOut)
def create_ledger(
    payload: LedgerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    existing_ledger = db.query(Ledger).filter(Ledger.gst == payload.gst.strip()).first()
    if existing_ledger:
        raise HTTPException(status_code=400, detail="Ledger with this GST already exists")

    ledger = Ledger(
        name=payload.name.strip(),
        address=payload.address.strip(),
        gst=payload.gst.strip().upper(),
        phone_number=payload.phone_number.strip(),
        email=payload.email.strip() if payload.email else None,
        website=payload.website.strip() if payload.website else None,
        bank_name=payload.bank_name.strip() if payload.bank_name else None,
        branch_name=payload.branch_name.strip() if payload.branch_name else None,
        account_name=payload.account_name.strip() if payload.account_name else None,
        account_number=payload.account_number.strip() if payload.account_number else None,
        ifsc_code=payload.ifsc_code.strip().upper() if payload.ifsc_code else None,
    )
    db.add(ledger)
    db.commit()
    db.refresh(ledger)
    return ledger


@router.get("", response_model=PaginatedLedgerOut, include_in_schema=False)
@router.get("/", response_model=PaginatedLedgerOut)
def list_ledgers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Ledger)
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
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    invoices = (
        db.query(Invoice)
        .filter(Invoice.invoice_date >= period_start)
        .filter(Invoice.invoice_date <= period_end)
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        .all()
    )

    payments = (
        db.query(Payment)
        .filter(Payment.date >= period_start)
        .filter(Payment.date <= period_end)
        .order_by(Payment.date.asc(), Payment.id.asc())
        .all()
    )

    entries = []
    for invoice in invoices:
        entries.append(DayBookEntry(
            entry_id=invoice.id,
            entry_type="invoice",
            date=invoice.invoice_date,
            voucher_type=invoice.voucher_type.title(),
            ledger_name=invoice.ledger_name or "Unknown ledger",
            particulars=f"{invoice.voucher_type.title()} Invoice #{invoice.id}",
            debit=float(invoice.total_amount) if invoice.voucher_type == "sales" else 0.0,
            credit=float(invoice.total_amount) if invoice.voucher_type == "purchase" else 0.0,
        ))
    for payment in payments:
        ledger = db.query(Ledger).filter(Ledger.id == payment.ledger_id).first()
        entries.append(DayBookEntry(
            entry_id=payment.id,
            entry_type="payment",
            date=payment.date,
            voucher_type=payment.voucher_type.title(),
            ledger_name=ledger.name if ledger else "Unknown ledger",
            particulars=f"{payment.voucher_type.title()} #{payment.id}" + (f" ({payment.mode})" if payment.mode else ""),
            debit=float(payment.amount) if payment.voucher_type == "payment" else 0.0,
            credit=float(payment.amount) if payment.voucher_type == "receipt" else 0.0,
        ))
    entries.sort(key=lambda e: _make_aware(e.date))

    return DayBookOut(
        from_date=from_date,
        to_date=to_date,
        total_debit=sum(entry.debit for entry in entries),
        total_credit=sum(entry.credit for entry in entries),
        entries=entries,
    )


@router.get("/{ledger_id}", response_model=LedgerOut)
def get_ledger(
    ledger_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")
    return ledger


@router.put("/{ledger_id}", response_model=LedgerOut)
def update_ledger(
    ledger_id: int,
    payload: LedgerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    gst = payload.gst.strip().upper()
    gst_owner = db.query(Ledger).filter(Ledger.gst == gst, Ledger.id != ledger_id).first()
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

    db.commit()
    db.refresh(ledger)
    return ledger


@router.delete("/{ledger_id}")
def delete_ledger(
    ledger_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    has_invoices = db.query(Invoice.id).filter(Invoice.ledger_id == ledger_id).first()
    if has_invoices:
        raise HTTPException(status_code=400, detail="Cannot delete ledger linked to invoices")

    has_payments = db.query(Payment.id).filter(Payment.ledger_id == ledger_id).first()
    if has_payments:
        raise HTTPException(status_code=400, detail="Cannot delete ledger linked to payments")

    db.delete(ledger)
    db.commit()
    return {"message": "Ledger deleted"}


@router.get("/{ledger_id}/statement", response_model=LedgerStatementOut)
def get_ledger_statement(
    ledger_id: int,
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    opening_totals = (
        db.query(
            func.coalesce(func.sum(case((Invoice.voucher_type == "sales", Invoice.total_amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.voucher_type == "purchase", Invoice.total_amount), else_=0)), 0),
        )
        .filter(Invoice.ledger_id == ledger_id)
        .filter(Invoice.invoice_date < period_start)
        .one()
    )

    opening_payment_totals = (
        db.query(
            func.coalesce(func.sum(case((Payment.voucher_type == "payment", Payment.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.voucher_type == "receipt", Payment.amount), else_=0)), 0),
        )
        .filter(Payment.ledger_id == ledger_id)
        .filter(Payment.date < period_start)
        .one()
    )

    period_invoices = (
        db.query(Invoice)
        .filter(Invoice.ledger_id == ledger_id)
        .filter(Invoice.invoice_date >= period_start)
        .filter(Invoice.invoice_date <= period_end)
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        .all()
    )

    period_payments = (
        db.query(Payment)
        .filter(Payment.ledger_id == ledger_id)
        .filter(Payment.date >= period_start)
        .filter(Payment.date <= period_end)
        .order_by(Payment.date.asc(), Payment.id.asc())
        .all()
    )

    entries = []
    for invoice in period_invoices:
        entries.append(LedgerStatementEntry(
            entry_id=invoice.id,
            entry_type="invoice",
            date=invoice.invoice_date,
            voucher_type=invoice.voucher_type.title(),
            particulars=invoice.ledger_name or ledger.name,
            debit=float(invoice.total_amount) if invoice.voucher_type == "sales" else 0.0,
            credit=float(invoice.total_amount) if invoice.voucher_type == "purchase" else 0.0,
        ))
    for payment in period_payments:
        entries.append(LedgerStatementEntry(
            entry_id=payment.id,
            entry_type="payment",
            date=payment.date,
            voucher_type=payment.voucher_type.title(),
            particulars=f"{payment.voucher_type.title()}" + (f" ({payment.mode})" if payment.mode else ""),
            debit=float(payment.amount) if payment.voucher_type == "payment" else 0.0,
            credit=float(payment.amount) if payment.voucher_type == "receipt" else 0.0,
        ))
    entries.sort(key=lambda e: _make_aware(e.date))

    period_debit = sum(entry.debit for entry in entries)
    period_credit = sum(entry.credit for entry in entries)
    opening_debit = float(opening_totals[0]) + float(opening_payment_totals[0])
    opening_credit = float(opening_totals[1]) + float(opening_payment_totals[1])
    opening_balance = opening_debit - opening_credit
    closing_balance = opening_balance + period_debit - period_credit

    return LedgerStatementOut(
        ledger=ledger,
        from_date=from_date,
        to_date=to_date,
        opening_balance=opening_balance,
        period_debit=period_debit,
        period_credit=period_credit,
        closing_balance=closing_balance,
        entries=entries,
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
        entry_rows += f"""
        <tr>
          <td>{_e(entry_date)}</td>
          <td>{vtype} #{entry.entry_id}</td>
          <td>{_e(entry.particulars)}</td>
          <td class="right">{dr}</td>
          <td class="right">{cr}</td>
        </tr>"""

    company_name = _e(company.name) if company else "Company"
    company_address = _e(company.address) if company else ""
    company_gst = f"GST: {_e(company.gst)}" if company and company.gst else ""
    company_phone = f"Phone: {_e(company.phone_number)}" if company and company.phone_number else ""
    company_details = " &middot; ".join(p for p in [company_gst, company_phone] if p)

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
    <p>GST: {_e(ledger.gst)} &middot; Phone: {_e(ledger.phone_number)}</p>
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
):
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")

    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")

    company = db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    currency = company.currency_code if company and company.currency_code else "INR"

    # Reuse the same calculation logic as the statement endpoint
    period_start = datetime.combine(from_date, time.min)
    period_end = datetime.combine(to_date, time.max)

    opening_totals = (
        db.query(
            func.coalesce(func.sum(case((Invoice.voucher_type == "sales", Invoice.total_amount), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.voucher_type == "purchase", Invoice.total_amount), else_=0)), 0),
        )
        .filter(Invoice.ledger_id == ledger_id)
        .filter(Invoice.invoice_date < period_start)
        .one()
    )

    opening_payment_totals = (
        db.query(
            func.coalesce(func.sum(case((Payment.voucher_type == "payment", Payment.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.voucher_type == "receipt", Payment.amount), else_=0)), 0),
        )
        .filter(Payment.ledger_id == ledger_id)
        .filter(Payment.date < period_start)
        .one()
    )

    period_invoices = (
        db.query(Invoice)
        .filter(Invoice.ledger_id == ledger_id)
        .filter(Invoice.invoice_date >= period_start)
        .filter(Invoice.invoice_date <= period_end)
        .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        .all()
    )

    period_payments = (
        db.query(Payment)
        .filter(Payment.ledger_id == ledger_id)
        .filter(Payment.date >= period_start)
        .filter(Payment.date <= period_end)
        .order_by(Payment.date.asc(), Payment.id.asc())
        .all()
    )

    entries: list[LedgerStatementEntry] = []
    for invoice in period_invoices:
        entries.append(LedgerStatementEntry(
            entry_id=invoice.id,
            entry_type="invoice",
            date=invoice.invoice_date,
            voucher_type=invoice.voucher_type.title(),
            particulars=invoice.ledger_name or ledger.name,
            debit=float(invoice.total_amount) if invoice.voucher_type == "sales" else 0.0,
            credit=float(invoice.total_amount) if invoice.voucher_type == "purchase" else 0.0,
        ))
    for payment in period_payments:
        entries.append(LedgerStatementEntry(
            entry_id=payment.id,
            entry_type="payment",
            date=payment.date,
            voucher_type=payment.voucher_type.title(),
            particulars=f"{payment.voucher_type.title()}" + (f" ({payment.mode})" if payment.mode else ""),
            debit=float(payment.amount) if payment.voucher_type == "payment" else 0.0,
            credit=float(payment.amount) if payment.voucher_type == "receipt" else 0.0,
        ))
    entries.sort(key=lambda e: _make_aware(e.date))

    period_debit = sum(e.debit for e in entries)
    period_credit = sum(e.credit for e in entries)
    opening_debit = float(opening_totals[0]) + float(opening_payment_totals[0])
    opening_credit = float(opening_totals[1]) + float(opening_payment_totals[1])
    opening_balance = opening_debit - opening_credit
    closing_balance = opening_balance + period_debit - period_credit

    html = _build_statement_html(
        ledger=ledger,
        company=company,
        from_date=from_date,
        to_date=to_date,
        opening_balance=opening_balance,
        period_debit=period_debit,
        period_credit=period_credit,
        closing_balance=closing_balance,
        entries=entries,
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