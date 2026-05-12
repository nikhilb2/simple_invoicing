"""Ledger-related PDF HTML template generation."""

from datetime import date, datetime
from html import escape

from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.schemas.ledger import DayBookEntry, LedgerStatementEntry


def _e(text: str | None) -> str:
    return escape(text or "")


def _fmt_inr(value: float, currency: str = "INR") -> str:
    try:
        if currency == "INR":
            # Indian grouping: 1,23,456.78
            neg = value < 0
            value = abs(value)
            integer_part = int(value)
            decimal_part = f"{value - integer_part:.2f}"[1:]  # ".xx"
            s = str(integer_part)
            if len(s) > 3:
                last3 = s[-3:]
                rest = s[:-3]
                groups = []
                while rest:
                    groups.append(rest[-2:])
                    rest = rest[:-2]
                groups.reverse()
                s = ",".join(groups) + "," + last3
            result = f"\u20b9{s}{decimal_part}"
            return f"-{result}" if neg else result
        return f"{value:,.2f} {currency}"
    except Exception:
        return f"{value:,.2f}"


def _build_day_book_html(
    company: CompanyProfile | None,
    from_date: date,
    to_date: date,
    entries: list[DayBookEntry],
    total_debit: float,
    total_credit: float,
    currency: str = "INR",
) -> str:
    entry_rows = ""
    for entry in entries:
        entry_date = entry.date.strftime("%d %b %Y") if entry.date else "N/A"
        dr = _fmt_inr(entry.debit, currency) if entry.debit > 0 else ""
        cr = _fmt_inr(entry.credit, currency) if entry.credit > 0 else ""
        reference = _e(entry.reference_number) if entry.reference_number else f"{_e(entry.voucher_type)} #{entry.entry_id}"
        entry_rows += f"""
        <tr>
          <td>{_e(entry_date)}</td>
          <td>{_e(entry.voucher_type)}</td>
          <td>{reference}</td>
          <td>{_e(entry.ledger_name)}</td>
          <td>{_e(entry.particulars)}</td>
          <td class=\"right\">{dr}</td>
          <td class=\"right\">{cr}</td>
        </tr>"""

    company_name = _e(company.name) if company else "Company"
    company_address = _e(company.address) if company else ""
    company_gst = f"GST: {_e(company.gst)}" if company and company.gst else ""
    company_phone = f"Phone: {_e(company.phone_number)}" if company and company.phone_number else ""
    company_details = " &middot; ".join(p for p in [company_gst, company_phone] if p)

    closing_balance = total_debit - total_credit

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\">
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
    line-height: 1.45;
  }}
  .eyebrow {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .sheet {{ width: 100%; }}
  .sheet__header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    padding-bottom: 14px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 14px;
  }}
  .sheet__company {{
    display: block;
  }}
  .sheet__header h3 {{
    font-size: 15px;
    font-weight: 700;
    margin-bottom: 3px;
  }}
  .sheet__header p {{
    font-size: 9px;
    color: #6b7280;
    margin-bottom: 1px;
  }}
  .sheet__meta {{ text-align: right; }}
  .sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #1a56db;
    background: #eff6ff;
    margin-bottom: 6px;
  }}
  .summary {{
    display: flex;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 14px;
  }}
  .summary-item {{
    flex: 1;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 10px 12px;
    text-align: center;
  }}
  .summary-item .label {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .summary-item .value {{
    font-size: 13px;
    font-weight: 700;
    color: #1f2937;
  }}
  .summary-item.highlight .value {{
    color: #1a56db;
    font-size: 15px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 14px;
    font-size: 9px;
  }}
  thead th {{
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
  thead th.right {{ text-align: right; }}
  tbody td {{
    padding: 6px 8px;
    border-bottom: 1px solid #e5e7eb;
    vertical-align: top;
  }}
  tbody td.right {{ text-align: right; }}
  tbody tr:last-child td {{ border-bottom: 2px solid #d1d5db; }}
  .footer {{
    margin-top: 8px;
    text-align: right;
  }}
  .footer .total-label {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .footer .total-value {{
    font-size: 18px;
    font-weight: 700;
    color: #1a56db;
  }}
  .muted {{ font-size: 8px; color: #9ca3af; }}
</style>
</head>
<body>
<div class=\"sheet\">
  <header class=\"sheet__header\">
    <div class=\"sheet__company\">
      <div>
        <p class=\"eyebrow\">Issued by</p>
        <h3>{company_name}</h3>
        <p>{company_address}</p>
        <p>{company_details}</p>
      </div>
    </div>
    <div class=\"sheet__meta\">
      <span class=\"badge\">Day Book</span>
      <h2>{from_date.strftime('%d %b %Y')} &ndash; {to_date.strftime('%d %b %Y')}</h2>
      <p>{len(entries)} voucher entries</p>
    </div>
  </header>

  <section class=\"summary\">
    <div class=\"summary-item\">
      <p class=\"label\">Total Debit</p>
      <p class=\"value\">{_fmt_inr(total_debit, currency)}</p>
    </div>
    <div class=\"summary-item\">
      <p class=\"label\">Total Credit</p>
      <p class=\"value\">{_fmt_inr(total_credit, currency)}</p>
    </div>
    <div class=\"summary-item highlight\">
      <p class=\"label\">Net Movement</p>
      <p class=\"value\">{_fmt_inr(closing_balance, currency)}</p>
    </div>
  </section>

  <section>
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Voucher</th>
          <th>Reference</th>
          <th>Ledger</th>
          <th>Particulars</th>
          <th class=\"right\">Debit</th>
          <th class=\"right\">Credit</th>
        </tr>
      </thead>
      <tbody>
        {entry_rows if entry_rows else '<tr><td colspan="7" style="text-align:center;color:#9ca3af;">No entries in this period</td></tr>'}
      </tbody>
    </table>
  </section>

  <section class=\"footer\">
    <p class=\"total-label\">Net Movement</p>
    <p class=\"total-value\">{_fmt_inr(closing_balance, currency)}</p>
    <p class=\"muted\">Generated on {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}</p>
  </section>
</div>
</body>
</html>"""
    return html



def _build_statement_html(
    ledger: Ledger,
    company: CompanyProfile | None,
    from_date: date,
    to_date: date,
    opening_balance: float,
    period_debit: float,
    period_credit: float,
    closing_balance: float,
    entries: list[LedgerStatementEntry],
    currency: str = "INR",
) -> str:
    entry_rows = ""
    for entry in entries:
        entry_date = entry.date.strftime("%d %b %Y") if entry.date else "N/A"
        dr = _fmt_inr(entry.debit, currency) if entry.debit > 0 else ""
        cr = _fmt_inr(entry.credit, currency) if entry.credit > 0 else ""
        ref_number = _e(entry.reference_number) if entry.reference_number else f"#{entry.entry_id}"
        entry_rows += f"""
        <tr>
          <td>{_e(entry_date)}</td>
          <td>{ref_number}</td>
          <td>{_e(entry.particulars)}</td>
          <td class=\"right\">{dr}</td>
          <td class=\"right\">{cr}</td>
        </tr>"""

    company_name = _e(company.name) if company else "Company"
    company_address = _e(company.address) if company else ""
    company_gst = f"GST: {_e(company.gst)}" if company and company.gst else ""
    company_phone = f"Phone: {_e(company.phone_number)}" if company and company.phone_number else ""
    company_details = " &middot; ".join(p for p in [company_gst, company_phone] if p)
    ledger_gst = f"GST: {_e(ledger.gst)}" if ledger.gst else ""
    ledger_phone = f"Phone: {_e(ledger.phone_number)}" if ledger.phone_number else ""
    ledger_details = " &middot; ".join(p for p in [ledger_gst, ledger_phone] if p)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\">
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
  .sheet {{ width: 100%; }}
  .sheet__header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 16px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 16px;
  }}
  .sheet__header h3 {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .sheet__header p {{
    font-size: 9px;
    color: #6b7280;
    margin-bottom: 1px;
  }}
  .sheet__meta {{
    text-align: right;
  }}
  .sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .sheet__meta p {{
    font-size: 9px;
    color: #6b7280;
  }}
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #1a56db;
    background: #eff6ff;
    margin-bottom: 6px;
  }}
  .ledger-info {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 16px;
  }}
  .ledger-info h4 {{
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 2px;
  }}
  .ledger-info p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .summary {{
    display: flex;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
  }}
  .summary-item {{
    flex: 1;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 10px 12px;
    text-align: center;
  }}
  .summary-item .label {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .summary-item .value {{
    font-size: 13px;
    font-weight: 700;
    color: #1f2937;
  }}
  .summary-item.highlight .value {{
    color: #1a56db;
    font-size: 15px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 16px;
    font-size: 9px;
  }}
  thead th {{
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
  thead th.right {{ text-align: right; }}
  tbody td {{
    padding: 6px 8px;
    border-bottom: 1px solid #e5e7eb;
    vertical-align: middle;
  }}
  tbody td.right {{ text-align: right; }}
  tbody tr:last-child td {{
    border-bottom: 2px solid #d1d5db;
  }}
  .footer {{
    margin-top: 8px;
    text-align: right;
  }}
  .footer .total-label {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7280;
    margin-bottom: 2px;
  }}
  .footer .total-value {{
    font-size: 20px;
    font-weight: 700;
    color: #1a56db;
  }}
  .muted {{ font-size: 8px; color: #9ca3af; }}
</style>
</head>
<body>
<div class=\"sheet\">
  <header class=\"sheet__header\">
    <div>
      <p class=\"eyebrow\">Issued by</p>
      <h3>{company_name}</h3>
      <p>{company_address}</p>
      <p>{company_details}</p>
    </div>
    <div class=\"sheet__meta\">
      <span class=\"badge\">Ledger Statement</span>
      <h2>{_e(ledger.name)}</h2>
      <p>{from_date.strftime('%d %b %Y')} &ndash; {to_date.strftime('%d %b %Y')}</p>
    </div>
  </header>

  <section class=\"ledger-info\">
    <p class=\"eyebrow\">Ledger</p>
    <h4>{_e(ledger.name)}</h4>
    <p>{_e(ledger.address)}</p>
    <p>{ledger_details}</p>
  </section>

  <section class=\"summary\">
    <div class=\"summary-item\">
      <p class=\"label\">Opening Balance</p>
      <p class=\"value\">{_fmt_inr(opening_balance, currency)}</p>
    </div>
    <div class=\"summary-item\">
      <p class=\"label\">Period Debit</p>
      <p class=\"value\">{_fmt_inr(period_debit, currency)}</p>
    </div>
    <div class=\"summary-item\">
      <p class=\"label\">Period Credit</p>
      <p class=\"value\">{_fmt_inr(period_credit, currency)}</p>
    </div>
    <div class=\"summary-item highlight\">
      <p class=\"label\">Closing Balance</p>
      <p class=\"value\">{_fmt_inr(closing_balance, currency)}</p>
    </div>
  </section>

  <section>
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Voucher</th>
          <th>Particulars</th>
          <th class=\"right\">Debit</th>
          <th class=\"right\">Credit</th>
        </tr>
      </thead>
      <tbody>
        {entry_rows if entry_rows else '<tr><td colspan="5" style="text-align:center;color:#9ca3af;">No entries in this period</td></tr>'}
      </tbody>
    </table>
  </section>

  <section class=\"footer\">
    <p class=\"total-label\">Closing Balance</p>
    <p class=\"total-value\">{_fmt_inr(closing_balance, currency)}</p>
    <p class=\"muted\">Generated on {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}</p>
  </section>
</div>
</body>
</html>"""
    return html