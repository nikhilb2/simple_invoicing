from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.product import Product
from src.models.user import User
from src.schemas.dashboard import (
    DashboardInventoryPreview,
    DashboardInvoicePreview,
    DashboardSummaryOut,
)

router = APIRouter()


@router.get("/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(
    low_stock_threshold: float = Query(5, ge=0),
    low_stock_limit: int = Query(5, ge=1, le=25),
    recent_invoice_limit: int = Query(6, ge=1, le=25),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    quantity_expr = func.coalesce(Inventory.quantity, 0)

    product_count = (
        db.query(func.count(Product.id))
        .filter(Product.company_id == active_company.id)
        .scalar()
        or 0
    )

    tracked_inventory_rows = (
        db.query(func.count(Product.id))
        .filter(
            Product.company_id == active_company.id,
            Product.maintain_inventory.is_(True),
        )
        .scalar()
        or 0
    )

    total_inventory_units = (
        db.query(func.coalesce(func.sum(Inventory.quantity), 0))
        .filter(Inventory.company_id == active_company.id)
        .scalar()
        or Decimal("0")
    )

    low_stock_base = (
        db.query(Product.id)
        .outerjoin(
            Inventory,
            and_(
                Inventory.product_id == Product.id,
                Inventory.company_id == active_company.id,
            ),
        )
        .filter(
            Product.company_id == active_company.id,
            Product.maintain_inventory.is_(True),
            quantity_expr <= low_stock_threshold,
        )
    )
    low_stock_count = low_stock_base.count()

    low_stock_rows = (
        db.query(Product.id, Product.name, quantity_expr.label("quantity"))
        .outerjoin(
            Inventory,
            and_(
                Inventory.product_id == Product.id,
                Inventory.company_id == active_company.id,
            ),
        )
        .filter(
            Product.company_id == active_company.id,
            Product.maintain_inventory.is_(True),
            quantity_expr <= low_stock_threshold,
        )
        .order_by(quantity_expr.asc(), Product.name.asc())
        .limit(low_stock_limit)
        .all()
    )

    active_invoice_total = (
        db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(
            Invoice.company_id == active_company.id,
            Invoice.status == "active",
        )
        .scalar()
        or Decimal("0")
    )

    recent_invoices = (
        db.query(Invoice)
        .filter(
            Invoice.company_id == active_company.id,
            Invoice.status == "active",
        )
        .order_by(Invoice.id.desc())
        .limit(recent_invoice_limit)
        .all()
    )

    return DashboardSummaryOut(
        product_count=product_count,
        tracked_inventory_rows=tracked_inventory_rows,
        total_inventory_units=float(total_inventory_units),
        low_stock_count=low_stock_count,
        active_invoice_total=float(active_invoice_total),
        low_stock_threshold=low_stock_threshold,
        low_stock_items=[
            DashboardInventoryPreview(
                product_id=product_id,
                product_name=product_name,
                quantity=float(quantity or 0),
            )
            for product_id, product_name, quantity in low_stock_rows
        ],
        recent_invoices=[
            DashboardInvoicePreview(
                id=invoice.id,
                invoice_number=invoice.invoice_number,
                ledger_name=invoice.ledger_name,
                total_amount=float(invoice.total_amount or 0),
                invoice_date=invoice.invoice_date,
            )
            for invoice in recent_invoices
        ],
    )
