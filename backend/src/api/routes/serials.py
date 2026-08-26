"""Scan and browse the individual units of serial-tracked products.

``/scan`` is the single call behind the shop's barcode scanner: it resolves a
raw code to a unit first and to a product SKU second, so phones and accessories
can be scanned in one uninterrupted rhythm.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from typing import Literal

from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.invoice import Invoice
from src.models.product import Product
from src.models.product_serial import STATUS_VOID, ProductSerial
from src.models.user import User
from src.schemas.serial import (
    PaginatedSerialOut,
    SerialInvoiceRef,
    SerialOut,
    SerialScanOut,
)
from src.api.deps import get_active_company, get_current_user
from src.services.serial_service import SerialManager

router = APIRouter()


def _build_serial_outs(
    serials: list[ProductSerial], db: Session, active_company_id: int
) -> list[SerialOut]:
    """Render serial rows with their product and invoice refs attached.

    Products and invoices are fetched once for the whole batch — the picker
    list would otherwise issue three queries per row.
    """
    if not serials:
        return []

    product_ids = {serial.product_id for serial in serials}
    products = {
        product.id: product
        for product in db.query(Product)
        .filter(
            Product.id.in_(product_ids),
            Product.company_id == active_company_id,
        )
        .all()
    }

    invoice_ids = {
        invoice_id
        for serial in serials
        for invoice_id in (serial.purchase_invoice_id, serial.sales_invoice_id)
        if invoice_id is not None
    }
    invoices = (
        {
            invoice.id: invoice
            for invoice in db.query(Invoice)
            .filter(
                Invoice.id.in_(invoice_ids),
                Invoice.company_id == active_company_id,
            )
            .all()
        }
        if invoice_ids
        else {}
    )

    def _ref(invoice_id: int | None) -> SerialInvoiceRef | None:
        invoice = invoices.get(invoice_id) if invoice_id is not None else None
        if invoice is None:
            return None
        return SerialInvoiceRef(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
        )

    results: list[SerialOut] = []
    for serial in serials:
        product = products.get(serial.product_id)
        if product is None:
            continue
        results.append(
            SerialOut(
                id=serial.id,
                serial_number=serial.serial_number,
                status=serial.status,
                product_id=serial.product_id,
                product=product,
                purchase_invoice=_ref(serial.purchase_invoice_id),
                sales_invoice=_ref(serial.sales_invoice_id),
                created_at=serial.created_at,
            )
        )
    return results


@router.get("/scan", response_model=SerialScanOut)
def scan_code(
    code: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Resolve a scanned code: a live serial first, then an exact product SKU."""
    manager = SerialManager(db)
    normalized = manager.normalize(code)

    if normalized:
        serial = manager.lookup(normalized, active_company.id)
        if serial is not None:
            built = _build_serial_outs([serial], db, active_company.id)
            if built:
                return SerialScanOut(kind="serial", serial=built[0], product=None)

        product = (
            db.query(Product)
            .filter(
                Product.company_id == active_company.id,
                func.upper(Product.sku) == normalized.upper(),
            )
            .first()
        )
        if product is not None:
            return SerialScanOut(kind="product", serial=None, product=product)

    raise HTTPException(
        status_code=404,
        detail=f'No product or serial number found for "{code}"',
    )


@router.get("", response_model=PaginatedSerialOut, include_in_schema=False)
@router.get("/", response_model=PaginatedSerialOut)
def list_serials(
    product_id: int | None = Query(None),
    status: Literal["in_stock", "sold", "void"] | None = Query(None),
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """List units for the picker, oldest first so the shop moves stock FIFO."""
    query = db.query(ProductSerial).filter(
        or_(
            ProductSerial.company_id == active_company.id,
            ProductSerial.company_id.is_(None),
        )
    )
    if product_id is not None:
        query = query.filter(ProductSerial.product_id == product_id)
    if status is not None:
        query = query.filter(ProductSerial.status == status)
    else:
        # Voided units are write-offs and cancelled receipts — noise in every
        # list, so they surface only when asked for by name.
        query = query.filter(ProductSerial.status != STATUS_VOID)
    if search.strip():
        query = query.filter(ProductSerial.serial_number.ilike(f"%{search.strip()}%"))

    total = query.count()
    serials = (
        query.order_by(ProductSerial.created_at.asc(), ProductSerial.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedSerialOut(
        items=_build_serial_outs(serials, db, active_company.id),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
    )
