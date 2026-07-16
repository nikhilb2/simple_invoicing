import csv
from datetime import date, timedelta
from io import BytesIO, StringIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.user import User
from src.schemas.analytics import (
    MonthlySalesReport,
    MonthlySalesRow,
    MonthlySalesTotals,
    ProductSalesReport,
    ProductSalesRow,
    ProductSalesTotals,
    ReportPeriod,
)
from src.services.analytics_reports import (
    average_of,
    build_monthly_sales_report,
    build_product_sales_report,
    month_label,
    month_window,
)
from src.services.financial_year import get_active_fy

router = APIRouter()

VoucherType = Literal["sales", "purchase"]
SortBy = Literal["quantity", "revenue", "name", "stock"]
SortDir = Literal["asc", "desc"]


def _resolve_period(
    db: Session,
    *,
    company_id: int,
    financial_year_id: int | None,
    from_date: date | None,
    to_date: date | None,
) -> ReportPeriod:
    """Work out which window the report covers.

    Precedence: explicit dates, then the requested financial year, then the
    active financial year, then a trailing 12 months. The last fallback is
    deliberate — unlike the day book (which 400s without an FY), an analytics
    page must still render for a company that hasn't set one up yet.
    """
    if from_date is not None and to_date is not None:
        if from_date > to_date:
            raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")
        return ReportPeriod(from_date=from_date, to_date=to_date)

    fy: FinancialYear | None = None
    if financial_year_id is not None:
        fy = (
            db.query(FinancialYear)
            .filter(FinancialYear.id == financial_year_id, FinancialYear.company_id == company_id)
            .first()
        )
        if fy is None:
            raise HTTPException(status_code=404, detail="Financial year not found")
    else:
        fy = get_active_fy(db, company_id=company_id)

    if fy is not None:
        resolved_from = from_date or fy.start_date
        resolved_to = to_date or fy.end_date
        if resolved_from > resolved_to:
            raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")
        return ReportPeriod(
            from_date=resolved_from,
            to_date=resolved_to,
            financial_year_id=fy.id,
            fy_label=fy.label,
        )

    # No dates and no financial year — fall back to a trailing 12 months.
    window = month_window(date.today())
    fallback_from = date(window[0][0], window[0][1], 1)
    fallback_to = date.today()
    resolved_from = from_date or fallback_from
    resolved_to = to_date or fallback_to
    if resolved_from > resolved_to:
        raise HTTPException(status_code=400, detail="from_date must be before or equal to to_date")
    return ReportPeriod(from_date=resolved_from, to_date=resolved_to)


def _monthly_report(
    db: Session,
    *,
    active_company: CompanyProfile,
    voucher_type: str,
    period: ReportPeriod,
    ledger_id: int | None,
) -> MonthlySalesReport:
    data = build_monthly_sales_report(
        db,
        company_id=active_company.id,
        voucher_type=voucher_type,
        from_date=period.from_date,
        to_date=period.to_date,
        ledger_id=ledger_id,
    )

    rows = [
        MonthlySalesRow(
            month=f"{year:04d}-{month:02d}",
            label=month_label(year, month),
            invoice_count=bucket.invoice_count,
            total_sales=float(bucket.total_sales),
            taxable_value=float(bucket.taxable_value),
            gst_collected=float(bucket.gst_collected),
            discount_given=float(bucket.discount_given),
            average_invoice_value=float(average_of(bucket.total_sales, bucket.invoice_count)),
        )
        for year, month, bucket in data.rows
    ]

    totals = MonthlySalesTotals(
        invoice_count=data.totals.invoice_count,
        total_sales=float(data.totals.total_sales),
        taxable_value=float(data.totals.taxable_value),
        gst_collected=float(data.totals.gst_collected),
        discount_given=float(data.totals.discount_given),
        average_invoice_value=float(average_of(data.totals.total_sales, data.totals.invoice_count)),
    )

    return MonthlySalesReport(
        currency_code=active_company.currency_code or "USD",
        voucher_type=voucher_type,
        period=period,
        rows=rows,
        totals=totals,
    )


def _product_report(
    db: Session,
    *,
    active_company: CompanyProfile,
    voucher_type: str,
    period: ReportPeriod,
    ledger_id: int | None,
    product_id: int | None,
    sort_by: str,
    sort_dir: str,
    limit: int | None,
) -> ProductSalesReport:
    data = build_product_sales_report(
        db,
        company_id=active_company.id,
        voucher_type=voucher_type,
        from_date=period.from_date,
        to_date=period.to_date,
        ledger_id=ledger_id,
        product_id=product_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
    )

    rows = [
        ProductSalesRow(
            product_id=row["product_id"],
            name=row["name"],
            sku=row["sku"],
            quantity_sold=float(row["quantity_sold"]),
            sales_amount=float(row["sales_amount"]),
            average_selling_price=float(row["average_selling_price"]),
            total_revenue=float(row["total_revenue"]),
            total_gst=float(row["total_gst"]),
            invoice_count=row["invoice_count"],
            current_stock=float(row["current_stock"]) if row["current_stock"] is not None else None,
        )
        for row in data.rows
    ]

    totals = ProductSalesTotals(
        product_count=data.totals["product_count"],
        quantity_sold=float(data.totals["quantity_sold"]),
        sales_amount=float(data.totals["sales_amount"]),
        total_revenue=float(data.totals["total_revenue"]),
        total_gst=float(data.totals["total_gst"]),
        invoice_count=data.totals["invoice_count"],
    )

    return ProductSalesReport(
        currency_code=active_company.currency_code or "USD",
        voucher_type=voucher_type,
        period=period,
        sort_by=sort_by,
        sort_dir=sort_dir,
        rows=rows,
        totals=totals,
    )


