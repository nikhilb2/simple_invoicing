from datetime import datetime
from html import escape
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import weasyprint

from src.api.deps import get_current_user, require_roles
from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.company_account import CompanyAccount
from src.models.company import CompanyProfile
from src.models.payment import Payment
from src.models.user import User, UserRole
from src.schemas.payment import PaymentCreate, PaymentOut, PaymentUpdate
from src.services.series import generate_next_number
from src.services.financial_year import get_active_fy, get_fy_for_date

router = APIRouter()


def _get_active_account(db: Session, account_id: int) -> CompanyAccount:
    account = db.query(CompanyAccount).filter(
        CompanyAccount.id == account_id,
        CompanyAccount.is_active.is_(True),
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _to_payment_out(payment: Payment) -> PaymentOut:
    result = PaymentOut.model_validate(payment)
    if payment.account is not None:
        result.account_display_name = payment.account.display_name
        result.account_type = payment.account.account_type
    return result


def _find_existing_opening_balance(
    db: Session,
    ledger_id: int,
    exclude_payment_id: int | None = None,
) -> Payment | None:
    query = db.query(Payment).filter(
        Payment.ledger_id == ledger_id,
        Payment.voucher_type == "opening_balance",
        Payment.status == "active",
    )
    if exclude_payment_id is not None:
        query = query.filter(Payment.id != exclude_payment_id)
    return query.first()


def _ensure_single_opening_balance(
    db: Session,
    ledger_id: int | None,
    voucher_type: str,
    exclude_payment_id: int | None = None,
) -> None:
    if voucher_type != "opening_balance":
        return

    if ledger_id is None:
        raise HTTPException(status_code=400, detail="opening_balance requires ledger_id")

    existing = _find_existing_opening_balance(
        db,
        ledger_id,
        exclude_payment_id=exclude_payment_id,
    )
    if existing:
        raise HTTPException(status_code=409, detail="Opening balance already exists for this ledger")


@router.post("", response_model=PaymentOut, include_in_schema=False)
@router.post("/", response_model=PaymentOut)
def create_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    _ensure_single_opening_balance(db, payload.ledger_id, payload.voucher_type)

    if payload.ledger_id is not None:
        ledger = db.query(Ledger).filter(Ledger.id == payload.ledger_id).first()
        if not ledger:
            raise HTTPException(status_code=404, detail="Ledger not found")
    elif payload.account_id is None:
        raise HTTPException(status_code=400, detail="Either ledger_id or account_id is required")

    selected_account = None
    if payload.account_id is not None:
        selected_account = _get_active_account(db, payload.account_id)

    payment_date = payload.date or datetime.utcnow()
    payment_day = payment_date.date() if hasattr(payment_date, "date") else payment_date

    active_fy = get_active_fy(db)
    fy_for_payment = active_fy
    if payment_day is not None:
        dated_fy = get_fy_for_date(db, payment_day)
        if dated_fy is not None:
            fy_for_payment = dated_fy
    fy_id = fy_for_payment.id if fy_for_payment else None

    payment_number = None
    if payload.voucher_type != "opening_balance":
        payment_number = generate_next_number(
            db,
            "payment",
            fy_id,
            payment_day,
            active_fy.id if active_fy else None,
        )

    payment = Payment(
        ledger_id=payload.ledger_id,
        voucher_type=payload.voucher_type,
        amount=payload.amount,
        account_id=selected_account.id if selected_account else None,
        date=payment_date,
        mode=payload.mode.strip() if payload.mode else None,
        reference=payload.reference.strip() if payload.reference else None,
        notes=payload.notes.strip() if payload.notes else None,
        payment_number=payment_number,
        financial_year_id=fy_id,
        created_by=current_user.id,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    warnings: list[str] = []
    if active_fy:
        pdate = payment_day
        if not (active_fy.start_date <= pdate <= active_fy.end_date):
            warnings.append("invoice_date_outside_fy")

    result = _to_payment_out(payment)
    result.warnings = warnings
    return result


@router.get("", response_model=list[PaymentOut], include_in_schema=False)
@router.get("/", response_model=list[PaymentOut])
def list_payments(
    ledger_id: int | None = Query(None),
    include_cancelled: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Payment)
    if ledger_id is not None:
        query = query.filter(Payment.ledger_id == ledger_id)
    if not include_cancelled:
        query = query.filter(Payment.status == "active")
    return [_to_payment_out(payment) for payment in query.order_by(Payment.date.desc()).all()]


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return _to_payment_out(payment)


@router.put("/{payment_id}", response_model=PaymentOut)
def update_payment(
    payment_id: int,
    payload: PaymentUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.status == "active").first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    next_ledger_id = payment.ledger_id
    _ensure_single_opening_balance(
        db,
      next_ledger_id,
        payload.voucher_type,
        exclude_payment_id=payment.id,
    )

    selected_account = None
    if payload.account_id is not None:
        selected_account = _get_active_account(db, payload.account_id)

    payment.voucher_type = payload.voucher_type
    payment.amount = payload.amount
    payment.account_id = selected_account.id if selected_account else None
    if payload.date is not None:
        payment.date = payload.date
    payment.mode = payload.mode.strip() if payload.mode else None
    payment.reference = payload.reference.strip() if payload.reference else None
    payment.notes = payload.notes.strip() if payload.notes else None
    db.commit()
    db.refresh(payment)
    result = _to_payment_out(payment)
    return result


@router.delete("/{payment_id}")
def delete_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.status == "active").first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment.status = "cancelled"
    db.commit()
    return {"message": "Payment cancelled"}


# ---------------------------------------------------------------------------
# Receipt / Payment voucher PDF
# ---------------------------------------------------------------------------

def _re(text: str | None) -> str:
    return escape(str(text or ""))


def _fmt_amt(value: float, currency_code: str | None = None) -> str:
    code = currency_code or "INR"
    try:
        if code == "INR":
            return f"\u20b9{value:,.2f}"
        elif code == "EUR":
            return f"\u20ac{value:,.2f}"
        elif code == "GBP":
            return f"\u00a3{value:,.2f}"
        else:
            return f"${value:,.2f}"
    except Exception:
        return f"{value:,.2f}"


def _build_receipt_html(payment: Payment, company: CompanyProfile | None) -> str:
    ledger = payment.ledger
    account = payment.account

    currency = (company.currency_code or "INR") if company else "INR"
    voucher_label = "Receipt" if payment.voucher_type == "receipt" else "Payment"
    voucher_number = _re(payment.payment_number) if payment.payment_number else f"#{payment.id}"
    dt = payment.date
    date_str = dt.strftime("%d %b %Y") if dt else "N/A"
    time_str = dt.strftime("%H:%M") if dt else ""

    company_name = _re(company.name) if company else "Company"
    company_address = _re(company.address) if company else ""
    company_gst = _re(company.gst) if company else ""
    company_phone = _re(company.phone_number) if company else ""
    company_email = _re(company.email) if company else ""

    ledger_name = _re(ledger.name) if ledger else "Unknown"
    ledger_address = _re(ledger.address) if ledger else ""
    ledger_phone = _re(ledger.phone_number) if ledger else ""
    ledger_gst = _re(ledger.gst) if ledger else ""

    amount_fmt = _fmt_amt(float(payment.amount), currency)
    mode_label = _re((payment.mode or "").title()) or "—"
    reference = _re(payment.reference) if payment.reference else "—"
    notes = _re(payment.notes) if payment.notes else ""

    account_name = _re(account.display_name) if account else "Unallocated"
    account_type = _re(account.account_type) if account else ""
    account_bank = _re(account.bank_name) if account and account.bank_name else ""

    party_label = "Received from" if payment.voucher_type == "receipt" else "Paid to"

    # Company detail line
    company_details_parts = []
    if company_gst:
        company_details_parts.append(f"GST: {company_gst}")
    if company_phone:
        company_details_parts.append(f"Ph: {company_phone}")
    if company_email:
        company_details_parts.append(f"Email: {company_email}")
    company_details = " &middot; ".join(company_details_parts)

    # Ledger detail line
    ledger_details_parts = []
    if ledger_gst:
        ledger_details_parts.append(f"GST: {ledger_gst}")
    if ledger_phone:
        ledger_details_parts.append(f"Ph: {ledger_phone}")
    ledger_details = " &middot; ".join(ledger_details_parts)

    account_html = f"""
    <tr>
      <td class="label">Account</td>
      <td>{account_name}{f' <span class="chip">{account_type}</span>' if account_type else ''}{f'<br><span class="sub">{account_bank}</span>' if account_bank else ''}</td>
    </tr>"""

    notes_html = f"""
    <tr>
      <td class="label">Notes</td>
      <td>{notes}</td>
    </tr>""" if notes else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: A5 landscape;
    margin: 12mm 16mm;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 10px;
    color: #1f2937;
    line-height: 1.5;
  }}
  .sheet {{
    width: 100%;
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 12px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 14px;
  }}
  .header h3 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .header p {{
    font-size: 8.5px;
    color: #6b7280;
    margin-bottom: 1px;
  }}
  .meta {{
    text-align: right;
  }}
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #fff;
    background: {"#16a34a" if payment.voucher_type == "receipt" else "#2563eb"};
    margin-bottom: 6px;
  }}
  .meta h2 {{
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .meta p {{
    font-size: 8.5px;
    color: #6b7280;
  }}
  .party-box {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 14px;
  }}
  .party-box .eyebrow {{
    font-size: 7.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .party-box h4 {{
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 2px;
    color: #111827;
  }}
  .party-box p {{
    font-size: 8.5px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .details-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 14px;
    font-size: 9px;
  }}
  .details-table td {{
    padding: 5px 8px;
    border-bottom: 1px solid #f3f4f6;
    vertical-align: top;
  }}
  .details-table td.label {{
    width: 28%;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    font-size: 8px;
    letter-spacing: 0.05em;
  }}
  .amount-block {{
    border-top: 2px solid #e5e7eb;
    padding-top: 12px;
    text-align: right;
  }}
  .amount-big {{
    font-size: 26px;
    font-weight: 700;
    color: {"#16a34a" if payment.voucher_type == "receipt" else "#2563eb"};
  }}
  .amount-label {{
    font-size: 8.5px;
    color: #9ca3af;
    margin-top: 2px;
  }}
  .chip {{
    display: inline-block;
    padding: 1px 6px;
    background: #eff6ff;
    color: #1a56db;
    border-radius: 4px;
    font-size: 8px;
    font-weight: 600;
    margin-left: 4px;
  }}
  .sub {{
    font-size: 8px;
    color: #9ca3af;
  }}
  .footer {{
    margin-top: 14px;
    border-top: 1px solid #e5e7eb;
    padding-top: 8px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }}
  .footer p {{
    font-size: 8px;
    color: #9ca3af;
  }}
  .sig-line {{
    width: 120px;
    border-top: 1px solid #d1d5db;
    padding-top: 4px;
    font-size: 8px;
    color: #6b7280;
    text-align: center;
  }}
</style>
</head>
<body>
<div class="sheet">
  <header class="header">
    <div>
      <h3>{company_name}</h3>
      <p>{company_address}</p>
      <p>{company_details}</p>
    </div>
    <div class="meta">
      <span class="badge">{voucher_label}</span>
      <h2>{voucher_number}</h2>
      <p>Date: {date_str}{f' {time_str}' if time_str else ''}</p>
    </div>
  </header>

  <section class="party-box">
    <p class="eyebrow">{party_label}</p>
    <h4>{ledger_name}</h4>
    <p>{ledger_address}</p>
    <p>{ledger_details}</p>
  </section>

  <table class="details-table">
    <tr>
      <td class="label">Mode</td>
      <td>{mode_label}</td>
    </tr>
    <tr>
      <td class="label">Reference</td>
      <td>{reference}</td>
    </tr>
    {account_html}
    {notes_html}
  </table>

  <section class="amount-block">
    <p class="amount-label">{voucher_label} Amount</p>
    <p class="amount-big">{amount_fmt}</p>
  </section>

  <footer class="footer">
    <p>Generated by {company_name} &middot; {date_str}</p>
    <div class="sig-line">Authorised Signatory</div>
  </footer>
</div>
</body>
</html>"""
    return html


@router.get("/{payment_id}/pdf")
def download_payment_pdf(
    payment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id, Payment.status == "active")
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    company = db.query(CompanyProfile).first()

    html = _build_receipt_html(payment, company)
    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    buf = BytesIO(pdf_bytes)

    filename = f"receipt_{payment.payment_number or payment_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
