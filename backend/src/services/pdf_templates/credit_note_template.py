"""Credit note HTML template generation.

Laid out like the sales invoice it reverses, so the customer can hold the two
side by side: same header, same party block, same tax columns. The note's own
amounts are the source of truth; the original invoices only supply the party
and seller snapshot they were issued under, and the invoice numbers a GST
credit note has to cite.
"""

from decimal import Decimal

from src.models.company import CompanyProfile
from src.models.buyer import Buyer as Ledger
from src.models.credit_note import CreditNote
from src.models.invoice import Invoice
from src.models.product import Product

from .builders import _amount_in_words_indian, _e, _fmt_currency, _fmt_rate
from .purchase_template import _extract_pan_from_gstin, _is_interstate_supply

CREDIT_NOTE_TYPE_LABELS = {
    "return": "Sales return",
    "discount": "Discount",
    "adjustment": "Adjustment",
}


def _fmt_date(value) -> str:
    return value.strftime("%d %b %Y") if value else "N/A"


def _join_parts(parts: list[str]) -> str:
    return " &middot; ".join(part for part in parts if part)


def _gst_parts(gst: str | None, phone: str | None) -> list[str]:
    parts = []
    if gst:
        parts.append(f"GSTIN: {_e(gst)}")
        pan = _extract_pan_from_gstin(gst)
        if pan:
            parts.append(f"PAN: {_e(pan)}")
    if phone:
        parts.append(f"Phone: {_e(phone)}")
    return parts


