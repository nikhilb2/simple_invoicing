from io import BytesIO
from html import escape
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
from decimal import Decimal, ROUND_HALF_UP

import weasyprint

from fastapi import Query

from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.invoice import Invoice, InvoiceItem
from src.models.inventory import Inventory
from src.models.product import Product
from src.models.user import User
from src.schemas.invoice import InvoiceCreate, InvoiceOut, PaginatedInvoiceOut
from src.api.deps import get_current_user

router = APIRouter()


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_interstate_supply(company_gst: str | None, ledger_gst: str | None) -> bool:
    if not company_gst or not ledger_gst or len(company_gst) < 2 or len(ledger_gst) < 2:
        return False
    return company_gst[:2] != ledger_gst[:2]


def _generate_invoice_number(invoice_id: int) -> str:
    return f"INV-{invoice_id:06d}"


def _require_ledger(db: Session, ledger_id: int) -> Ledger:
    ledger = db.query(Ledger).filter(Ledger.id == ledger_id).first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")
    return ledger


def _change_inventory_quantity(db: Session, product_id: int, quantity_delta: int, *, context: str) -> None:
    inventory = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if not inventory:
        inventory = Inventory(product_id=product_id, quantity=0)
        db.add(inventory)
        db.flush()

    inventory.quantity += quantity_delta
    if inventory.quantity < 0:
        raise HTTPException(status_code=400, detail=f"Insufficient inventory while {context}")


def _reverse_existing_invoice_inventory(db: Session, invoice: Invoice) -> None:
    for item in invoice.items:
        reverse_delta = item.quantity if invoice.voucher_type == "sales" else -item.quantity
        _change_inventory_quantity(
            db,
            item.product_id,
            reverse_delta,
            context=f"reversing invoice {invoice.id}",
        )


def _apply_payload_to_invoice(
    db: Session,
    invoice: Invoice,
    payload: InvoiceCreate,
    created_by: int | None = None,
) -> None:
    ledger = _require_ledger(db, payload.ledger_id)
    company = db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()

    invoice.ledger_id = ledger.id
    invoice.ledger_name = ledger.name
    invoice.ledger_address = ledger.address
    invoice.ledger_gst = ledger.gst
    invoice.ledger_phone = ledger.phone_number
    invoice.company_name = company.name if company else None
    invoice.company_address = company.address if company else None
    invoice.company_gst = company.gst if company else None
    invoice.company_phone = company.phone_number if company else None
    invoice.company_email = company.email if company else None
    invoice.company_website = company.website if company else None
    invoice.company_currency_code = company.currency_code if company else None
    invoice.company_bank_name = company.bank_name if company else None
    invoice.company_branch_name = company.branch_name if company else None
    invoice.company_account_name = company.account_name if company else None
    invoice.company_account_number = company.account_number if company else None
    invoice.company_ifsc_code = company.ifsc_code if company else None
    invoice.voucher_type = payload.voucher_type
    if created_by is not None:
        invoice.created_by = created_by

    if payload.invoice_date is not None:
        invoice.invoice_date = datetime.combine(payload.invoice_date, datetime.min.time())

    invoice.invoice_number = _generate_invoice_number(invoice.id)

    if not invoice.company_gst or not invoice.ledger_gst:
        raise HTTPException(
            status_code=400,
            detail="Company GSTIN and ledger GSTIN are required before creating an invoice",
        )

    if not payload.items:
        raise HTTPException(status_code=400, detail="Invoice must have at least one line item")

    interstate_supply = _is_interstate_supply(invoice.company_gst, invoice.ledger_gst)

    taxable_total = Decimal("0")
    tax_total = Decimal("0")
    cgst_total = Decimal("0")
    sgst_total = Decimal("0")
    igst_total = Decimal("0")
    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="Item quantity must be greater than zero")

        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

        inventory = db.query(Inventory).filter(Inventory.product_id == item.product_id).first()
        if payload.voucher_type == "sales" and (not inventory or inventory.quantity < item.quantity):
            raise HTTPException(status_code=400, detail=f"Insufficient inventory for {product.name}")

        quantity_delta = -item.quantity if payload.voucher_type == "sales" else item.quantity
        _change_inventory_quantity(
            db,
            item.product_id,
            quantity_delta,
            context=f"applying invoice {invoice.id or 'new'}",
        )

        # Use custom unit_price if provided, otherwise use product price.
        # GST rate is snapshotted from the product at invoice time.
        unit_price = Decimal(str(item.unit_price)) if item.unit_price is not None else Decimal(str(product.price))
        gst_rate = Decimal(str(product.gst_rate or 0))
        taxable_amount = _money(unit_price * Decimal(item.quantity))
        tax_amount = _money(taxable_amount * gst_rate / Decimal("100"))
        line_total = _money(taxable_amount + tax_amount)

        if interstate_supply:
            igst_amount = tax_amount
            cgst_amount = Decimal("0")
            sgst_amount = Decimal("0")
        else:
            half_tax = _money(tax_amount / Decimal("2"))
            cgst_amount = half_tax
            sgst_amount = _money(tax_amount - half_tax)
            igst_amount = Decimal("0")

        taxable_total += taxable_amount
        tax_total += tax_amount
        cgst_total += cgst_amount
        sgst_total += sgst_amount
        igst_total += igst_amount

        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                product_id=product.id,
                quantity=item.quantity,
                hsn_sac=product.hsn_sac,
                unit_price=float(unit_price),
                gst_rate=float(gst_rate),
                taxable_amount=float(taxable_amount),
                tax_amount=float(tax_amount),
                line_total=float(line_total),
            )
        )

    invoice.taxable_amount = float(_money(taxable_total))
    invoice.total_tax_amount = float(_money(tax_total))
    invoice.cgst_amount = float(_money(cgst_total))
    invoice.sgst_amount = float(_money(sgst_total))
    invoice.igst_amount = float(_money(igst_total))
    invoice.total_amount = float(_money(taxable_total + tax_total))


