"""Creating an invoice row, shared by the invoice route and quotation conversion.

Flushes but never commits. Conversion has to land the invoice, its number, its stock
movement and the quotation's new status in one transaction, so a failure anywhere
rolls back all of it.
"""

from sqlalchemy.orm import Session

from src.models.company import CompanyProfile
from src.models.financial_year import FinancialYear
from src.models.invoice import Invoice
from src.schemas.invoice import InvoiceCreate
from src.services.financial_year import get_fy_for_date
from src.services.invoice_processor import InvoiceProcessor


def create_invoice_record(
    db: Session,
    payload: InvoiceCreate,
    *,
    created_by: int,
    company: CompanyProfile,
    active_fy: FinancialYear | None,
) -> tuple[Invoice, list[str]]:
    """Add the invoice to the session and return it with its warnings."""
    # Determine which FY this invoice belongs to based on its date.
    # If the invoice date falls within a different FY, use that FY.
    fy_for_invoice = active_fy
    if payload.invoice_date:
        date_fy = get_fy_for_date(db, payload.invoice_date, company_id=company.id)
        if date_fy is not None:
            fy_for_invoice = date_fy
    fy_id = fy_for_invoice.id if fy_for_invoice else None

    invoice = Invoice(
        total_amount=0,
        created_by=created_by,
        company_id=company.id,
    )
    db.add(invoice)
    db.flush()
    InvoiceProcessor(db).apply_payload(
        invoice,
        payload,
        company,
        created_by=created_by,
        financial_year_id=fy_id,
        active_financial_year_id=active_fy.id if active_fy else None,
    )

    warnings: list[str] = []
    if active_fy and payload.invoice_date:
        if not (active_fy.start_date <= payload.invoice_date <= active_fy.end_date):
            warnings.append("invoice_date_outside_fy")
    return invoice, warnings
