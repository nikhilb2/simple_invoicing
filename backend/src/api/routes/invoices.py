from io import BytesIO
from datetime import date, datetime
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
from decimal import Decimal, ROUND_HALF_UP

import weasyprint

from fastapi import Query

from src.db.session import get_db
from src.models.buyer import Buyer as Ledger
from src.models.company_account import CompanyAccount
from src.models.company import CompanyProfile
from src.models.invoice import Invoice, InvoiceItem
from src.models.inventory import Inventory
from src.models.product import Product
from src.models.user import User
from src.schemas.invoice import InvoiceCreate, InvoiceOut, PaginatedInvoiceOut
from src.api.deps import get_active_company, get_current_user
from src.services.series import generate_next_number
from src.services.financial_year import get_active_fy, get_fy_for_date
from src.services.invoice_payments import build_invoice_payment_summaries
from src.services.pdf_templates import (
    _build_invoice_html,
    _build_multi_copy_invoice_html,
    _copy_label,
)
from src.services.gst_tax_service import _money, is_interstate_supply, assign_item_tax_split, TaxCalculator

router = APIRouter()




def _generate_next_number(
    db: Session,
    voucher_type: str,
    financial_year_id: int | None = None,
    invoice_date: date | None = None,
    active_financial_year_id: int | None = None,
    company_id: int | None = None,
) -> str:
    return generate_next_number(
        db,
        voucher_type,
        financial_year_id,
        invoice_date,
        active_financial_year_id,
        company_id=company_id,
    )


def _require_ledger(db: Session, ledger_id: int, company_id: int | None) -> Ledger:
    query = db.query(Ledger).filter(Ledger.id == ledger_id)
    if company_id is not None:
        query = query.filter(or_(Ledger.company_id == company_id, Ledger.company_id.is_(None)))
    ledger = query.first()
    if not ledger:
        raise HTTPException(status_code=404, detail=f"Ledger {ledger_id} not found")
    return ledger


def _change_inventory_quantity(
    db: Session,
    product_id: int,
  quantity_delta: Decimal,
    *,
    company_id: int | None,
    context: str,
) -> None:
    query = db.query(Inventory).filter(Inventory.product_id == product_id)
    if company_id is not None:
        query = query.filter(or_(Inventory.company_id == company_id, Inventory.company_id.is_(None)))
    inventory = query.first()
    if not inventory:
        inventory = Inventory(company_id=company_id, product_id=product_id, quantity=0)
        db.add(inventory)
        db.flush()

    inventory.quantity = Decimal(str(inventory.quantity or 0)) + quantity_delta
    if Decimal(str(inventory.quantity or 0)) < 0:
        raise HTTPException(status_code=400, detail=f"Insufficient inventory while {context}")




def _reverse_existing_invoice_inventory(db: Session, invoice: Invoice) -> None:
    for item in invoice.items:
        product_query = db.query(Product).filter(Product.id == item.product_id)
        if invoice.company_id is not None:
            product_query = product_query.filter(or_(Product.company_id == invoice.company_id, Product.company_id.is_(None)))
        product = product_query.first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        if not product.maintain_inventory:
            continue

        reverse_delta = item.quantity if invoice.voucher_type == "sales" else -item.quantity
        _change_inventory_quantity(
            db,
            item.product_id,
            reverse_delta,
            company_id=invoice.company_id,
            context=f"reversing invoice {invoice.id}",
        )


def _inventory_effect_for_voucher_type(quantity: float, voucher_type: str) -> Decimal:
  quantity_value = Decimal(str(quantity))
  return -quantity_value if voucher_type == "sales" else quantity_value


def _apply_inventory_delta_for_invoice_update(
    db: Session,
    invoice: Invoice,
    payload: InvoiceCreate,
    *,
    company_id: int | None,
) -> None:
    existing_effect_by_product: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in invoice.items:
        existing_effect_by_product[item.product_id] += _inventory_effect_for_voucher_type(
            item.quantity,
            invoice.voucher_type,
        )

    next_effect_by_product: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in payload.items:
        next_effect_by_product[item.product_id] += _inventory_effect_for_voucher_type(
            item.quantity,
            payload.voucher_type,
        )

    for product_id in set(existing_effect_by_product) | set(next_effect_by_product):
        quantity_delta = next_effect_by_product[product_id] - existing_effect_by_product[product_id]
        if quantity_delta == 0:
            continue

        product_query = db.query(Product).filter(Product.id == product_id)
        if company_id is not None:
            product_query = product_query.filter(or_(Product.company_id == company_id, Product.company_id.is_(None)))
        product = product_query.first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        if not product.maintain_inventory:
          continue

        _change_inventory_quantity(
            db,
            product_id,
            quantity_delta,
          company_id=company_id,
            context=f"editing invoice {invoice.id}",
        )


