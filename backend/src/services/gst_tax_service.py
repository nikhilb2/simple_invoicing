"""
GST and tax calculation service module.

Handles extraction of GST state codes, tax splitting logic for CGST/SGST/IGST,
and invoice-level tax aggregation.
"""

from decimal import Decimal, ROUND_HALF_UP

from src.models.invoice import Invoice, InvoiceItem


def _to_paise(value: Decimal) -> int:
    """Convert a Decimal rupee amount to integer paise (2dp, HALF_UP)."""
    quantized = money(value)
    return int((quantized * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


def _from_paise(paise: int) -> Decimal:
    """Convert integer paise to rupee Decimal with 2dp precision."""
    return money(Decimal(paise) / Decimal("100"))


def money(value: Decimal) -> Decimal:
    """Round a Decimal value to 2 decimal places using ROUND_HALF_UP."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def is_interstate_supply(company_gst: str | None, ledger_gst: str | None) -> bool:
    """
    Check if the invoice is for an interstate supply based on GST state codes.
    
    Compares the first 2 characters of the GST IN numbers (state codes) to determine
    if the supply is between different states (interstate) or within the same state (intrastate).
    
    Args:
        company_gst: The GST IN of the company (seller). None or insufficient length returns False.
        ledger_gst: The GST IN of the buyer/ledger (buyer). None or insufficient length returns False.
        
    Returns:
        True if the supply is interstate (different state codes), False otherwise.
    """
    if not company_gst or not ledger_gst or len(company_gst) < 2 or len(ledger_gst) < 2:
        return False
    return company_gst[:2] != ledger_gst[:2]


def assign_item_tax_split(
    items: list[InvoiceItem],
    *,
    interstate_supply: bool,
) -> None:
    """
    Assign tax split (CGST, SGST, IGST) to invoice items based on supply type.
    
    For interstate supplies, 100% of tax goes to IGST with CGST and SGST set to 0.
    For intrastate supplies, tax is split equally between CGST and SGST with IGST set to 0.
    
    Modifies the items in-place, updating:
    - cgst_amount, sgst_amount, igst_amount
    - tax_amount, line_total
    
    Args:
        items: List of InvoiceItem objects to assign tax splits to.
        interstate_supply: True if this is an interstate supply, False for intrastate.
    """
    if not items:
        return

    if interstate_supply:
        for item in items:
            item_tax_amount = money(Decimal(str(item.tax_amount or 0)))
            item_igst_amount = item_tax_amount
            taxable_amount = money(Decimal(str(item.taxable_amount or 0)))

            item.tax_amount = float(item_igst_amount)
            item.line_total = float(money(taxable_amount + item_igst_amount))
            item.cgst_amount = 0.0
            item.sgst_amount = 0.0
            item.igst_amount = float(item_igst_amount)
        return

    running_cgst_paise = 0
    running_sgst_paise = 0
    for item in items:
        item_tax_amount = money(Decimal(str(item.tax_amount or 0)))
        item_tax_paise = _to_paise(item_tax_amount)
        half_tax_paise = item_tax_paise // 2

        item_cgst_paise = half_tax_paise
        item_sgst_paise = half_tax_paise

        # For odd-paise tax amounts, assign the 1-paise remainder to the side
        # with the lower running total so invoice-level split stays near-equal
        # without inflating item tax.
        if item_tax_paise % 2 == 1:
            if running_cgst_paise <= running_sgst_paise:
                item_cgst_paise += 1
            else:
                item_sgst_paise += 1

        item_cgst_amount = _from_paise(item_cgst_paise)
        item_sgst_amount = _from_paise(item_sgst_paise)
        item_total_tax_amount = money(item_cgst_amount + item_sgst_amount)
        taxable_amount = money(Decimal(str(item.taxable_amount or 0)))

        running_cgst_paise += item_cgst_paise
        running_sgst_paise += item_sgst_paise

        item.tax_amount = float(item_total_tax_amount)
        item.line_total = float(money(taxable_amount + item_total_tax_amount))
        item.cgst_amount = float(item_cgst_amount)
        item.sgst_amount = float(item_sgst_amount)
        item.igst_amount = 0.0


def calculate_tax_totals(items: list[InvoiceItem]) -> tuple[Decimal, Decimal, Decimal]:
    """
    Calculate total CGST, SGST, and IGST from invoice items.

    Returns:
        A tuple of (cgst_total, sgst_total, igst_total) as Decimals rounded to 2 places.
    """
    cgst_total = money(sum((money(Decimal(str(item.cgst_amount or 0))) for item in items), Decimal("0")))
    sgst_total = money(sum((money(Decimal(str(item.sgst_amount or 0))) for item in items), Decimal("0")))
    igst_total = money(sum((money(Decimal(str(item.igst_amount or 0))) for item in items), Decimal("0")))
    return cgst_total, sgst_total, igst_total


def assign_invoice_tax_totals(
    invoice: Invoice,
    items: list[InvoiceItem],
    *,
    interstate_supply: bool,
) -> Decimal:
    """
    Assign tax totals to the invoice based on aggregated item taxes and supply type.

    For interstate supplies, sets cgst_amount and sgst_amount to 0, igst_amount to total.
    For intrastate supplies, aggregates cgst and sgst totals, sets igst_amount to 0.

    Modifies the invoice in-place (cgst_amount, sgst_amount, igst_amount, total_tax_amount)
    and returns the total tax as a Decimal for use in downstream calculations.
    """
    cgst_total, sgst_total, igst_total = calculate_tax_totals(items)

    if interstate_supply:
        invoice.cgst_amount = 0.0
        invoice.sgst_amount = 0.0
        invoice.igst_amount = float(igst_total)
    else:
        invoice.cgst_amount = float(cgst_total)
        invoice.sgst_amount = float(sgst_total)
        invoice.igst_amount = 0.0

    tax_total = money(cgst_total + sgst_total + igst_total)
    invoice.total_tax_amount = float(tax_total)
    return tax_total
