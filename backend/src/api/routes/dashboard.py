from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.payment import Payment
from src.models.product import Product
from src.models.user import User
from src.schemas.dashboard import (
    CatalogMetrics,
    DashboardCharts,
    DashboardMetrics,
    InventoryMetrics,
    MonthlyPoint,
    PaymentsMetrics,
    ReceivablesMetrics,
    SalesMetrics,
    TopProduct,
)
from src.services.invoice_payments import build_invoice_payment_summaries

router = APIRouter()

MONTHS_IN_TREND = 12
_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_window(today: date) -> list[tuple[int, int]]:
    """Return (year, month) tuples for the trailing MONTHS_IN_TREND months, oldest first."""
    months: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(MONTHS_IN_TREND):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(months))


@router.get("/metrics", response_model=DashboardMetrics)
def get_dashboard_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    company_id = active_company.id
    today = date.today()
    month_start = today.replace(day=1)

    # --- Catalog ---------------------------------------------------------
    catalog_row = (
        db.query(
            func.count(Product.id),
            func.coalesce(func.sum(case((Product.is_producable.is_(True), 1), else_=0)), 0),
        )
        .filter(Product.company_id == company_id)
        .one()
    )
    catalog = CatalogMetrics(
        total_products=int(catalog_row[0] or 0),
        producible_products=int(catalog_row[1] or 0),
    )

    # --- Inventory -------------------------------------------------------
    # Iterate maintained products with their (possibly missing) stock rows so the
    # low/out-of-stock rules can compare each quantity against its own reorder level.
    inv_rows = (
        db.query(
            func.coalesce(Inventory.quantity, 0),
            Product.reorder_level,
            Product.purchase_price,
        )
        .outerjoin(
            Inventory,
            and_(Inventory.product_id == Product.id, Inventory.company_id == company_id),
        )
        .filter(Product.company_id == company_id, Product.maintain_inventory.is_(True))
        .all()
    )
    total_units = Decimal("0")
    stock_value = Decimal("0")
    low_stock_count = 0
    out_of_stock_count = 0
    for quantity, reorder_level, purchase_price in inv_rows:
        qty = Decimal(str(quantity or 0))
        reorder = Decimal(str(reorder_level or 0))
        cost = Decimal(str(purchase_price or 0))
        total_units += qty
        stock_value += qty * cost
        if qty <= 0:
            out_of_stock_count += 1
        elif reorder > 0 and qty <= reorder:
            low_stock_count += 1
    inventory = InventoryMetrics(
        tracked_products=len(inv_rows),
        total_units=float(total_units),
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
        stock_value=float(stock_value),
    )

    # --- Sales / Purchases (active invoices only) ------------------------
    sales_case = (Invoice.voucher_type == "sales", Invoice.total_amount)
    purchase_case = (Invoice.voucher_type == "purchase", Invoice.total_amount)
    sales_row = (
        db.query(
            func.coalesce(func.sum(case((Invoice.voucher_type == "sales", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.voucher_type == "purchase", 1), else_=0)), 0),
            func.coalesce(func.sum(case(sales_case, else_=0)), 0),
            func.coalesce(func.sum(case(purchase_case, else_=0)), 0),
            func.coalesce(
                func.sum(
                    case(
                        ((Invoice.voucher_type == "sales") & (Invoice.invoice_date >= month_start), Invoice.total_amount),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .filter(Invoice.company_id == company_id, Invoice.status == "active")
        .one()
    )
    sales_count = int(sales_row[0] or 0)
    total_sales = Decimal(str(sales_row[2] or 0))
    sales = SalesMetrics(
        sales_invoice_count=sales_count,
        purchase_invoice_count=int(sales_row[1] or 0),
        total_sales=float(total_sales),
        total_purchases=float(Decimal(str(sales_row[3] or 0))),
        this_month_sales=float(Decimal(str(sales_row[4] or 0))),
        average_invoice_value=float(total_sales / sales_count) if sales_count else 0.0,
    )

    # --- Receivables (reuses the canonical outstanding calculation) ------
    active_sales = (
        db.query(Invoice)
        .filter(
            Invoice.company_id == company_id,
            Invoice.voucher_type == "sales",
            Invoice.status == "active",
        )
        .all()
    )
    summaries = build_invoice_payment_summaries(db, active_sales)
    outstanding_amount = Decimal("0")
    overdue_amount = Decimal("0")
    overdue_count = 0
    paid_count = partial_count = unpaid_count = 0
    for invoice in active_sales:
        summary = summaries[invoice.id]
        remaining = Decimal(str(summary.remaining_amount or 0))
        outstanding_amount += remaining
        if summary.payment_status == "paid":
            paid_count += 1
        elif summary.payment_status == "partial":
            partial_count += 1
        else:
            unpaid_count += 1
        if remaining > 0 and invoice.due_date is not None and invoice.due_date.date() < today:
            overdue_amount += remaining
            overdue_count += 1
    receivables = ReceivablesMetrics(
        outstanding_amount=float(outstanding_amount),
        overdue_amount=float(overdue_amount),
        overdue_count=overdue_count,
        paid_count=paid_count,
        partial_count=partial_count,
        unpaid_count=unpaid_count,
    )

    # --- Payments --------------------------------------------------------
    payment_row = (
        db.query(
            func.coalesce(func.sum(case((Payment.voucher_type == "receipt", Payment.amount), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.voucher_type == "payment", Payment.amount), else_=0)), 0),
            func.coalesce(
                func.sum(
                    case(
                        ((Payment.voucher_type == "receipt") & (Payment.date >= month_start), Payment.amount),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .filter(Payment.company_id == company_id, Payment.status == "active")
        .one()
    )
    payments = PaymentsMetrics(
        received_total=float(Decimal(str(payment_row[0] or 0))),
        paid_total=float(Decimal(str(payment_row[1] or 0))),
        this_month_received=float(Decimal(str(payment_row[2] or 0))),
    )

    # --- Monthly trend (DB-agnostic bucketing in Python) -----------------
    months = _month_window(today)
    window_start = date(months[0][0], months[0][1], 1)
    buckets: dict[tuple[int, int], dict[str, Decimal]] = {
        m: {"sales": Decimal("0"), "purchases": Decimal("0"), "receipts": Decimal("0")} for m in months
    }

    invoice_rows = (
        db.query(Invoice.invoice_date, Invoice.voucher_type, Invoice.total_amount)
        .filter(
            Invoice.company_id == company_id,
            Invoice.status == "active",
            Invoice.invoice_date >= window_start,
        )
        .all()
    )
    for inv_date, voucher_type, amount in invoice_rows:
        key = (inv_date.year, inv_date.month)
        if key not in buckets:
            continue
        if voucher_type == "sales":
            buckets[key]["sales"] += Decimal(str(amount or 0))
        elif voucher_type == "purchase":
            buckets[key]["purchases"] += Decimal(str(amount or 0))

    receipt_rows = (
        db.query(Payment.date, Payment.amount)
        .filter(
            Payment.company_id == company_id,
            Payment.status == "active",
            Payment.voucher_type == "receipt",
            Payment.date >= window_start,
        )
        .all()
    )
    for pay_date, amount in receipt_rows:
        key = (pay_date.year, pay_date.month)
        if key in buckets:
            buckets[key]["receipts"] += Decimal(str(amount or 0))

    monthly = [
        MonthlyPoint(
            month=f"{year:04d}-{month:02d}",
            label=f"{_MONTH_LABELS[month - 1]} {year % 100:02d}",
            sales=float(buckets[(year, month)]["sales"]),
            purchases=float(buckets[(year, month)]["purchases"]),
            receipts=float(buckets[(year, month)]["receipts"]),
        )
        for year, month in months
    ]

    # --- Top products by revenue (active sales) --------------------------
    top_rows = (
        db.query(
            Product.id,
            Product.name,
            func.coalesce(func.sum(InvoiceItem.quantity), 0),
            func.coalesce(func.sum(InvoiceItem.line_total), 0),
        )
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .join(Product, Product.id == InvoiceItem.product_id)
        .filter(
            Invoice.company_id == company_id,
            Invoice.status == "active",
            Invoice.voucher_type == "sales",
        )
        .group_by(Product.id, Product.name)
        .order_by(func.coalesce(func.sum(InvoiceItem.line_total), 0).desc())
        .limit(5)
        .all()
    )
    top_products = [
        TopProduct(
            product_id=product_id,
            name=name,
            quantity=float(Decimal(str(quantity or 0))),
            revenue=float(Decimal(str(revenue or 0))),
        )
        for product_id, name, quantity, revenue in top_rows
    ]

    return DashboardMetrics(
        currency_code=active_company.currency_code or "USD",
        catalog=catalog,
        inventory=inventory,
        sales=sales,
        receivables=receivables,
        payments=payments,
        charts=DashboardCharts(monthly=monthly, top_products=top_products),
    )