def _apply_payload_to_invoice(
    db: Session,
    invoice: Invoice,
    payload: InvoiceCreate,
  active_company: CompanyProfile | None = None,
    created_by: int | None = None,
    financial_year_id: int | None = None,
    active_financial_year_id: int | None = None,
    regenerate_number: bool = True,
    apply_inventory_changes: bool = True,
) -> None:
    company = active_company or db.query(CompanyProfile).order_by(CompanyProfile.id.asc()).first()
    company_id = company.id if company else None
    ledger = _require_ledger(db, payload.ledger_id, company_id)

    invoice.company_id = company_id
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
    invoice.reference_notes = payload.reference_notes
    if created_by is not None:
        invoice.created_by = created_by
    if financial_year_id is not None:
        invoice.financial_year_id = financial_year_id

    if payload.invoice_date is not None:
        invoice.invoice_date = datetime.combine(payload.invoice_date, datetime.min.time())

    invoice.due_date = datetime.combine(payload.due_date, datetime.min.time()) if payload.due_date is not None else None

    invoice.tax_inclusive = payload.tax_inclusive
    invoice.apply_round_off = payload.apply_round_off
    if regenerate_number:
        invoice.invoice_number = _generate_next_number(
            db, invoice.voucher_type, financial_year_id, payload.invoice_date,
            active_financial_year_id,
            company_id=company_id,
        )

    if not payload.items:
        raise HTTPException(status_code=400, detail="Invoice must have at least one line item")

    interstate_supply = is_interstate_supply(invoice.company_gst, invoice.ledger_gst)

    taxable_total = Decimal("0")
    tax_total = Decimal("0")
    created_items: list[InvoiceItem] = []
    for item in payload.items:
        quantity_value = Decimal(str(item.quantity))
        if quantity_value <= 0:
            raise HTTPException(status_code=400, detail="Item quantity must be greater than zero")

        product_query = db.query(Product).filter(Product.id == item.product_id)
        if company_id is not None:
            product_query = product_query.filter(or_(Product.company_id == company_id, Product.company_id.is_(None)))
        product = product_query.first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

        if not product.allow_decimal and quantity_value != quantity_value.to_integral_value():
            raise HTTPException(
                status_code=400,
                detail=f"Quantity for {product.name} must be a whole number",
            )

        if apply_inventory_changes and product.maintain_inventory:
            inventory_query = db.query(Inventory).filter(Inventory.product_id == item.product_id)
            if company_id is not None:
                inventory_query = inventory_query.filter(or_(Inventory.company_id == company_id, Inventory.company_id.is_(None)))
            inventory = inventory_query.first()
            if payload.voucher_type == "sales" and (not inventory or Decimal(str(inventory.quantity or 0)) < quantity_value):
                raise HTTPException(status_code=400, detail=f"Insufficient inventory for {product.name}")

            quantity_delta = _inventory_effect_for_voucher_type(item.quantity, payload.voucher_type)
            _change_inventory_quantity(
                db,
                item.product_id,
                quantity_delta,
                company_id=company_id,
                context=f"applying invoice {invoice.id or 'new'}",
            )

        # Use custom unit_price if provided, otherwise use product price.
        # GST rate is snapshotted from the product at invoice time.
        unit_price = Decimal(str(item.unit_price)) if item.unit_price is not None else Decimal(str(product.price))
        gst_rate = Decimal(str(product.gst_rate or 0))

        if payload.tax_inclusive:
            # Entered price already includes tax; back-calculate taxable amount
            line_total = _money(unit_price * quantity_value)
            taxable_amount = _money(line_total / (1 + gst_rate / Decimal("100")))
            tax_amount = _money(line_total - taxable_amount)
        else:
            taxable_amount = _money(unit_price * quantity_value)
            tax_amount = _money(taxable_amount * gst_rate / Decimal("100"))
            line_total = _money(taxable_amount + tax_amount)

        taxable_total += taxable_amount
        tax_total += tax_amount

        invoice_item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            quantity=float(quantity_value),
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

    assign_item_tax_split(
        created_items,
        interstate_supply=interstate_supply,
    )

    TaxCalculator.assign_invoice_tax_totals(
        invoice,
        created_items,
        interstate_supply=interstate_supply,
    )
    raw_total = _money(taxable_total + Decimal(str(invoice.total_tax_amount)))
    if invoice.apply_round_off:
        rounded_total = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        round_off_amount = _money(rounded_total - raw_total)
        invoice.round_off_amount = float(round_off_amount)
        invoice.total_amount = float(_money(rounded_total))
    else:
        invoice.round_off_amount = 0
        invoice.total_amount = float(raw_total)