def _csv_response(buffer: StringIO, filename: str) -> StreamingResponse:
    # utf-8-sig: the BOM is what makes Excel read the currency symbols correctly.
    csv_bytes = buffer.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/sales-by-month", response_model=MonthlySalesReport)
def get_sales_by_month(
    voucher_type: VoucherType = Query("sales"),
    financial_year_id: int | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    ledger_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    period = _resolve_period(
        db,
        company_id=active_company.id,
        financial_year_id=financial_year_id,
        from_date=from_date,
        to_date=to_date,
    )
    return _monthly_report(
        db,
        active_company=active_company,
        voucher_type=voucher_type,
        period=period,
        ledger_id=ledger_id,
    )


@router.get("/sales-by-month/csv")
def download_sales_by_month_csv(
    voucher_type: VoucherType = Query("sales"),
    financial_year_id: int | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    ledger_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    period = _resolve_period(
        db,
        company_id=active_company.id,
        financial_year_id=financial_year_id,
        from_date=from_date,
        to_date=to_date,
    )
    report = _monthly_report(
        db,
        active_company=active_company,
        voucher_type=voucher_type,
        period=period,
        ledger_id=ledger_id,
    )

    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([
        "Month", "Invoices", "Total Sales", "Taxable Value",
        "GST Collected", "Discount Given", "Average Invoice Value",
    ])
    for row in report.rows:
        writer.writerow([
            row.label,
            row.invoice_count,
            f"{row.total_sales:.2f}",
            f"{row.taxable_value:.2f}",
            f"{row.gst_collected:.2f}",
            f"{row.discount_given:.2f}",
            f"{row.average_invoice_value:.2f}",
        ])
    writer.writerow([])
    writer.writerow([
        "Totals",
        report.totals.invoice_count,
        f"{report.totals.total_sales:.2f}",
        f"{report.totals.taxable_value:.2f}",
        f"{report.totals.gst_collected:.2f}",
        f"{report.totals.discount_given:.2f}",
        f"{report.totals.average_invoice_value:.2f}",
    ])

    filename = f"sales_by_month_{period.from_date}_{period.to_date}.csv"
    return _csv_response(buffer, filename)


@router.get("/sales-by-product", response_model=ProductSalesReport)
def get_sales_by_product(
    voucher_type: VoucherType = Query("sales"),
    financial_year_id: int | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    ledger_id: int | None = Query(None),
    product_id: int | None = Query(None),
    sort_by: SortBy = Query("revenue"),
    sort_dir: SortDir = Query("desc"),
    limit: int | None = Query(None, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    period = _resolve_period(
        db,
        company_id=active_company.id,
        financial_year_id=financial_year_id,
        from_date=from_date,
        to_date=to_date,
    )
    return _product_report(
        db,
        active_company=active_company,
        voucher_type=voucher_type,
        period=period,
        ledger_id=ledger_id,
        product_id=product_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
    )


@router.get("/sales-by-product/csv")
def download_sales_by_product_csv(
    voucher_type: VoucherType = Query("sales"),
    financial_year_id: int | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    ledger_id: int | None = Query(None),
    product_id: int | None = Query(None),
    sort_by: SortBy = Query("revenue"),
    sort_dir: SortDir = Query("desc"),
    limit: int | None = Query(None, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    period = _resolve_period(
        db,
        company_id=active_company.id,
        financial_year_id=financial_year_id,
        from_date=from_date,
        to_date=to_date,
    )
    report = _product_report(
        db,
        active_company=active_company,
        voucher_type=voucher_type,
        period=period,
        ledger_id=ledger_id,
        product_id=product_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
    )

    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([
        "Product", "Item Code", "Quantity Sold", "Sales Amount", "Average Selling Price",
        "Total Revenue", "Total GST", "Invoices", "Current Stock",
    ])
    for row in report.rows:
        writer.writerow([
            row.name,
            row.sku or "",
            f"{row.quantity_sold:g}",
            f"{row.sales_amount:.2f}",
            f"{row.average_selling_price:.2f}",
            f"{row.total_revenue:.2f}",
            f"{row.total_gst:.2f}",
            row.invoice_count,
            f"{row.current_stock:g}" if row.current_stock is not None else "",
        ])
    writer.writerow([])
    writer.writerow([
        "Totals",
        "",
        f"{report.totals.quantity_sold:g}",
        f"{report.totals.sales_amount:.2f}",
        "",
        f"{report.totals.total_revenue:.2f}",
        f"{report.totals.total_gst:.2f}",
        report.totals.invoice_count,
        "",
    ])

    filename = f"sales_by_product_{period.from_date}_{period.to_date}.csv"
    return _csv_response(buffer, filename)
