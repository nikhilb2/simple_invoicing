"""Quotation and proforma invoice HTML template.

Its own template rather than branches in ``_build_invoice_html``, which is how
"Tax Invoice" would slip back onto a quotation. It shares the table and tax helpers
in ``builders``, and carries its own stylesheet, as the credit note template does.

The wording is a compliance position, not copy. A quotation or proforma is not a tax
invoice and cannot support input tax credit, and a buyer holding a document with GST
amounts on it could wrongly try to claim it. So it never prints "Tax Invoice",
"Bill to", a copy label, a due date, anything implying a debt, or a way to pay by UPI.
``tests/services/test_quotation_pdf_template.py`` enforces this. A CA should review
the note below before release.
"""

from datetime import date

from src.models.company_account import CompanyAccount
from src.models.product import Product
from src.models.quotation import DOCUMENT_PROFORMA, STATUS_CANCELLED, Quotation
from src.services.gst_tax_service import india_today

from .builders import (
    _amount_in_words_indian,
    _build_invoice_discount_html,
    _build_item_discount_html,
    _build_pdf_table_colgroup,
    _build_pdf_tax_breakup_rows,
    _build_pdf_tax_header_cells,
    _build_pdf_tax_row_cells,
    _e,
    _fmt_currency,
    _pdf_display_quantity,
    _pdf_display_unit,
    _pdf_unit_price,
)
from .purchase_template import _extract_pan_from_gstin, _is_interstate_supply

# Fixed, printed on every copy of both documents. The user cannot remove it.
NOT_A_TAX_INVOICE_NOTE = (
    "This is not a tax invoice and cannot be used to claim input tax credit. "
    "GST shown is an estimate. A tax invoice will be issued at the time of supply."
)


def _fmt_date(value) -> str:
    return value.strftime("%d %b %Y") if value else "N/A"


def _join(parts: list[str]) -> str:
    return " &middot; ".join(part for part in parts if part)


def _party_details(gst: str | None, phone: str | None) -> str:
    parts = []
    if gst:
        parts.append(f"GSTIN: {_e(gst)}")
        pan = _extract_pan_from_gstin(gst)
        if pan:
            parts.append(f"PAN: {_e(pan)}")
    if phone:
        parts.append(f"Phone: {_e(phone)}")
    return _join(parts)


def _bank_details_html(quotation: Quotation, accounts: list[CompanyAccount]) -> str:
    """Bank details, on a proforma only: it is the document that often asks for an advance."""
    if quotation.document_type != DOCUMENT_PROFORMA:
        return ""

    rows = [
        (
            account.bank_name,
            account.branch_name,
            account.account_name,
            account.account_number,
            account.ifsc_code,
        )
        for account in accounts
    ]
    if not rows and (quotation.company_bank_name or quotation.company_account_number):
        rows = [(
            quotation.company_bank_name,
            quotation.company_branch_name,
            quotation.company_account_name,
            quotation.company_account_number,
            quotation.company_ifsc_code,
        )]
    if not rows:
        return ""

    blocks = "".join(
        '<table class="sheet__bank-rows">'
        f"<tr><th>Bank</th><td>{_e(bank) or 'N/A'}</td></tr>"
        f"<tr><th>Branch</th><td>{_e(branch) or 'N/A'}</td></tr>"
        f"<tr><th>Account name</th><td>{_e(name) or 'N/A'}</td></tr>"
        f"<tr><th>A/C no.</th><td>{_e(number) or 'N/A'}</td></tr>"
        f"<tr><th>IFSC</th><td>{_e(ifsc) or 'N/A'}</td></tr>"
        "</table>"
        for bank, branch, name, number, ifsc in rows
    )
    return f'<p class="eyebrow">Bank details</p>{blocks}'


