"""The GSTR-3B worksheet: an estimate from the books, for cross-checking.

Thin on purpose. The figures come from ``services/gst_returns``; this file picks
the period, reads the documents, and shapes the answer. There is no JSON export
and nothing here writes: this is not a return and must not be mistakable for one.
"""

import csv
from datetime import date, datetime
from io import BytesIO, StringIO

import weasyprint
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.api.deps import get_active_company, get_current_user
from src.core.analytics import distinct_id_for, track
from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.user import User
from src.schemas.gstr3b import Gstr3bWorksheetOut
from src.services.gst_returns.gstr3b import (
    InvalidReturnPeriod,
    ReturnPeriod,
    build_worksheet,
    resolve_return_period,
)
from src.services.gst_returns.gstr3b_data import load_invoices, load_notes
from src.services.pdf_render import safe_url_fetcher
from src.services.pdf_templates.gstr3b_template import build_gstr3b_worksheet_html

router = APIRouter()

_ESTIMATE_DESCRIPTION = (
    "An estimate from the user's own books, for cross-checking only. It is not a filing, and "
    "values auto-populated on the GST portal take precedence."
)


def _period(from_date: date, to_date: date) -> ReturnPeriod:
    try:
        return resolve_return_period(from_date, to_date)
    except InvalidReturnPeriod as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _worksheet(db: Session, period: ReturnPeriod, company: CompanyProfile) -> Gstr3bWorksheetOut:
    company_id = getattr(company, "id", None)
    worksheet = build_worksheet(
        period,
        load_invoices(db, period, company_id),
        load_notes(db, period, company_id),
        company_gstin=getattr(company, "gst", None),
    )
    return Gstr3bWorksheetOut.model_validate(worksheet)


def _filename(worksheet: Gstr3bWorksheetOut, extension: str) -> str:
    # "worksheet" stays in the name so a saved file cannot pass for a return.
    return f"gstr3b_worksheet_{worksheet.from_date}_{worksheet.to_date}.{extension}"


def _csv_text(value: str | None) -> str:
    """Stop free text from running as a formula when the file opens in a spreadsheet."""
    text = value or ""
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text


def _csv_amount(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _worksheet_csv(worksheet: Gstr3bWorksheetOut, company: CompanyProfile) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)

    writer.writerow([f"{worksheet.title}: {worksheet.headline}"])
    writer.writerow([worksheet.disclaimer])
    writer.writerow(["Company", _csv_text(getattr(company, "name", None)), "GSTIN", _csv_text(getattr(company, "gst", None))])
    writer.writerow(["Period", worksheet.period_label, str(worksheet.from_date), str(worksheet.to_date)])
    writer.writerow([])

    writer.writerow(["Section", "Table", "Line", "Source", "Taxable value", "IGST", "CGST", "SGST", "Cess", "Note"])
    for section in worksheet.sections:
        for row in section.rows:
            writer.writerow([
                section.key, row.table, row.label, row.source,
                _csv_amount(row.taxable_value), _csv_amount(row.igst), _csv_amount(row.cgst), _csv_amount(row.sgst),
                "", row.note or "",
            ])
            for component in row.components:
                writer.writerow([
                    section.key, row.table, f"  {component.label}", row.source,
                    _csv_amount(component.taxable_value), _csv_amount(component.igst),
                    _csv_amount(component.cgst), _csv_amount(component.sgst),
                    "", "Part of the line above",
                ])
    writer.writerow([])

    writer.writerow(["6.1 Payment of tax (estimate)", worksheet.setoff.source, worksheet.setoff.note])
    writer.writerow(["Head", "Output tax", "Input credit", "Credit used", "Payable in cash", "Credit carried forward"])
    for line in worksheet.setoff.lines:
        writer.writerow([
            line.head.upper(), _csv_amount(line.output_tax), _csv_amount(line.input_credit),
            _csv_amount(line.credit_used), _csv_amount(line.payable), _csv_amount(line.credit_carried_forward),
        ])
    writer.writerow([
        "Total", "", "", "", _csv_amount(worksheet.setoff.total_payable),
        _csv_amount(worksheet.setoff.total_credit_carried_forward),
    ])
    for row in worksheet.setoff.rows:
        writer.writerow([row.label, row.source])
    writer.writerow(["5.1", worksheet.table_5_1_note])
    writer.writerow([])

    writer.writerow(["Warnings"])
    writer.writerow(["Severity", "Warning", "Explanation", "Document", "Detail"])
    for warning in worksheet.warnings:
        if not warning.documents:
            writer.writerow([warning.severity, warning.title, warning.message])
        for document in warning.documents:
            writer.writerow([
                warning.severity, warning.title, warning.message,
                _csv_text(document.number), _csv_text(document.detail),
            ])
    writer.writerow([])

    writer.writerow(["Known limits"])
    for limit in worksheet.known_limits:
        writer.writerow([limit])

    return buffer.getvalue().encode("utf-8-sig")


@router.get(
    "/worksheet",
    response_model=Gstr3bWorksheetOut,
    summary="GSTR-3B worksheet",
    description=_ESTIMATE_DESCRIPTION,
)
def gstr3b_worksheet(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    period = _period(from_date, to_date)
    worksheet = _worksheet(db, period, active_company)
    track(
        "gstr3b_worksheet_viewed",
        distinct_id_for(current_user),
        {
            "period_type": period.kind,
            "warning_count": len(worksheet.warnings),
            "has_net_payable": worksheet.setoff.total_payable > 0,
        },
    )
    return worksheet


@router.get(
    "/export-csv",
    summary="GSTR-3B worksheet as CSV",
    description=_ESTIMATE_DESCRIPTION,
)
def gstr3b_export_csv(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    period = _period(from_date, to_date)
    worksheet = _worksheet(db, period, active_company)
    body = _worksheet_csv(worksheet, active_company)
    track("gstr3b_exported", distinct_id_for(current_user), {"format": "csv", "period_type": period.kind})
    return StreamingResponse(
        BytesIO(body),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename(worksheet, "csv")}"'},
    )


@router.get(
    "/export-pdf",
    summary="GSTR-3B worksheet as PDF",
    description=_ESTIMATE_DESCRIPTION,
)
def gstr3b_export_pdf(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    period = _period(from_date, to_date)
    worksheet = _worksheet(db, period, active_company)
    html = build_gstr3b_worksheet_html(
        worksheet,
        company_name=getattr(active_company, "name", None),
        company_gstin=getattr(active_company, "gst", None),
        generated_at=datetime.now(),
    )
    pdf_bytes = weasyprint.HTML(string=html, url_fetcher=safe_url_fetcher).write_pdf()
    track("gstr3b_exported", distinct_id_for(current_user), {"format": "pdf", "period_type": period.kind})
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename(worksheet, "pdf")}"'},
    )
