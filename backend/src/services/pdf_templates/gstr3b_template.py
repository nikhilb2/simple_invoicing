"""PDF HTML for the GSTR-3B worksheet.

The first thing on every page says this is not a return, because a PDF gets
printed and passed around without the screen it came from.
"""

from datetime import datetime

from src.schemas.gstr3b import Gstr3bRow, Gstr3bRowComponent, Gstr3bWorksheetOut

from .builders import _e
from .ledger_template import _fmt_inr

# A warning can name hundreds of invoices. The page and the CSV list all of them;
# here a sample is enough to act on, and the count says how many there are.
_MAX_DOCUMENTS_PER_WARNING = 15

_SOURCE_LABELS = {"from_books": "From books", "not_tracked": "Not tracked"}


def _amount(value: float | None) -> str:
    return "" if value is None else _e(_fmt_inr(value))


def _component_row(component: Gstr3bRowComponent) -> str:
    return (
        '<tr class="component">'
        f'<td></td><td>{_e(component.label)}</td><td></td>'
        f'<td class="right">{_amount(component.taxable_value)}</td>'
        f'<td class="right">{_amount(component.igst)}</td>'
        f'<td class="right">{_amount(component.cgst)}</td>'
        f'<td class="right">{_amount(component.sgst)}</td>'
        '</tr>'
    )


def _row(row: Gstr3bRow) -> str:
    note = f'<div class="note">{_e(row.note)}</div>' if row.note else ""
    tracked = row.source == "from_books"
    if tracked:
        figures = (
            f'<td class="right">{_amount(row.taxable_value)}</td>'
            f'<td class="right">{_amount(row.igst)}</td>'
            f'<td class="right">{_amount(row.cgst)}</td>'
            f'<td class="right">{_amount(row.sgst)}</td>'
        )
    else:
        figures = '<td colspan="4" class="center muted">Not tracked</td>'
    components = "".join(_component_row(component) for component in row.components)
    return (
        f'<tr class="{"tracked" if tracked else "untracked"}">'
        f'<td class="nowrap">{_e(row.table)}</td>'
        f'<td>{_e(row.label)}{note}</td>'
        f'<td><span class="badge badge--{_e(row.source)}">{_SOURCE_LABELS[row.source]}</span></td>'
        f'{figures}</tr>{components}'
    )


TABLE_HEAD = (
    '<thead><tr><th>Table</th><th>Line</th><th>Source</th>'
    '<th class="right">Taxable value</th><th class="right">IGST</th>'
    '<th class="right">CGST</th><th class="right">SGST</th></tr></thead>'
)


def _warnings_html(worksheet: Gstr3bWorksheetOut) -> str:
    if not worksheet.warnings:
        return '<p class="muted">No document-level warnings for this period. The known limits below still apply.</p>'
    blocks = []
    for warning in worksheet.warnings:
        documents = warning.documents
        listed = ", ".join(_e(document.number) for document in documents[:_MAX_DOCUMENTS_PER_WARNING])
        more = len(documents) - _MAX_DOCUMENTS_PER_WARNING
        suffix = f" and {more} more" if more > 0 else ""
        count = f" ({len(documents)})" if documents else ""
        docs = f'<div class="docs">{listed}{suffix}</div>' if documents else ""
        blocks.append(
            f'<div class="warning warning--{_e(warning.severity)}">'
            f'<div class="warning__title">{_e(warning.title)}{count}</div>'
            f'<div>{_e(warning.message)}</div>{docs}</div>'
        )
    return "".join(blocks)