def _to_invoice_out(
    invoice: Invoice,
    *,
    payment_summary=None,
) -> InvoiceOut:
    result = InvoiceOut.model_validate(invoice)
    if payment_summary is not None:
        result.paid_amount = payment_summary.paid_amount
        result.remaining_amount = payment_summary.remaining_amount
        result.outstanding_amount = payment_summary.outstanding_amount
        result.payment_status = payment_summary.payment_status
        result.due_in_days = payment_summary.due_in_days
    return result


@router.post("", response_model=InvoiceOut, include_in_schema=False)
@router.post("/", response_model=InvoiceOut)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    try:
        active_fy = get_active_fy(db, company_id=active_company.id)

        # Determine which FY this invoice belongs to based on its date.
        # If the invoice date falls within a different FY, use that FY.
        fy_for_invoice = active_fy
        if payload.invoice_date:
            date_fy = get_fy_for_date(db, payload.invoice_date, company_id=active_company.id)
            if date_fy is not None:
                fy_for_invoice = date_fy
        fy_id = fy_for_invoice.id if fy_for_invoice else None

        invoice = Invoice(
            total_amount=0,
            created_by=current_user.id,
            company_id=active_company.id,
        )
        db.add(invoice)
        db.flush()
        _apply_payload_to_invoice(
            db,
            invoice,
            payload,
            active_company,
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

        summary = build_invoice_payment_summaries(db, [invoice]).get(invoice.id)
        result = _to_invoice_out(invoice, payment_summary=summary)
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
    active_company: CompanyProfile = Depends(get_active_company),
):
    try:
      base = db.query(Invoice).filter(Invoice.company_id == active_company.id)
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
      invoices = (
        base.options(joinedload(Invoice.ledger), joinedload(Invoice.items))
        .order_by(Invoice.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
      )

      payment_summaries = build_invoice_payment_summaries(db, invoices)
      items = [_to_invoice_out(invoice, payment_summary=payment_summaries.get(invoice.id)) for invoice in invoices]

      visible_page_total = sum((Decimal(str(item.total_amount or 0)) for item in items), Decimal("0"))

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


@router.get("/dues", response_model=PaginatedInvoiceOut)
def list_due_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(""),
    ledger_id: int | None = Query(None),
    due_date_from: date | None = Query(None),
    due_date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    try:
        base = (
            db.query(Invoice)
            .options(joinedload(Invoice.ledger), joinedload(Invoice.items))
            .filter(
                Invoice.company_id == active_company.id,
                Invoice.voucher_type == "sales",
                Invoice.status == "active",
                Invoice.due_date.isnot(None),
            )
        )

        if ledger_id is not None:
            base = base.filter(Invoice.ledger_id == ledger_id)
        if search.strip():
            base = base.filter(Invoice.ledger_name.ilike(f"%{search.strip()}%"))
        if due_date_from is not None:
            base = base.filter(Invoice.due_date >= datetime.combine(due_date_from, datetime.min.time()))
        if due_date_to is not None:
            base = base.filter(Invoice.due_date <= datetime.combine(due_date_to, datetime.max.time()))

        invoices = base.order_by(Invoice.due_date.asc(), Invoice.invoice_date.asc(), Invoice.id.asc()).all()
        payment_summaries = build_invoice_payment_summaries(db, invoices)
        outstanding_invoices = [
            invoice
            for invoice in invoices
            if payment_summaries[invoice.id].remaining_amount > 0
        ]

        total = len(outstanding_invoices)
        page_start = (page - 1) * page_size
        page_end = page_start + page_size
        paged_invoices = outstanding_invoices[page_start:page_end]
        items = [_to_invoice_out(invoice, payment_summary=payment_summaries.get(invoice.id)) for invoice in paged_invoices]

        total_listed = sum((Decimal(str(invoice.total_amount or 0)) for invoice in outstanding_invoices), Decimal("0"))
        visible_page_total = sum((Decimal(str(item.total_amount or 0)) for item in items), Decimal("0"))

        return PaginatedInvoiceOut(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
            summary=PaginatedInvoiceOut.SummaryMeta(
                total_listed=float(total_listed),
                credit_total=0.0,
                debit_total=float(total_listed),
                cancelled_total=0.0,
                active_total=float(total_listed),
                others_total=0.0,
                visible_page_total=float(visible_page_total),
                visible_page_count=len(items),
                filtered_count=total,
                include_cancelled=False,
                financial_year_id=None,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.ledger), joinedload(Invoice.items))
        .filter(Invoice.id == invoice_id, Invoice.company_id == active_company.id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    summary = build_invoice_payment_summaries(db, [invoice]).get(invoice.id)
    return _to_invoice_out(invoice, payment_summary=summary)


@router.put("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: int,
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.items))
        .filter(Invoice.id == invoice_id, Invoice.company_id == active_company.id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    if invoice.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Cancelled invoices cannot be edited. Restore the invoice first.",
        )

    try:
        active_fy = get_active_fy(db, company_id=active_company.id)

        _apply_inventory_delta_for_invoice_update(
            db,
            invoice,
            payload,
            company_id=active_company.id,
        )

        for item in list(invoice.items):
            db.delete(item)
        db.flush()

        _apply_payload_to_invoice(
            db,
            invoice,
            payload,
            active_company,
            regenerate_number=False,
            apply_inventory_changes=False,
        )
        db.commit()
        db.refresh(invoice)

        warnings: list[str] = []
        if active_fy and payload.invoice_date:
            inv_date = payload.invoice_date
            if not (active_fy.start_date <= inv_date <= active_fy.end_date):
                warnings.append("invoice_date_outside_fy")

        summary = build_invoice_payment_summaries(db, [invoice]).get(invoice.id)
        result = _to_invoice_out(invoice, payment_summary=summary)
        result.warnings = warnings
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))