@router.post("", response_model=InvoiceOut, include_in_schema=False)
@router.post("/", response_model=InvoiceOut)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        invoice = Invoice(
            total_amount=0,
            created_by=current_user.id,
        )
        db.add(invoice)
        db.flush()
        _apply_payload_to_invoice(db, invoice, payload, created_by=current_user.id)
        db.commit()
        db.refresh(invoice)
        return invoice
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        print(f"Error creating invoice: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=PaginatedInvoiceOut, include_in_schema=False)
@router.get("/", response_model=PaginatedInvoiceOut)
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        base = db.query(Invoice)
        if search.strip():
            base = base.filter(Invoice.ledger_name.ilike(f"%{search.strip()}%"))
        total = base.count()
        items = (
            base.options(joinedload(Invoice.ledger), joinedload(Invoice.items))
            .order_by(Invoice.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return PaginatedInvoiceOut(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.ledger), joinedload(Invoice.items))
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    return invoice


@router.put("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: int,
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    invoice = db.query(Invoice).options(joinedload(Invoice.items)).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    try:
        _reverse_existing_invoice_inventory(db, invoice)

        for item in list(invoice.items):
            db.delete(item)
        db.flush()

        _apply_payload_to_invoice(db, invoice, payload)
        db.commit()
        db.refresh(invoice)
        return invoice
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


def _fmt_currency(value: float, currency_code: str | None = None) -> str:
    code = currency_code or "USD"
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


def _e(text: str | None) -> str:
    return escape(text or "")


def _build_invoice_html(invoice: Invoice, products: list[Product]) -> str:
    currency = invoice.company_currency_code or "USD"
    voucher_label = "Sales" if invoice.voucher_type == "sales" else "Purchase"
    inv_number = invoice.invoice_number or f"#{invoice.id}"
    inv_date = invoice.invoice_date.strftime("%d %b %Y") if invoice.invoice_date else (invoice.created_at.strftime("%d %b %Y") if invoice.created_at else "N/A")

    product_map = {p.id: p for p in products}

    # Build line item rows
    item_rows = ""
    for idx, item in enumerate(invoice.items or [], start=1):
        prod = product_map.get(item.product_id)
        product_name = _e(prod.name) if prod else f"Product #{item.product_id}"
        sku = _e(prod.sku) if prod else "N/A"
        hsn = _e(item.hsn_sac or (prod.hsn_sac if prod else None) or "N/A")
        gst_rate = float(item.gst_rate or 0)
        taxable_amt = float(item.taxable_amount or (float(item.unit_price) * item.quantity))
        tax_amt = float(item.tax_amount or (taxable_amt * gst_rate / 100))

        item_rows += f"""
        <tr>
          <td>{idx}</td>
          <td>{product_name}</td>
          <td>{sku}</td>
          <td>{hsn}</td>
          <td class="right">{item.quantity}</td>
          <td class="right">{_fmt_currency(float(item.unit_price), currency)}</td>
          <td class="right">{gst_rate:.2f}%</td>
          <td class="right">{_fmt_currency(tax_amt, currency)}</td>
          <td class="right">{_fmt_currency(float(item.line_total), currency)}</td>
        </tr>"""

    # Company details
    company_detail_parts = []
    if invoice.company_gst:
        company_detail_parts.append(f"GST: {_e(invoice.company_gst)}")
    if invoice.company_phone:
        company_detail_parts.append(f"Phone: {_e(invoice.company_phone)}")
    company_details = " &middot; ".join(company_detail_parts)

    company_contact_parts = []
    if invoice.company_email:
        company_contact_parts.append(f"Email: {_e(invoice.company_email)}")
    if invoice.company_website:
        company_contact_parts.append(f"Web: {_e(invoice.company_website)}")
    company_contact = " &middot; ".join(company_contact_parts)

    # Bill-to details
    billto_parts = []
    if invoice.ledger_gst:
        billto_parts.append(f"GST: {_e(invoice.ledger_gst)}")
    if invoice.ledger_phone:
        billto_parts.append(f"Phone: {_e(invoice.ledger_phone)}")
    billto_details = " &middot; ".join(billto_parts)

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
  .invoice-sheet {{
    width: 100%;
  }}
  .invoice-sheet__header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 16px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 16px;
  }}
  .invoice-sheet__header h3 {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .invoice-sheet__header p {{
    font-size: 9px;
    color: #6b7280;
    margin-bottom: 1px;
  }}
  .invoice-sheet__meta {{
    text-align: right;
  }}
  .invoice-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #1a56db;
    background: #eff6ff;
    margin-bottom: 6px;
  }}
  .invoice-sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .invoice-sheet__meta p {{
    font-size: 9px;
    color: #6b7280;
  }}
  .invoice-sheet__billto {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 16px;
  }}
  .invoice-sheet__billto h4 {{
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 2px;
  }}
  .invoice-sheet__billto p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .invoice-sheet__table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 16px;
    font-size: 9px;
  }}
  .invoice-sheet__table thead th {{
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
  .invoice-sheet__table thead th.right {{
    text-align: right;
  }}
  .invoice-sheet__table tbody td {{
    padding: 6px 8px;
    border-bottom: 1px solid #e5e7eb;
    vertical-align: middle;
  }}
  .invoice-sheet__table tbody td.right {{
    text-align: right;
  }}
  .invoice-sheet__table tbody tr:last-child td {{
    border-bottom: 2px solid #d1d5db;
  }}
  .invoice-sheet__footer {{
    display: flex;
    justify-content: space-between;
    gap: 24px;
    margin-top: 8px;
  }}
  .invoice-sheet__bank {{
    flex: 1;
  }}
  .invoice-sheet__bank p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .invoice-sheet__totals {{
    flex: 1;
    text-align: right;
  }}
  .invoice-sheet__totals p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .invoice-sheet__total-value {{
    font-size: 20px !important;
    font-weight: 700;
    color: #1a56db !important;
    margin-top: 4px;
    margin-bottom: 4px;
  }}
  .muted-text {{
    font-size: 8px;
    color: #9ca3af;
  }}
</style>
</head>
<body>
<div class="invoice-sheet">
  <header class="invoice-sheet__header">
    <div>
      <p class="eyebrow">Billed by</p>
      <h3>{_e(invoice.company_name) or 'Company not set'}</h3>
      <p>{_e(invoice.company_address) or 'Address not provided'}</p>
      <p>{company_details}</p>
      <p>{company_contact}</p>
    </div>
    <div class="invoice-sheet__meta">
      <span class="invoice-badge">{voucher_label}</span>
      <h2>Invoice {_e(inv_number)}</h2>
      <p>Date: {inv_date}</p>
      <p>Currency: {_e(currency)}</p>
    </div>
  </header>

  <section class="invoice-sheet__billto">
    <p class="eyebrow">Bill to</p>
    <h4>{_e(invoice.ledger_name) or 'Unknown ledger'}</h4>
    <p>{_e(invoice.ledger_address) or 'Address not provided'}</p>
    <p>{billto_details}</p>
  </section>

  <section>
    <table class="invoice-sheet__table">
      <thead>
        <tr>
          <th>#</th>
          <th>Item</th>
          <th>SKU</th>
          <th>HSN/SAC</th>
          <th class="right">Qty</th>
          <th class="right">Unit Price</th>
          <th class="right">GST %</th>
          <th class="right">Tax</th>
          <th class="right">Amount</th>
        </tr>
      </thead>
      <tbody>
        {item_rows}
      </tbody>
    </table>
  </section>

  <section class="invoice-sheet__footer">
    <div class="invoice-sheet__bank">
      <p class="eyebrow">Payment details</p>
      <p>Bank: {_e(invoice.company_bank_name) or 'N/A'}</p>
      <p>Branch: {_e(invoice.company_branch_name) or 'N/A'}</p>
      <p>Account: {_e(invoice.company_account_name) or 'N/A'}</p>
      <p>A/C No: {_e(invoice.company_account_number) or 'N/A'}</p>
      <p>IFSC: {_e(invoice.company_ifsc_code) or 'N/A'}</p>
    </div>
    <div class="invoice-sheet__totals">
      <p class="eyebrow">Tax breakup</p>
      <p>Taxable: {_fmt_currency(float(invoice.taxable_amount or 0), currency)}</p>
      <p>CGST: {_fmt_currency(float(invoice.cgst_amount or 0), currency)}</p>
      <p>SGST: {_fmt_currency(float(invoice.sgst_amount or 0), currency)}</p>
      <p>IGST: {_fmt_currency(float(invoice.igst_amount or 0), currency)}</p>
      <p>Total tax: {_fmt_currency(float(invoice.total_tax_amount or 0), currency)}</p>
      <p class="eyebrow" style="margin-top: 10px;">Total due</p>
      <p class="invoice-sheet__total-value">{_fmt_currency(float(invoice.total_amount), currency)}</p>
      <p class="muted-text">Authorized by {_e(invoice.company_name) or 'Billing company'}</p>
    </div>
  </section>
</div>
</body>
</html>"""
    return html


def _build_invoice_pdf(invoice: Invoice, products: list[Product]) -> BytesIO:
    html = _build_invoice_html(invoice, products)
    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    buf = BytesIO(pdf_bytes)
    return buf


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.items), joinedload(Invoice.ledger))
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    product_ids = [item.product_id for item in (invoice.items or [])]
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []

    pdf_buffer = _build_invoice_pdf(invoice, products)
    filename = f"invoice_{invoice.invoice_number or invoice.id}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    invoice = db.query(Invoice).options(joinedload(Invoice.items)).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    try:
        _reverse_existing_invoice_inventory(db, invoice)
        db.delete(invoice)
        db.commit()
        return {"message": "Invoice deleted"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
