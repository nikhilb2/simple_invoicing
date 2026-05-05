"""Helper functions for PDF template building."""

from html import escape
from decimal import Decimal, ROUND_HALF_UP

from src.models.company_account import CompanyAccount
from src.models.invoice import Invoice, InvoiceItem


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _e(text: str | None) -> str:
    """Escape HTML special characters."""
    return escape(text or "")


def _fmt_currency(value: float, currency_code: str | None = None) -> str:
    """Format a currency value with the appropriate symbol."""
    code = currency_code or "USD"
    try:
        if code == "INR":
            return f"₹{value:,.2f}"
        elif code == "EUR":
            return f"€{value:,.2f}"
        elif code == "GBP":
            return f"£{value:,.2f}"
        else:
            return f"${value:,.2f}"
    except Exception:
        return f"{value:,.2f}"


def _fmt_rate(value: float) -> str:
    """Format a percentage rate without trailing zeros."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _amount_in_words_indian(amount: float, currency_code: str | None = None) -> str:
    """Convert a monetary amount to words using the Indian numbering system (crores/lakhs)."""
    _ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven',
             'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen',
             'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
    _TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _two(n: int) -> str:
        if n < 20:
            return _ONES[n]
        return _TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '')

    def _three(n: int) -> str:
        if n == 0:
            return ''
        if n < 100:
            return _two(n)
        return _ONES[n // 100] + ' Hundred' + (' ' + _two(n % 100) if n % 100 else '')

    try:
        amount = round(amount, 2)
        rupees = int(amount)
        paise = round((amount - rupees) * 100)
        currency_label = 'Rupees' if not currency_code or currency_code == 'INR' else currency_code

        if rupees == 0 and paise == 0:
            return f'Zero {currency_label} Only'

        parts: list[str] = []
        n = rupees
        crores = n // 10_000_000
        n %= 10_000_000
        lakhs = n // 100_000
        n %= 100_000
        thousands = n // 1000
        remainder = n % 1000

        if crores:
            parts.append(_three(crores) + ' Crore')
        if lakhs:
            parts.append(_two(lakhs) + ' Lakh')
        if thousands:
            parts.append(_two(thousands) + ' Thousand')
        if remainder:
            parts.append(_three(remainder))

        rupee_words = ' '.join(parts) if parts else 'Zero'
        result = f'{rupee_words} {currency_label}'
        if paise:
            result += f' and {_two(paise)} Paise'
        return result + ' Only'
    except Exception:
        return ''


def _pdf_unit_price_including_tax(item: InvoiceItem) -> float:
    """Calculate unit price including tax from a line item."""
    quantity = Decimal(str(item.quantity or 0))
    if quantity <= 0:
        return float(item.unit_price or 0)

    line_total = Decimal(str(item.line_total or 0))
    return float(_money(line_total / quantity))


def _pdf_display_unit(unit: str | None) -> str:
    """Format unit display for PDF, abbreviating common units."""
    normalized_unit = (unit or "Pieces").strip()
    if not normalized_unit:
        normalized_unit = "Pieces"
    if normalized_unit.lower() == "pieces":
        return "Pcs"
    return normalized_unit


def _pdf_display_quantity(quantity: float | Decimal | int | None, allow_decimal: bool | None) -> str:
    """Format quantity display, handling decimal vs integer display."""
    value = Decimal(str(quantity or 0))
    if not allow_decimal and value == value.to_integral_value():
        return str(int(value))

    as_text = format(value, "f").rstrip("0").rstrip(".")
    return as_text or "0"


def _build_pdf_tax_header_cells(interstate_supply: bool) -> str:
    """Build tax header cells for invoice table based on interstate/intrastate supply."""
    if interstate_supply:
        return '<th class="right">IGST %</th><th class="right">IGST Amt</th><th class="right">Total Tax</th>'
    return (
        '<th class="right">SGST %</th>'
        '<th class="right">SGST Amt</th>'
        '<th class="right">CGST %</th>'
        '<th class="right">CGST Amt</th>'
        '<th class="right">Total Tax</th>'
    )


def _build_pdf_table_colgroup(interstate_supply: bool) -> str:
    """Build table column group for invoice PDF based on tax type."""
    if interstate_supply:
        return (
            '<colgroup>'
            '<col style="width: 4%;" />'
            '<col style="width: 20%;" />'
            '<col style="width: 7%;" />'
            '<col style="width: 8%;" />'
            '<col style="width: 6%;" />'
            '<col style="width: 6%;" />'
            '<col style="width: 12%;" />'
            '<col style="width: 7%;" />'
            '<col style="width: 10%;" />'
            '<col style="width: 10%;" />'
            '<col style="width: 10%;" />'
            '</colgroup>'
        )
    return (
        '<colgroup>'
        '<col style="width: 3%;" />'
        '<col style="width: 16%;" />'
        '<col style="width: 6%;" />'
        '<col style="width: 7%;" />'
        '<col style="width: 5%;" />'
        '<col style="width: 5%;" />'
        '<col style="width: 10%;" />'
        '<col style="width: 6%;" />'
        '<col style="width: 8%;" />'
        '<col style="width: 6%;" />'
        '<col style="width: 8%;" />'
        '<col style="width: 8%;" />'
        '<col style="width: 12%;" />'
        '</colgroup>'
    )


def _build_pdf_tax_row_cells(item: InvoiceItem, currency: str, interstate_supply: bool) -> str:
    """Build tax cells for a single invoice line item."""
    gst_rate = float(item.gst_rate or 0)
    tax_amount = float(item.tax_amount or 0)

    if interstate_supply:
        igst_amount = float(item.igst_amount or 0)
        if tax_amount > 0 and igst_amount == 0:
            igst_amount = tax_amount
        igst_rate = gst_rate if igst_amount > 0 else 0
        return (
            f'<td class="right">{_fmt_rate(igst_rate)}%</td>'
            f'<td class="right">{_fmt_currency(igst_amount, currency)}</td>'
            f'<td class="right">{_fmt_currency(tax_amount, currency)}</td>'
        )

    sgst_amount = float(item.sgst_amount or 0)
    cgst_amount = float(item.cgst_amount or 0)
    if tax_amount > 0 and sgst_amount == 0 and cgst_amount == 0:
        cgst_amount = float(_money(Decimal(str(tax_amount)) / Decimal("2")))
        sgst_amount = float(_money(Decimal(str(tax_amount)) - Decimal(str(cgst_amount))))

    split_rate = gst_rate / 2 if (tax_amount > 0 or sgst_amount > 0 or cgst_amount > 0) else 0
    return (
        f'<td class="right">{_fmt_rate(split_rate)}%</td>'
        f'<td class="right">{_fmt_currency(sgst_amount, currency)}</td>'
        f'<td class="right">{_fmt_rate(split_rate)}%</td>'
        f'<td class="right">{_fmt_currency(cgst_amount, currency)}</td>'
        f'<td class="right">{_fmt_currency(tax_amount, currency)}</td>'
    )


def _build_pdf_tax_breakup_rows(invoice: Invoice, currency: str) -> str:
    """Build tax breakup summary rows for invoice footer."""
    cgst = float(invoice.cgst_amount or 0)
    sgst = float(invoice.sgst_amount or 0)
    igst = float(invoice.igst_amount or 0)

    # GST display rule for PDFs: show either IGST or CGST+SGST.
    if igst > 0:
        return f"<p>IGST: {_fmt_currency(igst, currency)}</p>"
    return (
        f"<p>CGST: {_fmt_currency(cgst, currency)}</p>"
        f"<p>SGST: {_fmt_currency(sgst, currency)}</p>"
    )


def _build_pdf_payment_details_html(invoice_bank_accounts: list[CompanyAccount]) -> str:
    """Build bank payment details section for invoice PDF."""
    if not invoice_bank_accounts:
        return '<p class="muted-text">No bank account marked to display on invoice.</p>'

    blocks: list[str] = []
    for account in invoice_bank_accounts:
        blocks.append(
            (
                '<div class="invoice-sheet__bank-card">'
                f"<p>Bank: {_e(account.bank_name) or 'N/A'}</p>"
                f"<p>Branch: {_e(account.branch_name) or 'N/A'}</p>"
                f"<p>Account Name: {_e(account.account_name) or 'N/A'}</p>"
                f"<p>A/C No: {_e(account.account_number) or 'N/A'}</p>"
                f"<p>IFSC: {_e(account.ifsc_code) or 'N/A'}</p>"
                "</div>"
            )
        )

    return f'<div class="invoice-sheet__bank-cards">{"".join(blocks)}</div>'