def _build_credit_note_html(
    credit_note: CreditNote,
    invoices: list[Invoice],
    products: list[Product],
    company: CompanyProfile | None,
    ledger: Ledger | None,
) -> str:
    """Generate HTML for an outward credit note.

    ``invoices`` are the note's referenced invoices, oldest first. The first one
    decides the seller and party snapshot and whether tax splits as IGST or
    CGST + SGST — the same rule ``create_credit_note`` used to compute the amounts.
    """
    first_invoice = invoices[0] if invoices else None
    invoice_by_id = {invoice.id: invoice for invoice in invoices}
    product_map = {product.id: product for product in products}

    currency = (
        (first_invoice.company_currency_code if first_invoice else None)
        or (company.currency_code if company else None)
        or "INR"
    )

    # The seller as the original invoice printed them, falling back to the
    # profile for anything the snapshot never captured.
    seller_name = (first_invoice.company_name if first_invoice else None) or (company.name if company else None)
    seller_address = (first_invoice.company_address if first_invoice else None) or (company.address if company else None)
    seller_gst = (first_invoice.company_gst if first_invoice else None) or (company.gst if company else None)
    seller_phone = (first_invoice.company_phone if first_invoice else None) or (company.phone_number if company else None)
    seller_email = (first_invoice.company_email if first_invoice else None) or (company.email if company else None)
    seller_website = (first_invoice.company_website if first_invoice else None) or (company.website if company else None)
    logo_data = (first_invoice.company_logo_data if first_invoice else None) or (company.logo_data if company else None)
    logo_mime_type = (first_invoice.company_logo_mime_type if first_invoice else None) or (company.logo_mime_type if company else None)

    party_name = (first_invoice.ledger_name if first_invoice else None) or (ledger.name if ledger else None)
    party_address = (first_invoice.ledger_address if first_invoice else None) or (ledger.address if ledger else None)
    party_gst = (first_invoice.ledger_gst if first_invoice else None) or (ledger.gst if ledger else None)
    party_phone = (first_invoice.ledger_phone if first_invoice else None) or (ledger.phone_number if ledger else None)

    # The note's own tax heads say which columns it needs: the GSTINs cannot, since
    # a sale's place of supply can differ from the state on the buyer's GSTIN.
    if float(credit_note.igst_amount or 0) > 0:
        interstate_supply = True
    elif float(credit_note.cgst_amount or 0) + float(credit_note.sgst_amount or 0) > 0:
        interstate_supply = False
    else:
        interstate_supply = _is_interstate_supply(seller_gst, ledger.gst if ledger else party_gst)
    is_discount = credit_note.credit_note_type == "discount"

    item_rows = ""
    for idx, item in enumerate(credit_note.items or [], start=1):
        invoice_item = item.invoice_item
        prod = product_map.get(item.product_id)
        product_name = _e(prod.name) if prod else f"Product #{item.product_id}"
        if is_discount:
            product_name = f"Discount on {product_name}"
        hsn = _e((invoice_item.hsn_sac if invoice_item else None) or (prod.hsn_sac if prod else None) or "N/A")
        source_invoice = invoice_by_id.get(item.invoice_id)
        source_number = _e(source_invoice.invoice_number or f"#{source_invoice.id}") if source_invoice else "N/A"

        tax_amount = Decimal(str(item.tax_amount or 0))
        if interstate_supply:
            tax_cells = f'<td class="right">{_fmt_currency(float(tax_amount), currency)}</td>'
        else:
            half = float(tax_amount) / 2
            tax_cells = (
                f'<td class="right">{_fmt_currency(half, currency)}</td>'
                f'<td class="right">{_fmt_currency(half, currency)}</td>'
            )

        item_rows += f"""
        <tr>
          <td>{idx}</td>
          <td>{product_name}</td>
          <td>{hsn}</td>
          <td>{source_number}</td>
          <td class="right">{item.quantity}</td>
          <td class="right">{_fmt_currency(float(item.unit_price or 0), currency)}</td>
          <td class="right">{_fmt_currency(float(item.taxable_amount or 0), currency)}</td>
          <td class="right">{_fmt_rate(float(item.gst_rate or 0))}%</td>
          {tax_cells}
          <td class="right">{_fmt_currency(float(item.line_total or 0), currency)}</td>
        </tr>"""

    tax_header_cells = (
        '<th class="right">IGST</th>'
        if interstate_supply
        else '<th class="right">CGST</th><th class="right">SGST</th>'
    )
    if interstate_supply:
        tax_breakup_rows = f"<p>IGST: {_fmt_currency(float(credit_note.igst_amount or 0), currency)}</p>"
    else:
        tax_breakup_rows = (
            f"<p>CGST: {_fmt_currency(float(credit_note.cgst_amount or 0), currency)}</p>"
            f"<p>SGST: {_fmt_currency(float(credit_note.sgst_amount or 0), currency)}</p>"
        )
    total_tax = float(
        (credit_note.cgst_amount or 0) + (credit_note.sgst_amount or 0) + (credit_note.igst_amount or 0)
    )

    company_header_html = ""
    if logo_data and logo_mime_type:
        company_header_html = f"""
    <div class="sheet__logo">
      <img src="data:{_e(logo_mime_type)};base64,{_e(logo_data)}" alt="Company logo" class="sheet__logo-img" />
    </div>"""

    original_invoices_html = ", ".join(
        f"{_e(invoice.invoice_number or f'#{invoice.id}')} ({_fmt_date(invoice.invoice_date)})"
        for invoice in invoices
    ) or "N/A"

    reason_html = ""
    if credit_note.reason:
        reason_html = f"""
  <section class="sheet__note">
    <p class="eyebrow">Reason</p>
    <p class="sheet__note-value">{_e(credit_note.reason)}</p>
  </section>"""

    cancelled = credit_note.status == "cancelled"
    cancelled_html = (
        f'<div class="sheet__cancelled">Cancelled on {_fmt_date(credit_note.cancelled_at)}</div>'
        if cancelled
        else ""
    )
    type_label = CREDIT_NOTE_TYPE_LABELS.get(credit_note.credit_note_type, "Credit note")

    return f"""<!DOCTYPE html>
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
  .sheet__title {{
    text-align: center;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding-bottom: 10px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 16px;
  }}
  .sheet__cancelled {{
    text-align: center;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #b91c1c;
    border: 2px solid #b91c1c;
    border-radius: 6px;
    padding: 6px;
    margin-bottom: 16px;
  }}
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
  .sheet__badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: #b45309;
    background: #fffbeb;
    margin-bottom: 6px;
  }}
  .sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .sheet__party {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 16px;
  }}
  .sheet__party h4 {{
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 2px;
  }}
  .sheet__party p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .sheet__note {{
    border: 1px dashed #d1d5db;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 14px;
    background: #f9fafb;
  }}
  .sheet__note-value {{
    font-size: 9px;
    color: #374151;
  }}
  .sheet__table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 16px;
    font-size: 8px;
  }}
  .sheet__table thead th {{
    background: #f3f4f6;
    color: #374151;
    font-weight: 600;
    font-size: 7px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 5px 4px;
    border-bottom: 2px solid #d1d5db;
    text-align: left;
  }}
  .sheet__table th.right, .sheet__table td.right {{
    text-align: right;
  }}
  .sheet__table tbody td {{
    padding: 5px 4px;
    border-bottom: 1px solid #e5e7eb;
    overflow-wrap: anywhere;
  }}
  .sheet__table tbody tr {{
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__totals {{
    margin-left: auto;
    width: 230px;
    text-align: right;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__totals p {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 1px;
  }}
  .sheet__total-value {{
    font-size: 20px !important;
    font-weight: 700;
    color: #1a56db !important;
    margin: 4px 0;
  }}
  .sheet__amount-words {{
    font-size: 8px;
    font-style: italic;
    color: #374151;
  }}
  .muted-text {{
    font-size: 8px;
    color: #9ca3af;
  }}
  .sheet__logo {{
    margin-bottom: 8px;
  }}
  .sheet__logo-img {{
    max-width: 180px;
    max-height: 80px;
    object-fit: contain;
  }}
</style>
</head>
<body>
<div class="sheet">
  <div class="sheet__title">Credit Note</div>
  {cancelled_html}
  <header class="sheet__header">
    <div>
      <p class="eyebrow">Issued by</p>
      {company_header_html}
      <h3>{_e(seller_name) or 'Company not set'}</h3>
      <p>{_e(seller_address) or 'Address not provided'}</p>
      <p>{_join_parts(_gst_parts(seller_gst, seller_phone))}</p>
      <p>{_join_parts([f"Email: {_e(seller_email)}" if seller_email else "", f"Web: {_e(seller_website)}" if seller_website else ""])}</p>
    </div>
    <div class="sheet__meta">
      <span class="sheet__badge">{_e(type_label)}</span>
      <h2>Credit Note {_e(credit_note.credit_note_number)}</h2>
      <p>Date: {_fmt_date(getattr(credit_note, "credit_note_date", None) or credit_note.created_at)}</p>
      <p>Against invoice: {original_invoices_html}</p>
    </div>
  </header>

  <div class="sheet__party">
    <p class="eyebrow">Issued to</p>
    <h4>{_e(party_name) or 'Unknown ledger'}</h4>
    <p>{_e(party_address) or 'Address not provided'}</p>
    <p>{_join_parts(_gst_parts(party_gst, party_phone))}</p>
  </div>

  {reason_html}

  <table class="sheet__table">
    <thead>
      <tr>
        <th>#</th>
        <th>Item</th>
        <th>HSN/SAC</th>
        <th>Invoice</th>
        <th class="right">Qty</th>
        <th class="right">Rate</th>
        <th class="right">Taxable</th>
        <th class="right">GST</th>
        {tax_header_cells}
        <th class="right">Amount</th>
      </tr>
    </thead>
    <tbody>
      {item_rows}
    </tbody>
  </table>

  <section class="sheet__totals">
    <p class="eyebrow">Tax breakup</p>
    <p>Taxable: {_fmt_currency(float(credit_note.taxable_amount or 0), currency)}</p>
    {tax_breakup_rows}
    <p>Total tax: {_fmt_currency(total_tax, currency)}</p>
    <p class="eyebrow" style="margin-top: 10px;">Total credit</p>
    <p class="sheet__total-value">{_fmt_currency(float(credit_note.total_amount or 0), currency)}</p>
    <p class="sheet__amount-words">{_amount_in_words_indian(float(credit_note.total_amount or 0), currency)}</p>
    <p class="muted-text">Authorized by {_e(seller_name) or 'Billing company'}</p>
  </section>
</div>
</body>
</html>"""