def _build_invoice_pdf(invoice: Invoice, products: list[Product], invoice_bank_accounts: list[CompanyAccount]) -> BytesIO:
    html = _build_invoice_html(invoice, products, invoice_bank_accounts, copy_label=_copy_label(1))
    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    buf = BytesIO(pdf_bytes)
    return buf


def _build_multi_copy_invoice_pdf(invoice: Invoice, products: list[Product], invoice_bank_accounts: list[CompanyAccount], copies: int) -> BytesIO:
    html = _build_multi_copy_invoice_html(invoice, products, invoice_bank_accounts, copies)
    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    buf = BytesIO(pdf_bytes)
    return buf


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    copies: int = Query(default=1, ge=1, le=10),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.items), joinedload(Invoice.ledger))
        .filter(Invoice.id == invoice_id, Invoice.company_id == active_company.id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    product_ids = [item.product_id for item in (invoice.items or [])]
    products = (
      db.query(Product)
      .filter(Product.id.in_(product_ids), Product.company_id == active_company.id)
      .all()
      if product_ids
      else []
    )

    invoice_bank_accounts = (
      db.query(CompanyAccount)
      .filter(
        CompanyAccount.is_active.is_(True),
        CompanyAccount.account_type == "bank",
        CompanyAccount.display_on_invoice.is_(True),
        CompanyAccount.company_id == active_company.id,
      )
      .order_by(CompanyAccount.display_name.asc(), CompanyAccount.id.asc())
      .all()
    )

    pdf_buffer = _build_multi_copy_invoice_pdf(invoice, products, invoice_bank_accounts, copies)
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
    active_company: CompanyProfile = Depends(get_active_company),
):
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.items))
        .filter(Invoice.id == invoice_id, Invoice.company_id == active_company.id)
        .first()
    )
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
    active_company: CompanyProfile = Depends(get_active_company),
):
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.items))
        .filter(Invoice.id == invoice_id, Invoice.company_id == active_company.id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    if invoice.status != "cancelled":
        raise HTTPException(status_code=400, detail="Invoice is not cancelled")

    try:
        # Re-apply inventory changes (reverse the reversal)
        for item in invoice.items:
            product_query = db.query(Product).filter(Product.id == item.product_id)
            product_query = product_query.filter(or_(Product.company_id == active_company.id, Product.company_id.is_(None)))
            product = product_query.first()
            if not product:
                raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
            if not product.maintain_inventory:
                continue

            restore_delta = -item.quantity if invoice.voucher_type == "sales" else item.quantity
            _change_inventory_quantity(
                db,
                item.product_id,
                restore_delta,
                company_id=active_company.id,
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
