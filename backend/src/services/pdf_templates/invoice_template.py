"""Sales invoice HTML template generation."""

from src.models.company_account import CompanyAccount
from src.models.invoice import Invoice
from src.models.product import Product

from .builders import (
    _build_pdf_payment_details_html,
    _build_pdf_table_colgroup,
    _build_pdf_tax_breakup_rows,
    _build_pdf_tax_header_cells,
    _build_pdf_tax_row_cells,
    _amount_in_words_indian,
    _e,
    _fmt_currency,
    _pdf_display_quantity,
    _pdf_display_unit,
    _pdf_unit_price_including_tax,
)
from .purchase_template import _build_purchase_invoice_html, _is_interstate_supply, _extract_pan_from_gstin


def _copy_label(n: int) -> str:
    """Generate a copy label (Original, Duplicate, etc.) for invoice copies."""
    _labels = {1: "Original", 2: "Duplicate", 3: "Triplicate"}
    if n in _labels:
        return _labels[n]
    suffix = ("th" if (n % 100) in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))
    return f"{n}{suffix} Copy"


def _build_invoice_html(invoice: Invoice, products: list[Product], invoice_bank_accounts: list[CompanyAccount] | None = None, copy_label: str = "Original") -> str:
    """Generate HTML for a sales invoice."""
    if invoice_bank_accounts is None:
        invoice_bank_accounts = []
    
    if invoice.voucher_type == "purchase":
        return _build_purchase_invoice_html(invoice, products)

    currency = invoice.company_currency_code or "USD"
    voucher_label = "Sales" if invoice.voucher_type == "sales" else "Purchase"
    inv_number = invoice.invoice_number or f"#{invoice.id}"
    inv_date = invoice.invoice_date.strftime("%d %b %Y") if invoice.invoice_date else (invoice.created_at.strftime("%d %b %Y") if invoice.created_at else "N/A")
    interstate_supply = _is_interstate_supply(invoice.company_gst, invoice.ledger_gst)
    tax_header_cells = _build_pdf_tax_header_cells(interstate_supply)
    table_colgroup = _build_pdf_table_colgroup(interstate_supply)

    product_map = {p.id: p for p in products}

    # Build line item rows
    item_rows = ""
    for idx, item in enumerate(invoice.items or [], start=1):
        prod = product_map.get(item.product_id)
        product_name = _e(prod.name) if prod else f"Product #{item.product_id}"
        item_description = _e(item.description)
        product_cell_html = product_name
        if item_description:
            product_cell_html = f"{product_name}<br><span class=\"muted-text\">{item_description}</span>"
        sku = _e(prod.sku) if prod else "N/A"
        hsn = _e(item.hsn_sac or (prod.hsn_sac if prod else None) or "N/A")
        unit = _e(_pdf_display_unit(getattr(prod, "unit", None) if prod else None))
        quantity_display = _pdf_display_quantity(item.quantity, getattr(prod, "allow_decimal", None) if prod else None)
        tax_row_cells = _build_pdf_tax_row_cells(item, currency, interstate_supply)

        item_rows += f"""
        <tr>
          <td>{idx}</td>
          <td>{product_cell_html}</td>
          <td>{sku}</td>
          <td>{hsn}</td>
          <td class="right">{quantity_display}</td>
          <td>{unit}</td>
          <td class="right">{_fmt_currency(_pdf_unit_price_including_tax(item), currency)}</td>
          {tax_row_cells}
          <td class="right">{_fmt_currency(float(item.line_total), currency)}</td>
        </tr>"""

    # Company details
    company_detail_parts = []
    if invoice.company_gst:
        company_detail_parts.append(f"GST: {_e(invoice.company_gst)}")
        company_pan = _extract_pan_from_gstin(invoice.company_gst)
        if company_pan:
            company_detail_parts.append(f"PAN: {_e(company_pan)}")
    if invoice.company_phone:
        company_detail_parts.append(f"Phone: {_e(invoice.company_phone)}")
    company_details = " &middot; ".join(company_detail_parts)

    company_contact_parts = []
    if invoice.company_email:
        company_contact_parts.append(f"Email: {_e(invoice.company_email)}")
    if invoice.company_website:
        company_contact_parts.append(f"Web: {_e(invoice.company_website)}")
    company_contact = " &middot; ".join(company_contact_parts)

    # Bill-to details
    billto_parts = []
    if invoice.ledger_gst:
        billto_parts.append(f"GST: {_e(invoice.ledger_gst)}")
        billto_pan = _extract_pan_from_gstin(invoice.ledger_gst)
        if billto_pan:
            billto_parts.append(f"PAN: {_e(billto_pan)}")
    if invoice.ledger_phone:
        billto_parts.append(f"Phone: {_e(invoice.ledger_phone)}")
    billto_details = " &middot; ".join(billto_parts)

    invoice_title = "Tax Invoice" if invoice.ledger_gst else "Sales Invoice"

    round_off_amount = float(invoice.round_off_amount or 0)
    show_round_off = bool(invoice.apply_round_off and round_off_amount != 0)
    round_off_html = (
        f'<p>Round off: {_fmt_currency(round_off_amount, currency)}</p>' if show_round_off else ''
    )
    tax_breakup_rows = _build_pdf_tax_breakup_rows(invoice, currency)
    payment_details_html = _build_pdf_payment_details_html(invoice_bank_accounts)
    reference_notes_html = ""
    if invoice.reference_notes:
        reference_notes_html = f"""
  <section class=\"invoice-sheet__reference-notes\">
    <p class=\"eyebrow\">Reference notes</p>
    <p class=\"invoice-sheet__reference-notes-value\">{_e(invoice.reference_notes)}</p>
  </section>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
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
  .invoice-sheet {{
    width: 100%;
  }}
  .invoice-sheet__header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 16px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 16px;
  }}
  .invoice-sheet__header h3 {{
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .invoice-sheet__header p {{
    font-size: 9px;
    color: #6b7280;
    margin-bottom: 1px;
  }}
  .invoice-sheet__meta {{
    text-align: right;
  }}
  .invoice-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #1a56db;
    background: #eff6ff;
    margin-bottom: 6px;
  }}
  .invoice-sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .invoice-sheet__meta p {{
    font-size: 9px;
    color: #6b7280;
  }}
  .invoice-sheet__billto {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 16px;
  }}
  .invoice-sheet__billto h4 {{
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 2px;
  }}
  .invoice-sheet__billto p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .invoice-sheet__reference-notes {{
    border: 1px dashed #d1d5db;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 14px;
    background: #f9fafb;
  }}
  .invoice-sheet__reference-notes-value {{
    font-size: 9px;
    color: #374151;
  }}
  .invoice-sheet__table {{
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    margin-bottom: 16px;
    font-size: 8px;
  }}
  .invoice-sheet__table thead th {{
    background: #f3f4f6;
    color: #374151;
    font-weight: 600;
    font-size: 7px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    line-height: 1.2;
    padding: 5px 4px;
    border-bottom: 2px solid #d1d5db;
    text-align: left;
    white-space: normal;
    overflow-wrap: anywhere;
  }}
  .invoice-sheet__table thead th.right {{
    text-align: right;
  }}
  .invoice-sheet__table tbody td {{
    padding: 5px 4px;
    border-bottom: 1px solid #e5e7eb;
    vertical-align: middle;
    white-space: normal;
    overflow-wrap: anywhere;
  }}
  .invoice-sheet__table tbody td.right {{
    text-align: right;
  }}
  .invoice-sheet__table tbody tr:last-child td {{
    border-bottom: 2px solid #d1d5db;
  }}
  .invoice-sheet__footer {{
    display: flex;
    justify-content: flex-end;
    margin-top: 8px;
  }}
  .invoice-sheet__bank-section {{
    margin-top: 14px;
    border-top: 1px solid #e5e7eb;
    padding-top: 10px;
  }}
  .invoice-sheet__bank-section p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .invoice-sheet__bank-cards {{
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    align-items: stretch;
  }}
  .invoice-sheet__bank-card {{
    flex: 1 1 240px;
    max-width: 320px;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    background: #f9fafb;
    padding: 10px 12px;
  }}
  .invoice-sheet__bank-card p {{
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
  }}
  .invoice-sheet__bank-card-title {{
    font-size: 10px !important;
    font-weight: 700;
    color: #1f2937 !important;
    margin-bottom: 4px !important;
  }}
  .invoice-sheet__totals {{
    min-width: 240px;
    text-align: right;
  }}
  .invoice-sheet__totals p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .invoice-sheet__total-value {{
    font-size: 20px !important;
    font-weight: 700;
    color: #1a56db !important;
    margin-top: 4px;
    margin-bottom: 4px;
  }}
  .muted-text {{
    font-size: 8px;
    color: #9ca3af;
  }}
  .invoice-title {{
    text-align: center;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #1f2937;
    padding-bottom: 10px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 16px;
  }}
  .copy-label {{
    text-align: right;
    font-size: 8px;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 4px;
  }}
  .invoice-amount-words {{
    font-size: 8px;
    font-style: italic;
    color: #374151;
    margin-top: 2px;
  }}
</style>
</head>
<body>
<div class="invoice-sheet">
  <div class="copy-label">{copy_label}</div>
  <div class="invoice-title">{invoice_title}</div>
  <header class="invoice-sheet__header">
    <div>
      <p class="eyebrow">Billed by</p>
      <h3>{_e(invoice.company_name) or 'Company not set'}</h3>
      <p>{_e(invoice.company_address) or 'Address not provided'}</p>
      <p>{company_details}</p>
      <p>{company_contact}</p>
    </div>
    <div class="invoice-sheet__meta">
      <span class="invoice-badge">{voucher_label}</span>
      <h2>Invoice {_e(inv_number)}</h2>
      <p>Date: {inv_date}</p>
      <p>Currency: {_e(currency)}</p>
    </div>
  </header>

  <section class="invoice-sheet__billto">
    <p class="eyebrow">Bill to</p>
    <h4>{_e(invoice.ledger_name) or 'Unknown ledger'}</h4>
    <p>{_e(invoice.ledger_address) or 'Address not provided'}</p>
    <p>{billto_details}</p>
  </section>

  {reference_notes_html}

  <section>
    <table class="invoice-sheet__table">
      {table_colgroup}
      <thead>
        <tr>
          <th>#</th>
          <th>Item</th>
          <th>SKU</th>
          <th>HSN/SAC</th>
          <th class="right">Qty</th>
          <th>Unit</th>
          <th class="right">Unit Price<br><span style="font-size: 6px; font-weight: 500; text-transform: none;">(with tax)</span></th>
          {tax_header_cells}
          <th class="right">Amount</th>
        </tr>
      </thead>
      <tbody>
        {item_rows}
      </tbody>
    </table>
  </section>

  <section class="invoice-sheet__footer">
    <div class="invoice-sheet__totals">
      <p class="eyebrow">Tax breakup</p>
      <p>Taxable: {_fmt_currency(float(invoice.taxable_amount or 0), currency)}</p>
      {tax_breakup_rows}
      <p>Total tax: {_fmt_currency(float(invoice.total_tax_amount or 0), currency)}</p>
      {round_off_html}
      <p class="eyebrow" style="margin-top: 10px;">Total due</p>
      <p class="invoice-sheet__total-value">{_fmt_currency(float(invoice.total_amount), currency)}</p>
      <p class="invoice-amount-words">{_amount_in_words_indian(float(invoice.total_amount), currency)}</p>
      <p class="muted-text">Authorized by {_e(invoice.company_name) or 'Billing company'}</p>
    </div>
  </section>

  <section class="invoice-sheet__bank-section">
    <p class="eyebrow">Payment details</p>
    {payment_details_html}
  </section>
</div>
</body>
</html>"""
    return html


def _build_multi_copy_invoice_html(invoice: Invoice, products: list[Product], invoice_bank_accounts: list[CompanyAccount], copies: int) -> str:
    """Generate HTML for multiple copies of an invoice in a single document."""
    if invoice.voucher_type == "purchase":
        return _build_purchase_invoice_html(invoice, products)
    if copies == 1:
        return _build_invoice_html(invoice, products, invoice_bank_accounts, copy_label=_copy_label(1))

    pages = []
    first_html: str | None = None
    for i in range(1, copies + 1):
        full_html = _build_invoice_html(invoice, products, invoice_bank_accounts, copy_label=_copy_label(i))
        if i == 1:
            first_html = full_html
        body_open_end = full_html.index('<body>') + len('<body>')
        body_close_start = full_html.rindex('</body>')
        body_content = full_html[body_open_end:body_close_start].strip()
        page_style = '' if i == copies else ' style="break-after: page; page-break-after: always;"'
        pages.append(f'<div{page_style}>\n{body_content}\n</div>')

    assert first_html is not None
    body_open_end = first_html.index('<body>') + len('<body>')
    combined = '\n'.join(pages)
    return first_html[:body_open_end] + '\n' + combined + '\n</body>\n</html>'
