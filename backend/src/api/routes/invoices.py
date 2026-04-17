from io import BytesIO
from html import escape
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func
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
from src.services.series import generate_next_number
from src.services.financial_year import get_active_fy, get_fy_for_date

router = APIRouter()


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_interstate_supply(company_gst: str | None, ledger_gst: str | None) -> bool:
    if not company_gst or not ledger_gst or len(company_gst) < 2 or len(ledger_gst) < 2:
        return False
    return company_gst[:2] != ledger_gst[:2]


def _extract_pan_from_gstin(gstin: str | None) -> str | None:
    normalized = (gstin or "").strip().upper()
    if len(normalized) != 15:
        return None
    return normalized[2:12]


def _generate_next_number(
    db: Session,
    voucher_type: str,
    financial_year_id: int | None = None,
    invoice_date: date | None = None,
    active_financial_year_id: int | None = None,
) -> str:
    return generate_next_number(db, voucher_type, financial_year_id, invoice_date, active_financial_year_id)


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


def _assign_item_tax_split(
    items: list[InvoiceItem],
    *,
    interstate_supply: bool,
) -> None:
    if not items:
        return

    if interstate_supply:
        for item in items:
            item_tax_amount = _money(Decimal(str(item.tax_amount or 0)))
            item_igst_amount = item_tax_amount
            taxable_amount = _money(Decimal(str(item.taxable_amount or 0)))

            item.tax_amount = float(item_igst_amount)
            item.line_total = float(_money(taxable_amount + item_igst_amount))
            item.cgst_amount = 0.0
            item.sgst_amount = 0.0
            item.igst_amount = float(item_igst_amount)
        return

    for item in items:
        item_tax_amount = _money(Decimal(str(item.tax_amount or 0)))
        item_half_tax_amount = _money(item_tax_amount / Decimal("2"))
        item_cgst_amount = item_half_tax_amount
        item_sgst_amount = item_half_tax_amount
        item_total_tax_amount = _money(item_cgst_amount + item_sgst_amount)
        taxable_amount = _money(Decimal(str(item.taxable_amount or 0)))

        item.tax_amount = float(item_total_tax_amount)
        item.line_total = float(_money(taxable_amount + item_total_tax_amount))
        item.cgst_amount = float(item_cgst_amount)
        item.sgst_amount = float(item_sgst_amount)
        item.igst_amount = 0.0


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
    financial_year_id: int | None = None,
    active_financial_year_id: int | None = None,
    regenerate_number: bool = True,
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
    invoice.supplier_invoice_number = payload.supplier_invoice_number
    if created_by is not None:
        invoice.created_by = created_by
    if financial_year_id is not None:
        invoice.financial_year_id = financial_year_id

    if payload.invoice_date is not None:
        invoice.invoice_date = datetime.combine(payload.invoice_date, datetime.min.time())

    if payload.due_date is not None:
        invoice.due_date = datetime.combine(payload.due_date, datetime.min.time())

    invoice.tax_inclusive = payload.tax_inclusive
    invoice.apply_round_off = payload.apply_round_off
    if regenerate_number:
        invoice.invoice_number = _generate_next_number(
            db, invoice.voucher_type, financial_year_id, payload.invoice_date,
            active_financial_year_id,
        )

    if not payload.items:
        raise HTTPException(status_code=400, detail="Invoice must have at least one line item")

    interstate_supply = _is_interstate_supply(invoice.company_gst, invoice.ledger_gst)

    taxable_total = Decimal("0")
    tax_total = Decimal("0")
    created_items: list[InvoiceItem] = []
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

        if payload.tax_inclusive:
            # Entered price already includes tax; back-calculate taxable amount
            line_total = _money(unit_price * Decimal(item.quantity))
            taxable_amount = _money(line_total / (1 + gst_rate / Decimal("100")))
            tax_amount = _money(line_total - taxable_amount)
        else:
            taxable_amount = _money(unit_price * Decimal(item.quantity))
            tax_amount = _money(taxable_amount * gst_rate / Decimal("100"))
            line_total = _money(taxable_amount + tax_amount)

        taxable_total += taxable_amount
        tax_total += tax_amount

        invoice_item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            quantity=item.quantity,
            hsn_sac=product.hsn_sac,
            unit_price=float(unit_price),
            gst_rate=float(gst_rate),
            taxable_amount=float(taxable_amount),
            tax_amount=float(tax_amount),
            line_total=float(line_total),
            description=item.description,
        )
        created_items.append(invoice_item)
        db.add(invoice_item)

    taxable_total = _money(taxable_total)
    invoice.taxable_amount = float(taxable_total)

    _assign_item_tax_split(
        created_items,
        interstate_supply=interstate_supply,
    )

    cgst_total = _money(sum((_money(Decimal(str(item.cgst_amount or 0))) for item in created_items), Decimal("0")))
    sgst_total = _money(sum((_money(Decimal(str(item.sgst_amount or 0))) for item in created_items), Decimal("0")))
    igst_total = _money(sum((_money(Decimal(str(item.igst_amount or 0))) for item in created_items), Decimal("0")))

    if interstate_supply:
        invoice.cgst_amount = 0.0
        invoice.sgst_amount = 0.0
        invoice.igst_amount = float(igst_total)
    else:
        invoice.cgst_amount = float(cgst_total)
        invoice.sgst_amount = float(sgst_total)
        invoice.igst_amount = 0.0

    tax_total = _money(cgst_total + sgst_total + igst_total)
    invoice.total_tax_amount = float(tax_total)
    raw_total = _money(taxable_total + tax_total)
    if invoice.apply_round_off:
        rounded_total = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        round_off_amount = _money(rounded_total - raw_total)
        invoice.round_off_amount = float(round_off_amount)
        invoice.total_amount = float(_money(rounded_total))
    else:
        invoice.round_off_amount = 0
        invoice.total_amount = float(raw_total)