def _build_quotation_html(
    quotation: Quotation,
    products: list[Product],
    bank_accounts: list[CompanyAccount] | None = None,
    *,
    show_sku: bool = True,
    today: date | None = None,
) -> str:
    """Generate HTML for a quotation or a proforma invoice."""
    today = today or india_today()
    is_proforma = quotation.document_type == DOCUMENT_PROFORMA
    title = "Proforma Invoice" if is_proforma else "Quotation"
    party_eyebrow = "Proforma for" if is_proforma else "Quotation for"

    currency = quotation.company_currency_code or "USD"
    number = _e(quotation.quotation_number)
    interstate_supply = _is_interstate_supply(quotation.company_gst, quotation.ledger_gst)
    tax_inclusive = bool(quotation.tax_inclusive)
    product_map = {product.id: product for product in products}
    expired = quotation.is_expired_on(today)
    cancelled = quotation.status == STATUS_CANCELLED

    item_rows = ""
    for idx, item in enumerate(quotation.items or [], start=1):
        prod = product_map.get(item.product_id)
        product_name = _e(prod.name) if prod else f"Product #{item.product_id}"
        description = _e(item.description)
        product_cell = f'{product_name}<br><span class="muted-text">{description}</span>' if description else product_name
        discount_html = _build_item_discount_html(item, currency, tax_inclusive=tax_inclusive)
        hsn = _e(item.hsn_sac or (prod.hsn_sac if prod else None) or "N/A")
        unit = _e(_pdf_display_unit(getattr(prod, "unit", None) if prod else None))
        quantity = _pdf_display_quantity(item.quantity, getattr(prod, "allow_decimal", None) if prod else None)
        sku_cell = f"<td>{_e(prod.sku) if prod else 'N/A'}</td>" if show_sku else ""
        item_rows += f"""
        <tr>
          <td>{idx}</td>
          <td>{product_cell}{discount_html}</td>
          {sku_cell}
          <td class="nowrap">{hsn}</td>
          <td class="right">{quantity}</td>
          <td>{unit}</td>
          <td class="right">{_fmt_currency(_pdf_unit_price(item, tax_inclusive=tax_inclusive), currency)}</td>
          {_build_pdf_tax_row_cells(item, currency, interstate_supply)}
          <td class="right">{_fmt_currency(float(item.line_total), currency)}</td>
        </tr>"""

    logo_html = ""
    if quotation.company_logo_data and quotation.company_logo_mime_type:
        logo_html = (
            '<div class="sheet__logo">'
            f'<img src="data:{_e(quotation.company_logo_mime_type)};base64,{_e(quotation.company_logo_data)}" '
            'alt="Company logo" class="sheet__logo-img" />'
            "</div>"
        )
    info_html = ""
    if quotation.company_additional_info:
        lines = "<br>".join(_e(line) for line in quotation.company_additional_info.split("\n"))
        info_html = f'<div class="sheet__company-info">{lines}</div>'

    ship_to_html = ""
    if quotation.shipping_address:
        ship_label = f"<h4>{_e(quotation.shipping_address_label)}</h4>" if quotation.shipping_address_label else ""
        ship_to_html = f"""
    <div class="sheet__party">
      <p class="eyebrow">Ship to</p>
      {ship_label}
      <p>{_e(quotation.shipping_address)}</p>
    </div>"""

    reference_html = ""
    if quotation.reference_notes:
        reference_html = f"""
  <section class="sheet__note">
    <p class="eyebrow">Reference</p>
    <p>{_e(quotation.reference_notes)}</p>
  </section>"""

    terms_html = ""
    if quotation.company_terms_text:
        terms_items = "".join(
            f'<div class="sheet__terms-item">{_e(line)}</div>'
            for line in quotation.company_terms_text.split("\n")
            if line.strip()
        )
        if terms_items:
            terms_html = f"""
  <section class="sheet__terms">
    <p class="eyebrow">Terms &amp; Conditions</p>
    {terms_items}
  </section>"""

    mark_html = ""
    if cancelled:
        mark_html = f'<div class="sheet__mark">Cancelled on {_fmt_date(quotation.cancelled_at)}</div>'
    elif expired:
        mark_html = f'<div class="sheet__mark">Expired on {_fmt_date(quotation.valid_until)}</div>'

    valid_until_html = f"<p>Valid until: {_fmt_date(quotation.valid_until)}</p>" if quotation.valid_until else ""
    validity_sentence = ""
    if quotation.valid_until and not is_proforma:
        verb = "were" if expired else "are"
        validity_sentence = f" Prices {verb} valid until {_fmt_date(quotation.valid_until)}."

    round_off = float(quotation.round_off_amount or 0)
    round_off_html = (
        f"<p>Round off: {_fmt_currency(round_off, currency)}</p>"
        if quotation.apply_round_off and round_off != 0
        else ""
    )

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
    white-space: nowrap;
    padding-bottom: 10px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 8px;
  }}
  .sheet__disclaimer {{
    text-align: center;
    font-size: 11px;
    font-weight: 700;
    margin-bottom: 14px;
  }}
  .sheet__mark {{
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
  .sheet__meta h2 {{
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .sheet__parties {{
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
  }}
  .sheet__party {{
    flex: 1;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px 14px;
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
    font-size: 9px;
    color: #374151;
  }}
  .sheet__table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
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
  .sheet__table td.nowrap {{
    overflow-wrap: normal;
    white-space: nowrap;
  }}
  .sheet__table tbody tr {{
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__footer {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__bank-rows {{
    border-collapse: collapse;
    font-size: 9px;
    margin-bottom: 8px;
  }}
  .sheet__bank-rows th {{
    text-align: left;
    font-weight: 500;
    color: #6b7280;
    padding-right: 10px;
  }}
  .sheet__totals {{
    margin-left: auto;
    width: 230px;
    text-align: right;
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
  .sheet__company-info {{
    font-size: 9px;
    color: #4b5563;
    margin-bottom: 6px;
  }}
  .sheet__terms {{
    border-top: 1px solid #e5e7eb;
    margin-top: 16px;
    padding-top: 10px;
    font-size: 9px;
    color: #4b5563;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  .sheet__fixed-note {{
    border-top: 2px solid #e5e7eb;
    margin-top: 16px;
    padding-top: 10px;
    font-size: 9px;
    font-weight: 600;
    color: #111827;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
</style>
</head>
<body>
<div class="sheet">
  <div class="sheet__title">{title}</div>
  <div class="sheet__disclaimer">This is not a tax invoice</div>
  {mark_html}
  <header class="sheet__header">
    <div>
      <p class="eyebrow">From</p>
      {logo_html}
      {info_html}
      <h3>{_e(quotation.company_name) or 'Company not set'}</h3>
      <p>{_e(quotation.company_address) or 'Address not provided'}</p>
      <p>{_party_details(quotation.company_gst, quotation.company_phone)}</p>
      <p>{_join([f"Email: {_e(quotation.company_email)}" if quotation.company_email else "", f"Web: {_e(quotation.company_website)}" if quotation.company_website else ""])}</p>
    </div>
    <div class="sheet__meta">
      <h2>{number}</h2>
      <p>Date: {_fmt_date(quotation.quotation_date)}</p>
      {valid_until_html}
      <p>Currency: {_e(currency)}</p>
    </div>
  </header>

  <div class="sheet__parties">
    <div class="sheet__party">
      <p class="eyebrow">{party_eyebrow}</p>
      <h4>{_e(quotation.ledger_name) or 'Unknown ledger'}</h4>
      <p>{_e(quotation.ledger_address) or 'Address not provided'}</p>
      <p>{_party_details(quotation.ledger_gst, quotation.ledger_phone)}</p>
    </div>{ship_to_html}
  </div>

  {reference_html}

  <section>
    <table class="sheet__table">
      {_build_pdf_table_colgroup(interstate_supply, show_sku=show_sku)}
      <thead>
        <tr>
          <th>#</th>
          <th>Item</th>
          {"<th>SKU</th>" if show_sku else ""}
          <th>HSN/SAC</th>
          <th class="right">Qty</th>
          <th>Unit</th>
          <th class="right">Unit Price<br><span style="font-size: 6px; font-weight: 500; text-transform: none;">{"(with tax)" if tax_inclusive else "(without tax)"}</span></th>
          {_build_pdf_tax_header_cells(interstate_supply)}
          <th class="right">Amount</th>
        </tr>
      </thead>
      <tbody>
        {item_rows}
      </tbody>
    </table>
  </section>

  <section class="sheet__footer">
    <div>{_bank_details_html(quotation, bank_accounts or [])}</div>
    <div class="sheet__totals">
      <p class="eyebrow">Estimated tax</p>
      <p>Taxable: {_fmt_currency(float(quotation.taxable_amount or 0), currency)}</p>
      {_build_pdf_tax_breakup_rows(quotation, currency)}
      <p>Total estimated GST: {_fmt_currency(float(quotation.total_tax_amount or 0), currency)}</p>
      {_build_invoice_discount_html(quotation, currency)}
      {round_off_html}
      <p class="eyebrow" style="margin-top: 10px;">{title} total</p>
      <p class="sheet__total-value">{_fmt_currency(float(quotation.total_amount or 0), currency)}</p>
      <p class="sheet__amount-words">{_amount_in_words_indian(float(quotation.total_amount or 0), currency)}</p>
      <p class="muted-text">For {_e(quotation.company_name) or 'Company'}</p>
    </div>
  </section>

  {terms_html}

  <p class="sheet__fixed-note">{NOT_A_TAX_INVOICE_NOTE}{validity_sentence}</p>
</div>
</body>
</html>"""