def build_gstr3b_worksheet_html(
    worksheet: Gstr3bWorksheetOut,
    *,
    company_name: str | None,
    company_gstin: str | None,
    generated_at: datetime,
) -> str:
    sections = "".join(
        f'<div class="section"><h2>{_e(section.title)}</h2>'
        + (f'<p class="section-note">{_e(section.note)}</p>' if section.note else "")
        + f'<table>{TABLE_HEAD}<tbody>{"".join(_row(row) for row in section.rows)}</tbody></table></div>'
        for section in worksheet.sections
    )

    setoff = worksheet.setoff
    setoff_rows = "".join(
        f'<tr><td>{_e(line.head.upper())}</td>'
        f'<td class="right">{_amount(line.output_tax)}</td>'
        f'<td class="right">{_amount(line.input_credit)}</td>'
        f'<td class="right">{_amount(line.credit_used)}</td>'
        f'<td class="right">{_amount(line.payable)}</td>'
        f'<td class="right">{_amount(line.credit_carried_forward)}</td></tr>'
        for line in setoff.lines
    )
    setoff_untracked = "".join(
        f'<tr class="untracked"><td colspan="6">{_e(row.label)}: not tracked</td></tr>' for row in setoff.rows
    )
    limits = "".join(f"<li>{_e(limit)}</li>" for limit in worksheet.known_limits)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
    @page {{
        size: A4 landscape;
        margin: 18mm 12mm 14mm;
        @top-center {{ content: "{_e(worksheet.headline)}. Estimate from your books, not a filing."; font-size: 8pt; color: #8a1c1c; font-family: Arial, sans-serif; }}
        @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-size: 8pt; color: #666; font-family: Arial, sans-serif; }}
    }}
    body {{ font-family: Arial, sans-serif; font-size: 9.5pt; color: #1a1a1a; }}
    h1 {{ font-size: 18pt; margin: 0 0 2px; color: #8a1c1c; }}
    .subtitle {{ font-size: 11pt; margin: 0 0 6px; }}
    .meta {{ color: #555; margin: 0 0 10px; }}
    .disclaimer {{ border: 1.5pt solid #8a1c1c; background: #fdf3f3; padding: 8px 10px; margin-bottom: 12px; font-weight: bold; }}
    h2 {{ font-size: 11.5pt; margin: 16px 0 5px; page-break-after: avoid; }}
    /* A title stranded from its table, or one row alone on the next page, reads badly. */
    .section {{ page-break-inside: avoid; }}
    .section-note {{ margin: 0 0 5px; color: #555; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 8px; }}
    th, td {{ border: 0.5pt solid #bbb; padding: 4px 6px; vertical-align: top; }}
    th {{ background: #f1f1f1; text-align: left; font-size: 8.5pt; }}
    tr {{ page-break-inside: avoid; }}
    .right {{ text-align: right; white-space: nowrap; }}
    .center {{ text-align: center; }}
    .nowrap {{ white-space: nowrap; }}
    .muted {{ color: #777; }}
    .note {{ font-size: 8pt; color: #666; margin-top: 2px; }}
    .component td {{ background: #fafafa; font-size: 8.5pt; color: #444; }}
    .untracked td {{ color: #777; }}
    .badge {{ font-size: 7.5pt; padding: 1px 4px; border-radius: 3px; white-space: nowrap; }}
    .badge--from_books {{ background: #e3f1e6; color: #1d5a2c; }}
    .badge--not_tracked {{ background: #ececec; color: #555; }}
    .warning {{ border-left: 3pt solid #b7791f; padding: 3px 8px; margin-bottom: 7px; page-break-inside: avoid; }}
    .warning--info {{ border-left-color: #888; }}
    .warning__title {{ font-weight: bold; }}
    .docs {{ font-size: 8.5pt; color: #444; margin-top: 2px; }}
    ul {{ margin: 4px 0; padding-left: 16px; }}
    li {{ margin-bottom: 3px; }}
    .generated {{ font-size: 8pt; color: #888; margin-top: 12px; }}
</style></head><body>
<h1>{_e(worksheet.headline)}</h1>
<p class="subtitle">{_e(worksheet.title)} for {_e(worksheet.period_label)}</p>
<p class="meta">{_e(company_name)}{" &middot; GSTIN " + _e(company_gstin) if company_gstin else ""} &middot; {worksheet.from_date} to {worksheet.to_date}</p>
<div class="disclaimer">{_e(worksheet.disclaimer)}</div>

<h2>Warnings</h2>
{_warnings_html(worksheet)}

{sections}

<h2>6.1 Payment of tax (estimate)</h2>
<p class="section-note">{_e(setoff.note)}</p>
<table>
    <thead><tr><th>Head</th><th class="right">Output tax</th><th class="right">Input credit</th>
    <th class="right">Credit used</th><th class="right">Payable in cash</th><th class="right">Credit carried forward</th></tr></thead>
    <tbody>
    {setoff_rows}
    <tr><td><strong>Total</strong></td><td></td><td></td><td></td>
        <td class="right"><strong>{_amount(setoff.total_payable)}</strong></td>
        <td class="right"><strong>{_amount(setoff.total_credit_carried_forward)}</strong></td></tr>
    {setoff_untracked}
    </tbody>
</table>

<h2>Known limits</h2>
<ul>{limits}</ul>
<p class="generated">Generated on {generated_at.strftime('%Y-%m-%d %H:%M')}. Check every figure against the GST portal before filing.</p>
</body></html>"""