@router.post("", response_model=InvoiceOut, include_in_schema=False)
@router.post("/", response_model=InvoiceOut)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        active_fy = get_active_fy(db)

        # Determine which FY this invoice belongs to based on its date.
        # If the invoice date falls within a different FY, use that FY.
        fy_for_invoice = active_fy
        if payload.invoice_date:
            date_fy = get_fy_for_date(db, payload.invoice_date)
            if date_fy is not None:
                fy_for_invoice = date_fy
        fy_id = fy_for_invoice.id if fy_for_invoice else None

        invoice = Invoice(
            total_amount=0,
            created_by=current_user.id,
        )
        db.add(invoice)
        db.flush()
        _apply_payload_to_invoice(
            db, invoice, payload,
            created_by=current_user.id,
            financial_year_id=fy_id,
            active_financial_year_id=active_fy.id if active_fy else None,
        )
        db.commit()
        db.refresh(invoice)

        warnings: list[str] = []
        if active_fy and payload.invoice_date:
            inv_date = payload.invoice_date
            if not (active_fy.start_date <= inv_date <= active_fy.end_date):
                warnings.append("invoice_date_outside_fy")

        result = InvoiceOut.model_validate(invoice)
        result.warnings = warnings
        return result
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
    show_cancelled: bool = Query(False),
    financial_year_id: int | None = Query(None),
    product_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        base = db.query(Invoice)
        if not show_cancelled:
            base = base.filter(Invoice.status == "active")
        if financial_year_id is not None:
            base = base.filter(Invoice.financial_year_id == financial_year_id)
        if search.strip():
            base = base.filter(Invoice.ledger_name.ilike(f"%{search.strip()}%"))
        if product_id is not None:
            product_subq = db.query(InvoiceItem.invoice_id).filter(InvoiceItem.product_id == product_id).subquery()
            base = base.filter(Invoice.id.in_(product_subq))

        summary_row = base.with_entities(
          func.coalesce(func.sum(Invoice.total_amount), 0),
          func.coalesce(func.sum(case((Invoice.voucher_type == "purchase", Invoice.total_amount), else_=0)), 0),
          func.coalesce(func.sum(case((Invoice.voucher_type == "sales", Invoice.total_amount), else_=0)), 0),
          func.coalesce(func.sum(case((Invoice.status == "cancelled", Invoice.total_amount), else_=0)), 0),
          func.coalesce(func.sum(case((Invoice.status == "active", Invoice.total_amount), else_=0)), 0),
        ).one()

        total_listed = Decimal(summary_row[0] or 0)
        credit_total = Decimal(summary_row[1] or 0)
        debit_total = Decimal(summary_row[2] or 0)
        cancelled_total = Decimal(summary_row[3] or 0)
        active_total = Decimal(summary_row[4] or 0)
        others_total = total_listed - (credit_total + debit_total + cancelled_total)

        total = base.count()
        items = (
            base.options(joinedload(Invoice.ledger), joinedload(Invoice.items))
            .order_by(Invoice.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        visible_page_total = sum((Decimal(item.total_amount or 0) for item in items), Decimal("0"))

        return PaginatedInvoiceOut(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
          summary=PaginatedInvoiceOut.SummaryMeta(
            total_listed=float(total_listed),
            credit_total=float(credit_total),
            debit_total=float(debit_total),
            cancelled_total=float(cancelled_total),
            active_total=float(active_total),
            others_total=float(others_total),
            visible_page_total=float(visible_page_total),
            visible_page_count=len(items),
            filtered_count=total,
            include_cancelled=show_cancelled,
            financial_year_id=financial_year_id,
          ),
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

    if invoice.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Cancelled invoices cannot be edited. Restore the invoice first.",
        )

    try:
        active_fy = get_active_fy(db)

        _reverse_existing_invoice_inventory(db, invoice)

        for item in list(invoice.items):
            db.delete(item)
        db.flush()

        _apply_payload_to_invoice(
            db, invoice, payload,
            regenerate_number=False,
        )
        db.commit()
        db.refresh(invoice)

        warnings: list[str] = []
        if active_fy and payload.invoice_date:
            inv_date = payload.invoice_date
            if not (active_fy.start_date <= inv_date <= active_fy.end_date):
                warnings.append("invoice_date_outside_fy")

        result = InvoiceOut.model_validate(invoice)
        result.warnings = warnings
        return result
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


def _amount_in_words_indian(amount: float, currency_code: str | None = None) -> str:
    """Convert a monetary amount to words using the Indian numbering system (crores/lakhs)."""
    _ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven',
             'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen',
             'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
    _TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _two(n: int) -> str:
        if n < 20:
            return _ONES[n]
        return _TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '')

    def _three(n: int) -> str:
        if n == 0:
            return ''
        if n < 100:
            return _two(n)
        return _ONES[n // 100] + ' Hundred' + (' ' + _two(n % 100) if n % 100 else '')

    try:
        amount = round(amount, 2)
        rupees = int(amount)
        paise = round((amount - rupees) * 100)
        currency_label = 'Rupees' if not currency_code or currency_code == 'INR' else currency_code

        if rupees == 0 and paise == 0:
            return f'Zero {currency_label} Only'

        parts: list[str] = []
        n = rupees
        crores = n // 10_000_000
        n %= 10_000_000
        lakhs = n // 100_000
        n %= 100_000
        thousands = n // 1000
        remainder = n % 1000

        if crores:
            parts.append(_three(crores) + ' Crore')
        if lakhs:
            parts.append(_two(lakhs) + ' Lakh')
        if thousands:
            parts.append(_two(thousands) + ' Thousand')
        if remainder:
            parts.append(_three(remainder))

        rupee_words = ' '.join(parts) if parts else 'Zero'
        result = f'{rupee_words} {currency_label}'
        if paise:
            result += f' and {_two(paise)} Paise'
        return result + ' Only'
    except Exception:
        return ''


def _fmt_rate(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _build_pdf_tax_header_cells(interstate_supply: bool) -> str:
    if interstate_supply:
        return '<th class="right">IGST %</th><th class="right">IGST Amt</th><th class="right">Total Tax</th>'
    return (
        '<th class="right">SGST %</th>'
        '<th class="right">SGST Amt</th>'
        '<th class="right">CGST %</th>'
        '<th class="right">CGST Amt</th>'
        '<th class="right">Total Tax</th>'
    )


def _build_pdf_tax_row_cells(item: InvoiceItem, currency: str, interstate_supply: bool) -> str:
    gst_rate = float(item.gst_rate or 0)
    tax_amount = float(item.tax_amount or 0)

    if interstate_supply:
        igst_amount = float(item.igst_amount or 0)
        if tax_amount > 0 and igst_amount == 0:
            igst_amount = tax_amount
        igst_rate = gst_rate if igst_amount > 0 else 0
        return (
            f'<td class="right">{_fmt_rate(igst_rate)}%</td>'
        f'<td class="right">{_fmt_currency(igst_amount, currency)}</td>'
            f'<td class="right">{_fmt_currency(tax_amount, currency)}</td>'
        )

    sgst_amount = float(item.sgst_amount or 0)
    cgst_amount = float(item.cgst_amount or 0)
    if tax_amount > 0 and sgst_amount == 0 and cgst_amount == 0:
      cgst_amount = float(_money(Decimal(str(tax_amount)) / Decimal("2")))
      sgst_amount = float(_money(Decimal(str(tax_amount)) - Decimal(str(cgst_amount))))

    split_rate = gst_rate / 2 if (tax_amount > 0 or sgst_amount > 0 or cgst_amount > 0) else 0
    return (
        f'<td class="right">{_fmt_rate(split_rate)}%</td>'
      f'<td class="right">{_fmt_currency(sgst_amount, currency)}</td>'
        f'<td class="right">{_fmt_rate(split_rate)}%</td>'
      f'<td class="right">{_fmt_currency(cgst_amount, currency)}</td>'
        f'<td class="right">{_fmt_currency(tax_amount, currency)}</td>'
    )


def _build_pdf_tax_breakup_rows(invoice: Invoice, currency: str) -> str:
  cgst = float(invoice.cgst_amount or 0)
  sgst = float(invoice.sgst_amount or 0)
  igst = float(invoice.igst_amount or 0)

  # GST display rule for PDFs: show either IGST or CGST+SGST.
  if igst > 0:
    return f"<p>IGST: {_fmt_currency(igst, currency)}</p>"
  return (
    f"<p>CGST: {_fmt_currency(cgst, currency)}</p>"
    f"<p>SGST: {_fmt_currency(sgst, currency)}</p>"
  )


def _build_purchase_invoice_html(invoice: Invoice, products: list[Product]) -> str:
    """Generate HTML for a purchase invoice (supplier at top-left, your company top-right,
    no bank details in footer, optional supplier ref row)."""
    currency = invoice.company_currency_code or "USD"
    inv_number = invoice.invoice_number or f"#{invoice.id}"
    inv_date = invoice.invoice_date.strftime("%d %b %Y") if invoice.invoice_date else (invoice.created_at.strftime("%d %b %Y") if invoice.created_at else "N/A")
    interstate_supply = _is_interstate_supply(invoice.company_gst, invoice.ledger_gst)
    tax_header_cells = _build_pdf_tax_header_cells(interstate_supply)

    product_map = {p.id: p for p in products}

    item_rows = ""
    for idx, item in enumerate(invoice.items or [], start=1):
        prod = product_map.get(item.product_id)
        product_name = _e(prod.name) if prod else f"Product #{item.product_id}"
        item_description = _e(item.description)
        product_cell_html = product_name
        if item_description:
            product_cell_html = f"{product_name}<br><span class=\"muted-text\">{item_description}</span>"
        sku = _e(prod.sku) if prod else "N/A"
        hsn = _e(item.hsn_sac or (prod.hsn_sac if prod else None) or "N/A")
        tax_row_cells = _build_pdf_tax_row_cells(item, currency, interstate_supply)

        item_rows += f"""
        <tr>
          <td>{idx}</td>
          <td>{product_cell_html}</td>
          <td>{sku}</td>
          <td>{hsn}</td>
          <td class="right">{item.quantity}</td>
          <td class="right">{_fmt_currency(float(item.unit_price), currency)}</td>
          {tax_row_cells}
          <td class="right">{_fmt_currency(float(item.line_total), currency)}</td>
        </tr>"""

    # Supplier details are stored as ledger_* (buyer_* in DB) on purchase invoices
    supplier_detail_parts = []
    if invoice.ledger_gst:
        supplier_detail_parts.append(f"GST: {_e(invoice.ledger_gst)}")
        supplier_pan = _extract_pan_from_gstin(invoice.ledger_gst)
        if supplier_pan:
            supplier_detail_parts.append(f"PAN: {_e(supplier_pan)}")
    if invoice.ledger_phone:
        supplier_detail_parts.append(f"Phone: {_e(invoice.ledger_phone)}")
    supplier_details = " &middot; ".join(supplier_detail_parts)

    # Your company (receiving / bill-to party)
    company_detail_parts = []
    if invoice.company_gst:
        company_detail_parts.append(f"GST: {_e(invoice.company_gst)}")
        company_pan = _extract_pan_from_gstin(invoice.company_gst)
        if company_pan:
            company_detail_parts.append(f"PAN: {_e(company_pan)}")
    company_details = " &middot; ".join(company_detail_parts)

    # Optional supplier reference row
    supplier_ref_html = ""
    if invoice.supplier_invoice_number:
        supplier_ref_html = f"""
  <section class="invoice-sheet__supplierref">
    <span class="eyebrow">Supplier Ref:</span>
    <span class="invoice-sheet__supplierref-value">{_e(invoice.supplier_invoice_number)}</span>
  </section>"""

    round_off_amount = float(invoice.round_off_amount or 0)
    show_round_off = bool(invoice.apply_round_off and round_off_amount != 0)
    round_off_html = (
        f'<p>Round off: {_fmt_currency(round_off_amount, currency)}</p>' if show_round_off else ''
    )
    tax_breakup_rows = _build_pdf_tax_breakup_rows(invoice, currency)

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
    margin-bottom: 12px;
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
  .invoice-sheet__header-right {{
    text-align: right;
  }}
  .invoice-sheet__header-right h3 {{
    font-size: 14px;
  }}
  .invoice-sheet__titleblock {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    padding: 10px 14px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
  }}
  .invoice-sheet__titleblock h2 {{
    font-size: 14px;
    font-weight: 700;
  }}
  .invoice-sheet__titleblock p {{
    font-size: 9px;
    color: #6b7280;
    margin-left: auto;
  }}
  .invoice-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #065f46;
    background: #ecfdf5;
  }}
  .invoice-sheet__supplierref {{
    margin-bottom: 12px;
    font-size: 9px;
    color: #374151;
  }}
  .invoice-sheet__supplierref-value {{
    font-size: 9px;
    font-weight: 600;
    color: #1f2937;
    margin-left: 4px;
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
    justify-content: flex-end;
    margin-top: 8px;
  }}
  .invoice-sheet__totals {{
    text-align: right;
    min-width: 220px;
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
  .invoice-amount-words {{
    font-size: 8px;
    font-style: italic;
    color: #374151;
    margin-top: 2px;
  }}
</style>
</head>
<body>
<div class="invoice-sheet">
  <header class="invoice-sheet__header">
    <div>
      <p class="eyebrow">Supplier</p>
      <h3>{_e(invoice.ledger_name) or 'Unknown supplier'}</h3>
      <p>{_e(invoice.ledger_address) or 'Address not provided'}</p>
      <p>{supplier_details}</p>
    </div>
    <div class="invoice-sheet__header-right">
      <p class="eyebrow">Bill To</p>
      <h3>{_e(invoice.company_name) or 'Your company'}</h3>
      <p>{_e(invoice.company_address) or 'Address not provided'}</p>
      <p>{company_details}</p>
    </div>
  </header>

  <div class="invoice-sheet__titleblock">
    <span class="invoice-badge">Purchase Invoice</span>
    <h2>Invoice {_e(inv_number)}</h2>
    <p>Date: {inv_date} &nbsp;&middot;&nbsp; Currency: {_e(currency)}</p>
  </div>
{supplier_ref_html}
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
          {tax_header_cells}
          <th class="right">Amount</th>
        </tr>
      </thead>
      <tbody>
        {item_rows}
      </tbody>
    </table>
  </section>

  <section class="invoice-sheet__footer">
    <div class="invoice-sheet__totals">
      <p class="eyebrow">Tax breakup</p>
      <p>Taxable: {_fmt_currency(float(invoice.taxable_amount or 0), currency)}</p>
      {tax_breakup_rows}
      <p>Total tax: {_fmt_currency(float(invoice.total_tax_amount or 0), currency)}</p>
      {round_off_html}
      <p class="eyebrow" style="margin-top: 10px;">Total due</p>
      <p class="invoice-sheet__total-value">{_fmt_currency(float(invoice.total_amount), currency)}</p>
      <p class="invoice-amount-words">{_amount_in_words_indian(float(invoice.total_amount), currency)}</p>
      <p class="muted-text">Received by {_e(invoice.company_name) or 'Your company'}</p>
    </div>
  </section>
</div>
</body>
</html>"""
    return html


def _build_invoice_html(invoice: Invoice, products: list[Product]) -> str:
    if invoice.voucher_type == "purchase":
        return _build_purchase_invoice_html(invoice, products)

    currency = invoice.company_currency_code or "USD"
    voucher_label = "Sales" if invoice.voucher_type == "sales" else "Purchase"
    inv_number = invoice.invoice_number or f"#{invoice.id}"
    inv_date = invoice.invoice_date.strftime("%d %b %Y") if invoice.invoice_date else (invoice.created_at.strftime("%d %b %Y") if invoice.created_at else "N/A")
    interstate_supply = _is_interstate_supply(invoice.company_gst, invoice.ledger_gst)
    tax_header_cells = _build_pdf_tax_header_cells(interstate_supply)

    product_map = {p.id: p for p in products}

    # Build line item rows
    item_rows = ""
    for idx, item in enumerate(invoice.items or [], start=1):
        prod = product_map.get(item.product_id)
        product_name = _e(prod.name) if prod else f"Product #{item.product_id}"
        item_description = _e(item.description)
        product_cell_html = product_name
        if item_description:
            product_cell_html = f"{product_name}<br><span class=\"muted-text\">{item_description}</span>"
        sku = _e(prod.sku) if prod else "N/A"
        hsn = _e(item.hsn_sac or (prod.hsn_sac if prod else None) or "N/A")
        tax_row_cells = _build_pdf_tax_row_cells(item, currency, interstate_supply)

        item_rows += f"""
        <tr>
          <td>{idx}</td>
          <td>{product_cell_html}</td>
          <td>{sku}</td>
          <td>{hsn}</td>
          <td class="right">{item.quantity}</td>
          <td class="right">{_fmt_currency(float(item.unit_price), currency)}</td>
          {tax_row_cells}
          <td class="right">{_fmt_currency(float(item.line_total), currency)}</td>
        </tr>"""

    # Company details
    company_detail_parts = []
    if invoice.company_gst:
        company_detail_parts.append(f"GST: {_e(invoice.company_gst)}")
        company_pan = _extract_pan_from_gstin(invoice.company_gst)
        if company_pan:
            company_detail_parts.append(f"PAN: {_e(company_pan)}")
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
        billto_pan = _extract_pan_from_gstin(invoice.ledger_gst)
        if billto_pan:
            billto_parts.append(f"PAN: {_e(billto_pan)}")
    if invoice.ledger_phone:
        billto_parts.append(f"Phone: {_e(invoice.ledger_phone)}")
    billto_details = " &middot; ".join(billto_parts)

    round_off_amount = float(invoice.round_off_amount or 0)
    show_round_off = bool(invoice.apply_round_off and round_off_amount != 0)
    round_off_html = (
        f'<p>Round off: {_fmt_currency(round_off_amount, currency)}</p>' if show_round_off else ''
    )
    tax_breakup_rows = _build_pdf_tax_breakup_rows(invoice, currency)

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
  .invoice-amount-words {{
    font-size: 8px;
    font-style: italic;
    color: #374151;
    margin-top: 2px;
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
          {tax_header_cells}
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
      {tax_breakup_rows}
      <p>Total tax: {_fmt_currency(float(invoice.total_tax_amount or 0), currency)}</p>
      {round_off_html}
      <p class="eyebrow" style="margin-top: 10px;">Total due</p>
      <p class="invoice-sheet__total-value">{_fmt_currency(float(invoice.total_amount), currency)}</p>
      <p class="invoice-amount-words">{_amount_in_words_indian(float(invoice.total_amount), currency)}</p>
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


@router.delete("/{invoice_id}", response_model=InvoiceOut)
def cancel_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    invoice = db.query(Invoice).options(joinedload(Invoice.items)).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    if invoice.status == "cancelled":
        raise HTTPException(status_code=400, detail="Invoice is already cancelled")

    try:
        _reverse_existing_invoice_inventory(db, invoice)
        invoice.status = "cancelled"
        db.commit()
        db.refresh(invoice)
        return invoice
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{invoice_id}/restore", response_model=InvoiceOut)
def restore_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    invoice = db.query(Invoice).options(joinedload(Invoice.items)).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    if invoice.status != "cancelled":
        raise HTTPException(status_code=400, detail="Invoice is not cancelled")

    try:
        # Re-apply inventory changes (reverse the reversal)
        for item in invoice.items:
            restore_delta = -item.quantity if invoice.voucher_type == "sales" else item.quantity
            _change_inventory_quantity(
                db,
                item.product_id,
                restore_delta,
                context=f"restoring invoice {invoice.id}",
            )
        invoice.status = "active"
        db.commit()
        db.refresh(invoice)
        return invoice
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
