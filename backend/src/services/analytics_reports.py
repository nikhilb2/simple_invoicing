"""Sales analytics report builders.

The JSON and CSV routes both call these builders so the two can never disagree
about a number — the same split :mod:`src.api.routes.ledgers` uses for the day
book.

Month bucketing happens in Python rather than via ``date_trunc``: the test suite
runs on SQLite while production runs on Postgres, and the dashboard already set
this precedent.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.services.gst_tax_service import money as _money
from src.services.invoice_discounts import build_invoice_discount_totals

MONTHS_IN_TREND = 12
_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_window(today: date, months: int = MONTHS_IN_TREND) -> list[tuple[int, int]]:
    """Return (year, month) tuples for the trailing ``months`` months, oldest first."""
    window: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(months):
        window.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(window))


def month_label(year: int, month: int) -> str:
    """Format a month as "Apr 26". Shared with the dashboard so labels match."""
    return f"{_MONTH_LABELS[month - 1]} {year % 100:02d}"


def months_between(from_date: date, to_date: date) -> list[tuple[int, int]]:
    """Every (year, month) touched by the range, inclusive, oldest first."""
    window: list[tuple[int, int]] = []
    year, month = from_date.year, from_date.month
    while (year, month) <= (to_date.year, to_date.month):
        window.append((year, month))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return window


@dataclass
class MonthlyBucket:
    invoice_count: int = 0
    total_sales: Decimal = Decimal("0")
    taxable_value: Decimal = Decimal("0")
    gst_collected: Decimal = Decimal("0")
    discount_given: Decimal = Decimal("0")


@dataclass
class MonthlySalesData:
    rows: list[tuple[int, int, MonthlyBucket]]
    totals: MonthlyBucket


@dataclass
class ProductSalesData:
    rows: list[dict]
    totals: dict


def _date_bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    """Convert a date range to datetime bounds covering the whole end day.

    ``Invoice.invoice_date`` is a DateTime; comparing it against a bare date
    silently drops invoices dated on ``to_date`` that carry a time component.
    """
    return datetime.combine(from_date, time.min), datetime.combine(to_date, time.max)


def _scoped_invoice_query(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
):
    start, end = _date_bounds(from_date, to_date)
    # Strict company_id equality (not the NULL-tolerant form used by
    # invoice_payments for legacy rows): on a reporting surface a NULL-company
    # invoice would leak into every company's revenue. Legacy rows were
    # populated by migration 20260424000002_backfill_company_scope_data.
    query = db.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.status == "active",
        Invoice.voucher_type == voucher_type,
        Invoice.invoice_date >= start,
        Invoice.invoice_date <= end,
    )
    if ledger_id is not None:
        query = query.filter(Invoice.ledger_id == ledger_id)
    return query


def build_monthly_sales_report(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
) -> MonthlySalesData:
    """Aggregate invoices into one row per calendar month in the range.

    Every month in the range is emitted, including empty ones — a chart with
    gaps silently omitted would misrepresent a quiet month as no month.
    """
    invoices = _scoped_invoice_query(
        db,
        company_id=company_id,
        voucher_type=voucher_type,
        from_date=from_date,
        to_date=to_date,
        ledger_id=ledger_id,
    ).all()

    discounts = build_invoice_discount_totals(db, invoices)

    buckets: dict[tuple[int, int], MonthlyBucket] = {
        key: MonthlyBucket() for key in months_between(from_date, to_date)
    }

    for invoice in invoices:
        key = (invoice.invoice_date.year, invoice.invoice_date.month)
        bucket = buckets.get(key)
        if bucket is None:
            # Defensive: the query is already bounded to the range.
            continue
        bucket.invoice_count += 1
        bucket.total_sales += Decimal(str(invoice.total_amount or 0))
        bucket.taxable_value += Decimal(str(invoice.taxable_amount or 0))
        bucket.gst_collected += Decimal(str(invoice.total_tax_amount or 0))
        bucket.discount_given += discounts[invoice.id].total_discount

    totals = MonthlyBucket()
    for bucket in buckets.values():
        totals.invoice_count += bucket.invoice_count
        totals.total_sales += bucket.total_sales
        totals.taxable_value += bucket.taxable_value
        totals.gst_collected += bucket.gst_collected
        totals.discount_given += bucket.discount_given

    rows = [(year, month, buckets[(year, month)]) for year, month in months_between(from_date, to_date)]
    return MonthlySalesData(rows=rows, totals=totals)


def average_of(total: Decimal, count) -> Decimal:
    """Mean guarded against a zero denominator (empty months, zero-qty lines)."""
    if not count:
        return Decimal("0.00")
    return _money(total / Decimal(str(count)))


def build_product_sales_report(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
    product_id: int | None = None,
    sort_by: str = "revenue",
    sort_dir: str = "desc",
    limit: int | None = None,
) -> ProductSalesData:
    """Aggregate invoice lines into one row per product."""
    start, end = _date_bounds(from_date, to_date)

    query = (
        db.query(
            Product.id,
            Product.name,
            Product.sku,
            Product.maintain_inventory,
            func.coalesce(func.sum(InvoiceItem.quantity), 0),
            func.coalesce(func.sum(InvoiceItem.taxable_amount), 0),
            func.coalesce(func.sum(InvoiceItem.tax_amount), 0),
            func.coalesce(func.sum(InvoiceItem.line_total), 0),
            # Distinct: a product appearing on two lines of one invoice must
            # count that invoice once.
            func.count(func.distinct(InvoiceItem.invoice_id)),
        )
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .join(Product, Product.id == InvoiceItem.product_id)
        .filter(
            # InvoiceItem carries no company_id — scope comes via the Invoice join.
            Invoice.company_id == company_id,
            Invoice.status == "active",
            Invoice.voucher_type == voucher_type,
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
        )
    )
    if ledger_id is not None:
        query = query.filter(Invoice.ledger_id == ledger_id)
    if product_id is not None:
        query = query.filter(Product.id == product_id)

    grouped = query.group_by(Product.id, Product.name, Product.sku, Product.maintain_inventory).all()

    # Stock is fetched separately rather than outer-joined: a product with
    # maintain_inventory=False has no meaningful stock, and a join would report
    # a misleading 0 instead of "not tracked".
    stock_map: dict[int, Decimal] = {}
    if grouped:
        stock_rows = (
            db.query(Inventory.product_id, Inventory.quantity)
            .filter(
                Inventory.company_id == company_id,
                Inventory.product_id.in_([row[0] for row in grouped]),
            )
            .all()
        )
        stock_map = {pid: Decimal(str(qty or 0)) for pid, qty in stock_rows}

    rows: list[dict] = []
    for pid, name, sku, maintain_inventory, quantity, taxable, tax, revenue, invoice_count in grouped:
        qty = Decimal(str(quantity or 0))
        sales_amount = Decimal(str(taxable or 0))
        rows.append({
            "product_id": pid,
            "name": name,
            "sku": sku,
            "quantity_sold": qty,
            "sales_amount": sales_amount,
            "average_selling_price": average_of(sales_amount, qty),
            "total_revenue": Decimal(str(revenue or 0)),
            "total_gst": Decimal(str(tax or 0)),
            "invoice_count": int(invoice_count or 0),
            "current_stock": stock_map.get(pid, Decimal("0")) if maintain_inventory else None,
        })

    _sort_rows(rows, sort_by=sort_by, sort_dir=sort_dir)

    if limit is not None:
        rows = rows[:limit]

    totals = {
        "product_count": len(rows),
        "quantity_sold": sum((row["quantity_sold"] for row in rows), Decimal("0")),
        "sales_amount": sum((row["sales_amount"] for row in rows), Decimal("0")),
        "total_revenue": sum((row["total_revenue"] for row in rows), Decimal("0")),
        "total_gst": sum((row["total_gst"] for row in rows), Decimal("0")),
        "invoice_count": _distinct_invoice_count(
            db,
            company_id=company_id,
            voucher_type=voucher_type,
            from_date=from_date,
            to_date=to_date,
            ledger_id=ledger_id,
            product_ids=[row["product_id"] for row in rows],
        ),
    }

    return ProductSalesData(rows=rows, totals=totals)


def _sort_rows(rows: list[dict], *, sort_by: str, sort_dir: str) -> None:
    reverse = sort_dir == "desc"

    if sort_by == "stock":
        # Stock isn't in the grouped query, so this can't be pushed into SQL.
        # Untracked products (None) sort last in both directions rather than
        # being treated as zero.
        tracked = [row for row in rows if row["current_stock"] is not None]
        untracked = [row for row in rows if row["current_stock"] is None]
        tracked.sort(key=lambda row: row["current_stock"], reverse=reverse)
        rows[:] = tracked + untracked
        return

    keys = {
        "quantity": lambda row: row["quantity_sold"],
        "revenue": lambda row: row["total_revenue"],
        "name": lambda row: (row["name"] or "").lower(),
    }
    rows.sort(key=keys[sort_by], reverse=reverse)


def _distinct_invoice_count(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_ids: list[int],
) -> int:
    """Count invoices touching the listed products.

    Summing each row's invoice_count would double-count an invoice that carries
    two different products, so the total needs its own distinct query.
    """
    if not product_ids:
        return 0

    start, end = _date_bounds(from_date, to_date)
    query = (
        db.query(func.count(func.distinct(Invoice.id)))
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .filter(
            Invoice.company_id == company_id,
            Invoice.status == "active",
            Invoice.voucher_type == voucher_type,
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
            InvoiceItem.product_id.in_(product_ids),
        )
    )
    if ledger_id is not None:
        query = query.filter(Invoice.ledger_id == ledger_id)
    return int(query.scalar() or 0)
