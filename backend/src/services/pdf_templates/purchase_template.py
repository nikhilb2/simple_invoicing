"""Purchase invoice HTML template generation."""

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


def _extract_pan_from_gstin(gstin: str | None) -> str | None:
    """Extract PAN from a 15-character GSTIN."""
    normalized = (gstin or "").strip().upper()
    if len(normalized) != 15:
        return None
    return normalized[2:12]


def _is_interstate_supply(company_gst: str | None, ledger_gst: str | None) -> bool:
    """Check if the invoice is for an interstate supply based on GST state codes."""
    if not company_gst or not ledger_gst or len(company_gst) < 2 or len(ledger_gst) < 2:
        return False
    return company_gst[:2] != ledger_gst[:2]


def _build_purchase_invoice_html(invoice: Invoice, products: list[Product]) -> str:
    """Generate HTML for a purchase invoice (supplier at top-left, your company top-right,
    no bank details in footer, optional supplier ref row)."""
    currency = invoice.company_currency_code or "USD"
    inv_number = invoice.invoice_number or f"#{invoice.id}"
    inv_date = invoice.invoice_date.strftime("%d %b %Y") if invoice.invoice_date else (invoice.created_at.strftime("%d %b %Y") if invoice.created_at else "N/A")
    interstate_supply = _is_interstate_supply(invoice.company_gst, invoice.ledger_gst)
    tax_header_cells = _build_pdf_tax_header_cells(interstate_supply)
    table_colgroup = _build_pdf_table_colgroup(interstate_supply)

    product_map = {p.id: p for p in products}

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

    # Supplier details are stored as ledger_* (buyer_* in DB) on purchase invoices
    supplier_detail_parts = []
    if invoice.ledger_gst:
        supplier_detail_parts.append(f"GST: {_e(invoice.ledger_gst)}")
        supplier_pan = _extract_pan_from_gstin(invoice.ledger_gst)
        if supplier_pan:
            supplier_detail_parts.append(f"PAN: {_e(supplier_pan)}")
    if invoice.ledger_phone:
        supplier_detail_parts.append(f"Phone: {_e(invoice.ledger_phone)}")
    supplier_details = " &middot; ".join(supplier_detail_parts)

    # Your company (receiving / bill-to party)
    company_detail_parts = []
    if invoice.company_gst:
        company_detail_parts.append(f"GST: {_e(invoice.company_gst)}")
        company_pan = _extract_pan_from_gstin(invoice.company_gst)
        if company_pan:
            company_detail_parts.append(f"PAN: {_e(company_pan)}")
    company_details = " &middot; ".join(company_detail_parts)

    # Optional supplier reference row
    supplier_ref_html = ""
    if invoice.supplier_invoice_number:
        supplier_ref_html = f"""
  <section class="invoice-sheet__supplierref">
    <span class="eyebrow">Supplier Ref:</span>
    <span class="invoice-sheet__supplierref-value">{_e(invoice.supplier_invoice_number)}</span>
  </section>"""

    round_off_amount = float(invoice.round_off_amount or 0)
    show_round_off = bool(invoice.apply_round_off and round_off_amount != 0)
    round_off_html = (
        f'<p>Round off: {_fmt_currency(round_off_amount, currency)}</p>' if show_round_off else ''
    )
    tax_breakup_rows = _build_pdf_tax_breakup_rows(invoice, currency)

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
    margin-bottom: 12px;
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
  .invoice-sheet__header-right {{
    text-align: right;
  }}
  .invoice-sheet__header-right h3 {{
    font-size: 14px;
  }}
  .invoice-sheet__titleblock {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    padding: 10px 14px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
  }}
  .invoice-sheet__titleblock h2 {{
    font-size: 14px;
    font-weight: 700;
  }}
  .invoice-sheet__titleblock p {{
    font-size: 9px;
    color: #6b7280;
    margin-left: auto;
  }}
  .invoice-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #065f46;
    background: #ecfdf5;
  }}
  .invoice-sheet__supplierref {{
    margin-bottom: 12px;
    font-size: 9px;
    color: #374151;
  }}
  .invoice-sheet__supplierref-value {{
    font-size: 9px;
    font-weight: 600;
    color: #1f2937;
    margin-left: 4px;
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
  .invoice-sheet__totals {{
    text-align: right;
    min-width: 220px;
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
  <header class="invoice-sheet__header">
    <div>
      <p class="eyebrow">Supplier</p>
      <h3>{_e(invoice.ledger_name) or 'Unknown supplier'}</h3>
      <p>{_e(invoice.ledger_address) or 'Address not provided'}</p>
      <p>{supplier_details}</p>
    </div>
    <div class="invoice-sheet__header-right">
      <p class="eyebrow">Bill To</p>
      <h3>{_e(invoice.company_name) or 'Your company'}</h3>
      <p>{_e(invoice.company_address) or 'Address not provided'}</p>
      <p>{company_details}</p>
    </div>
  </header>

  <div class="invoice-sheet__titleblock">
    <span class="invoice-badge">Purchase Invoice</span>
    <h2>Invoice {_e(inv_number)}</h2>
    <p>Date: {inv_date} &nbsp;&middot;&nbsp; Currency: {_e(currency)}</p>
  </div>
{supplier_ref_html}
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
      <p class="muted-text">Received by {_e(invoice.company_name) or 'Your company'}</p>
    </div>
  </section>
</div>
</body>
</html>"""
    return html
