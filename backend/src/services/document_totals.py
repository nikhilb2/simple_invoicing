"""The parts of a sales document that invoices and quotations must compute alike.

A quotation that converts to an invoice has to arrive at the same figures, so this
arithmetic exists once. ``InvoiceProcessor.apply_payload`` and
:mod:`src.services.quotation` both call it. Line totals are shared the same way,
through ``InvoiceProcessor.calculate_totals``.

:mod:`src.services.invoice_discounts` inverts the discount and round-off arithmetic
below for reporting, so any change here must be mirrored there.
"""

from decimal import Decimal, ROUND_HALF_UP

from src.models.company import CompanyProfile
from src.services.gst_tax_service import money as _money


def snapshot_company_fields(document, company: CompanyProfile | None) -> None:
    """Copy the seller's details onto a document, as they stand today."""
    document.company_name = company.name if company else None
    document.company_address = company.address if company else None
    document.company_gst = company.gst if company else None
    document.company_phone = company.phone_number if company else None
    document.company_email = company.email if company else None
    document.company_website = company.website if company else None
    document.company_currency_code = company.currency_code if company else None
    document.company_bank_name = company.bank_name if company else None
    document.company_branch_name = company.branch_name if company else None
    document.company_account_name = company.account_name if company else None
    document.company_account_number = company.account_number if company else None
    document.company_ifsc_code = company.ifsc_code if company else None
    # Company branding fields
    document.company_logo_data = company.logo_data if company else None
    document.company_logo_mime_type = company.logo_mime_type if company else None
    document.company_additional_info = company.additional_company_info if company else None
    # Snapshot terms & conditions as formatted text
    terms = (company.terms or []) if company else []
    document.company_terms_text = "\n".join(f"{t.serial_number}. {t.content}" for t in terms) if terms else None


def apply_discount_and_round_off(
    document,
    raw_total: Decimal,
    discount_type: str | None,
    discount_value: float | None,
) -> None:
    """Take a document-level discount off ``raw_total``, then round it if asked.

    ``raw_total`` is taxable plus tax. Reads ``document.apply_round_off`` and sets
    the discount fields, ``round_off_amount`` and ``total_amount``.
    """
    document.discount_type = discount_type
    document.discount_value = discount_value
    if discount_type and discount_value is not None and discount_value > 0:
        if discount_type == "percentage":
            discount_amount = _money(raw_total * Decimal(str(discount_value)) / Decimal("100"))
        else:
            discount_amount = _money(Decimal(str(discount_value)))
        discount_amount = min(discount_amount, raw_total)
        raw_total = _money(raw_total - discount_amount)

    if document.apply_round_off:
        rounded_total = raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        document.round_off_amount = float(_money(rounded_total - raw_total))
        document.total_amount = float(_money(rounded_total))
    else:
        document.round_off_amount = 0
        document.total_amount = float(raw_total)
