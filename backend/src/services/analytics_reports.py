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

from src.models.credit_note import CreditNote, CreditNoteItem
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.services.gst_tax_service import money as _money
from src.services.invoice_discounts import (
    apportion_invoice_discount,
    build_invoice_discount_totals,
    invoice_discount_amount,
)

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


def _margin_pct(gross_profit: Decimal, revenue: Decimal) -> Decimal:
    """Gross margin as a percentage, guarded against zero revenue."""
    if not revenue:
        return Decimal("0.00")
    return _money(gross_profit / revenue * Decimal("100"))


@dataclass
class ProfitLossData:
    product_rows: list[dict]
    monthly_rows: list[tuple[int, int, dict]]
    customer_rows: list[dict]
    totals: dict


def build_profit_loss_report(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
    product_id: int | None = None,
) -> ProfitLossData:
    """Profit & loss per product, per month, and per customer.

    Cost basis is the product's *current* ``purchase_price`` — invoice lines
    carry no cost snapshot, so a historical period is priced at today's cost and
    its margin shifts if the cost is later edited. Revenue is ``taxable_amount``
    (ex-GST); GST is pass-through and never counted as profit.

    All three breakdowns come from one line-level scan so the numbers can't
    diverge. When ``product_id`` is set, ``monthly_rows`` narrows to that
    product's series — the per-product purchase-vs-sales view reuses it directly.
    """
    start, end = _date_bounds(from_date, to_date)

    query = (
        db.query(
            Invoice.id,
            Invoice.invoice_date,
            Invoice.ledger_id,
            Invoice.ledger_name,
            InvoiceItem.product_id,
            InvoiceItem.quantity,
            InvoiceItem.taxable_amount,
            Product.name,
            Product.sku,
            Product.purchase_price,
        )
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .join(Product, Product.id == InvoiceItem.product_id)
        .filter(
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

    # Per-product, per-month, and per-customer accumulators, all built in one pass.
    products: dict[int, dict] = {}
    months: dict[tuple[int, int], dict] = {
        key: {"quantity": Decimal("0"), "revenue": Decimal("0"), "cogs": Decimal("0")}
        for key in months_between(from_date, to_date)
    }
    customers: dict[int | None, dict] = {}
    total_invoice_ids: set[int] = set()

    for (
        invoice_id,
        invoice_date,
        row_ledger_id,
        ledger_name,
        pid,
        quantity,
        taxable,
        name,
        sku,
        purchase_price,
    ) in query.all():
        qty = Decimal(str(quantity or 0))
        revenue = Decimal(str(taxable or 0))
        cost = Decimal(str(purchase_price or 0))
        line_cogs = qty * cost

        product = products.get(pid)
        if product is None:
            product = {
                "product_id": pid,
                "name": name,
                "sku": sku,
                "purchase_price": cost,
                "quantity_sold": Decimal("0"),
                "revenue": Decimal("0"),
            }
            products[pid] = product
        product["quantity_sold"] += qty
        product["revenue"] += revenue

        bucket = months.get((invoice_date.year, invoice_date.month))
        if bucket is not None:  # defensive: query is already range-bounded
            bucket["quantity"] += qty
            bucket["revenue"] += revenue
            bucket["cogs"] += line_cogs

        customer = customers.get(row_ledger_id)
        if customer is None:
            customer = {
                "ledger_id": row_ledger_id,
                "name": ledger_name or "—",
                "revenue": Decimal("0"),
                "cogs": Decimal("0"),
                "invoice_ids": set(),
            }
            customers[row_ledger_id] = customer
        customer["revenue"] += revenue
        customer["cogs"] += line_cogs
        customer["invoice_ids"].add(invoice_id)

        total_invoice_ids.add(invoice_id)

    product_rows: list[dict] = []
    for product in products.values():
        revenue = _money(product["revenue"])
        cogs = _money(product["quantity_sold"] * product["purchase_price"])
        gross_profit = _money(revenue - cogs)
        product_rows.append({
            "product_id": product["product_id"],
            "name": product["name"],
            "sku": product["sku"],
            "quantity_sold": product["quantity_sold"],
            "sales_amount": revenue,
            "average_selling_price": average_of(revenue, product["quantity_sold"]),
            "purchase_price": _money(product["purchase_price"]),
            "cogs": cogs,
            "gross_profit": gross_profit,
            "margin_pct": _margin_pct(gross_profit, revenue),
        })
    # Most profitable first — the table opens on what matters and the chart's
    # Top-N slice is a straight prefix.
    product_rows.sort(key=lambda row: row["gross_profit"], reverse=True)

    monthly_rows: list[tuple[int, int, dict]] = []
    for year, month in months_between(from_date, to_date):
        bucket = months[(year, month)]
        revenue = _money(bucket["revenue"])
        cogs = _money(bucket["cogs"])
        gross_profit = _money(revenue - cogs)
        monthly_rows.append((year, month, {
            "quantity": bucket["quantity"],
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "margin_pct": _margin_pct(gross_profit, revenue),
        }))

    customer_rows: list[dict] = []
    for customer in customers.values():
        revenue = _money(customer["revenue"])
        cogs = _money(customer["cogs"])
        gross_profit = _money(revenue - cogs)
        customer_rows.append({
            "ledger_id": customer["ledger_id"],
            "name": customer["name"],
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "margin_pct": _margin_pct(gross_profit, revenue),
            "invoice_count": len(customer["invoice_ids"]),
        })
    customer_rows.sort(key=lambda row: row["gross_profit"], reverse=True)

    total_revenue = sum((row["sales_amount"] for row in product_rows), Decimal("0"))
    total_cogs = sum((row["cogs"] for row in product_rows), Decimal("0"))
    total_gross_profit = _money(total_revenue - total_cogs)
    totals = {
        "product_count": len(product_rows),
        "quantity_sold": sum((row["quantity_sold"] for row in product_rows), Decimal("0")),
        "revenue": _money(total_revenue),
        "cogs": _money(total_cogs),
        "gross_profit": total_gross_profit,
        "margin_pct": _margin_pct(total_gross_profit, total_revenue),
    }

    return ProfitLossData(
        product_rows=product_rows,
        monthly_rows=monthly_rows,
        customer_rows=customer_rows,
        totals=totals,
    )


# --- Product performance ----------------------------------------------------

PRODUCT_PERFORMANCE_SORTS = (
    "name",
    "units_sold",
    "units_returned",
    "net_units_sold",
    "units_bought",
    "net_units_bought",
    "average_selling_price",
    "average_buying_price",
    "revenue",
    "purchase_spend",
    "cogs",
    "gross_profit",
    "margin_pct",
    "profit_per_unit",
    "current_stock",
)

COST_BASIS_PURCHASES = "purchases"
COST_BASIS_CURRENT_PRICE = "current_price"


@dataclass
class ProductPerformanceData:
    rows: list[dict]
    totals: dict


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Rounded ``numerator / denominator``; None (not 0) when undefined."""
    if not denominator:
        return None
    return _money(numerator / denominator)


def _discounted_invoice_lines(
    db: Session,
    *,
    company_id: int,
    voucher_type: str,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_id: int | None,
) -> list[tuple[int, Decimal, Decimal]]:
    """``(product_id, quantity, taxable net of invoice discount)`` per line.

    Every line of every in-scope invoice is fetched, even under a product
    filter, because the invoice-level discount is apportioned across *all* of
    an invoice's lines; dropping the other lines first would hand the filtered
    product the whole discount. The product filter narrows the invoice set in
    SQL and the lines in Python afterwards.

    Only the columns needed are selected — a full ``Invoice`` row carries the
    company logo snapshot, which is far too heavy to load per invoice here.
    """
    start, end = _date_bounds(from_date, to_date)
    query = (
        db.query(
            Invoice.id,
            Invoice.taxable_amount,
            Invoice.total_tax_amount,
            Invoice.round_off_amount,
            Invoice.total_amount,
            InvoiceItem.product_id,
            InvoiceItem.quantity,
            InvoiceItem.taxable_amount.label("line_taxable"),
        )
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .filter(
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
        containing = db.query(InvoiceItem.invoice_id).filter(InvoiceItem.product_id == product_id)
        query = query.filter(Invoice.id.in_(containing))

    by_invoice: dict[int, list] = {}
    for row in query.order_by(Invoice.id, InvoiceItem.id).all():
        by_invoice.setdefault(row.id, []).append(row)

    lines: list[tuple[int, Decimal, Decimal]] = []
    for invoice_rows in by_invoice.values():
        header = invoice_rows[0]  # every row repeats the invoice's own columns
        taxables = [Decimal(str(row.line_taxable or 0)) for row in invoice_rows]
        shares = apportion_invoice_discount(
            taxables,
            # invoice_discount_amount only reads the four total columns, all
            # of which the row carries under the same names.
            invoice_discount=invoice_discount_amount(header),
            invoice_tax=Decimal(str(header.total_tax_amount or 0)),
        )
        for row, taxable, share in zip(invoice_rows, taxables, shares):
            if product_id is not None and row.product_id != product_id:
                continue
            lines.append((row.product_id, Decimal(str(row.quantity or 0)), taxable - share))
    return lines


def _credit_note_lines(
    db: Session,
    *,
    company_id: int,
    from_date: date,
    to_date: date,
    ledger_id: int | None,
    product_id: int | None,
):
    """Active credit/debit note lines in the period, dated by ``created_at``.

    Strict company equality on the note header: unlike
    :mod:`src.services.credit_note_reporting`, a NULL-company note must not
    leak into every company's figures on a reporting surface.
    """
    start, end = _date_bounds(from_date, to_date)
    query = (
        db.query(
            CreditNote.direction,
            CreditNote.credit_note_type,
            CreditNoteItem.product_id,
            CreditNoteItem.quantity,
            CreditNoteItem.taxable_amount,
        )
        .join(CreditNote, CreditNoteItem.credit_note_id == CreditNote.id)
        .filter(
            CreditNote.company_id == company_id,
            CreditNote.status == "active",
            CreditNote.created_at >= start,
            CreditNote.created_at <= end,
            CreditNoteItem.product_id.isnot(None),
        )
    )
    if ledger_id is not None:
        query = query.filter(CreditNote.ledger_id == ledger_id)
    if product_id is not None:
        query = query.filter(CreditNoteItem.product_id == product_id)
    return query.all()


def _purchase_unit_costs(lines: list[tuple[int, Decimal, Decimal]]) -> dict[int, Decimal]:
    """Weighted average ex-GST unit cost per product from purchase lines.

    Kept unrounded: it is multiplied by unit counts for COGS, and rounding the
    unit cost first would scale a sub-paisa error by the quantity.
    """
    spend: dict[int, Decimal] = {}
    units: dict[int, Decimal] = {}
    for pid, qty, taxable in lines:
        spend[pid] = spend.get(pid, Decimal("0")) + taxable
        units[pid] = units.get(pid, Decimal("0")) + qty
    return {pid: spend[pid] / units[pid] for pid in spend if units[pid]}


def build_product_performance_report(
    db: Session,
    *,
    company_id: int,
    from_date: date,
    to_date: date,
    ledger_id: int | None = None,
    product_id: int | None = None,
    sort_by: str = "revenue",
    sort_dir: str = "desc",
    limit: int | None = None,
) -> ProductPerformanceData:
    """Per-product sales, purchases, returns and margin for a period.

    Money is ex-GST throughout. Revenue and purchase spend start from line
    ``taxable_amount`` (already net of line discounts), less each line's share
    of any invoice-level discount (see
    :func:`~src.services.invoice_discounts.apportion_invoice_discount`), less
    active credit notes: outward notes reduce sales, inward (supplier) notes
    reduce purchases. Every credit note type reduces value; only ``return``
    notes move units, because a ``discount`` or ``adjustment`` note sends no
    goods back (the credit note service only touches stock for returns).

    Cost: the weighted average ex-GST purchase price over the period
    (``cost_basis="purchases"``), falling back to the product's current
    ``purchase_price`` when it had no purchases in the period
    (``cost_basis="current_price"``). With neither, the cost is unknown and
    every cost-derived field is None rather than a misleading full margin.
    COGS is net units sold x that cost, so returned units take their cost back
    out. The average cost ignores the ledger filter — what a product cost does
    not depend on which customer it was later sold to — while units bought and
    spend shown on the row do honour it.

    Totals cover the returned rows (after ``limit``), like the product sales
    report. Profit totals only cover rows with a known cost, and the margin is
    taken over those rows' revenue so uncosted revenue can't dilute it.
    """
    sales_lines = _discounted_invoice_lines(
        db, company_id=company_id, voucher_type="sales", from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    )
    purchase_lines = _discounted_invoice_lines(
        db, company_id=company_id, voucher_type="purchase", from_date=from_date,
        to_date=to_date, ledger_id=ledger_id, product_id=product_id,
    )
    cost_lines = purchase_lines
    if ledger_id is not None:
        cost_lines = _discounted_invoice_lines(
            db, company_id=company_id, voucher_type="purchase", from_date=from_date,
            to_date=to_date, ledger_id=None, product_id=product_id,
        )
    unit_costs = _purchase_unit_costs(cost_lines)
    note_lines = _credit_note_lines(
        db, company_id=company_id, from_date=from_date, to_date=to_date,
        ledger_id=ledger_id, product_id=product_id,
    )

    zero = Decimal("0")
    fields = (
        "units_sold", "units_returned", "units_bought", "units_purchase_returned",
        "sales_value", "return_value", "purchase_value", "purchase_return_value",
    )
    acc: dict[int, dict[str, Decimal]] = {}

    def bucket(pid: int) -> dict[str, Decimal]:
        if pid not in acc:
            acc[pid] = {field: zero for field in fields}
        return acc[pid]

    for pid, qty, taxable in sales_lines:
        entry = bucket(pid)
        entry["units_sold"] += qty
        entry["sales_value"] += taxable
    for pid, qty, taxable in purchase_lines:
        entry = bucket(pid)
        entry["units_bought"] += qty
        entry["purchase_value"] += taxable
    for direction, note_type, pid, qty, taxable in note_lines:
        entry = bucket(pid)
        units = Decimal(str(qty or 0)) if note_type == "return" else zero
        value = Decimal(str(taxable or 0))
        # A NULL direction predates the column; every such note was outward.
        if direction == "inward":
            entry["units_purchase_returned"] += units
            entry["purchase_return_value"] += value
        else:
            entry["units_returned"] += units
            entry["return_value"] += value

    if not acc:
        return ProductPerformanceData(rows=[], totals=_performance_totals([]))

    products = {
        product.id: product
        for product in db.query(
            Product.id, Product.name, Product.sku, Product.maintain_inventory, Product.purchase_price,
        ).filter(Product.id.in_(list(acc))).all()
    }
    stock_map = {
        pid: Decimal(str(qty or 0))
        for pid, qty in db.query(Inventory.product_id, Inventory.quantity)
        .filter(Inventory.company_id == company_id, Inventory.product_id.in_(list(acc)))
        .all()
    }

    rows: list[dict] = []
    for pid, entry in acc.items():
        product = products.get(pid)
        if product is None:  # defensive: a line pointing at a deleted product
            continue

        net_units_sold = entry["units_sold"] - entry["units_returned"]
        net_units_bought = entry["units_bought"] - entry["units_purchase_returned"]
        sales_value = _money(entry["sales_value"])
        return_value = _money(entry["return_value"])
        revenue = _money(sales_value - return_value)
        purchase_value = _money(entry["purchase_value"])
        purchase_return_value = _money(entry["purchase_return_value"])
        purchase_spend = _money(purchase_value - purchase_return_value)

        unit_cost = unit_costs.get(pid)
        cost_basis: str | None = COST_BASIS_PURCHASES
        if unit_cost is None:
            current = Decimal(str(product.purchase_price or 0))
            unit_cost, cost_basis = (current, COST_BASIS_CURRENT_PRICE) if current > 0 else (None, None)

        cogs = gross_profit = margin_pct = profit_per_unit = None
        if unit_cost is not None:
            cogs = _money(net_units_sold * unit_cost)
            gross_profit = _money(revenue - cogs)
            margin_pct = _ratio(gross_profit * 100, revenue)
            profit_per_unit = _ratio(gross_profit, net_units_sold)

        rows.append({
            "product_id": pid,
            "name": product.name,
            "sku": product.sku,
            "units_sold": entry["units_sold"],
            "units_returned": entry["units_returned"],
            "net_units_sold": net_units_sold,
            "units_bought": entry["units_bought"],
            "units_purchase_returned": entry["units_purchase_returned"],
            "net_units_bought": net_units_bought,
            # Averages are over gross (pre-return) lines: they describe the
            # prices actually transacted, and stay defined when everything
            # sold in the period also came back.
            "average_selling_price": _ratio(sales_value, entry["units_sold"]),
            "average_buying_price": _money(unit_cost) if unit_cost is not None else None,
            "cost_basis": cost_basis,
            "sales_value": sales_value,
            "return_value": return_value,
            "revenue": revenue,
            "purchase_value": purchase_value,
            "purchase_return_value": purchase_return_value,
            "purchase_spend": purchase_spend,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "margin_pct": margin_pct,
            "profit_per_unit": profit_per_unit,
            "current_stock": stock_map.get(pid, zero) if product.maintain_inventory else None,
        })

    _sort_performance_rows(rows, sort_by=sort_by, sort_dir=sort_dir)
    if limit is not None:
        rows = rows[:limit]

    return ProductPerformanceData(rows=rows, totals=_performance_totals(rows))


def _sort_performance_rows(rows: list[dict], *, sort_by: str, sort_dir: str) -> None:
    """Sort in place; rows whose key is None sort last in both directions."""
    if sort_by not in PRODUCT_PERFORMANCE_SORTS:
        raise ValueError(f"Unsupported sort field: {sort_by}")
    reverse = sort_dir == "desc"

    # Name first, so ties on the real key fall back to a stable, readable order.
    rows.sort(key=lambda row: (row["name"] or "").lower())
    if sort_by == "name":
        if reverse:
            rows.reverse()
        return

    present = [row for row in rows if row[sort_by] is not None]
    missing = [row for row in rows if row[sort_by] is None]
    present.sort(key=lambda row: row[sort_by], reverse=reverse)
    rows[:] = present + missing


def _performance_totals(rows: list[dict]) -> dict:
    def total(field: str, subset: list[dict] | None = None) -> Decimal:
        return sum((row[field] for row in (rows if subset is None else subset)), Decimal("0"))

    costed = [row for row in rows if row["cogs"] is not None]
    costed_revenue = total("revenue", costed)
    gross_profit = total("gross_profit", costed)
    return {
        "product_count": len(rows),
        "units_sold": total("units_sold"),
        "units_returned": total("units_returned"),
        "net_units_sold": total("net_units_sold"),
        "units_bought": total("units_bought"),
        "units_purchase_returned": total("units_purchase_returned"),
        "net_units_bought": total("net_units_bought"),
        "sales_value": total("sales_value"),
        "return_value": total("return_value"),
        "revenue": total("revenue"),
        "purchase_value": total("purchase_value"),
        "purchase_return_value": total("purchase_return_value"),
        "purchase_spend": total("purchase_spend"),
        "costed_revenue": costed_revenue,
        "cogs": total("cogs", costed),
        "gross_profit": gross_profit,
        "margin_pct": _ratio(gross_profit * 100, costed_revenue),
        "uncosted_product_count": len(rows) - len(costed),
        "current_price_product_count": sum(1 for row in rows if row["cost_basis"] == COST_BASIS_CURRENT_PRICE),
    }


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
