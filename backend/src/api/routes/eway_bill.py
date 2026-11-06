"""
E-Way Bill API routes.

Provides endpoints for:
- Pre-check available data before generating E-Way Bill
- E-Way Bill settings
- Transporter profile management (CRUD)
- Generate E-Way Bill JSON
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_active_company, get_current_user, require_company_role
from src.db.session import get_db
from src.models.buyer import Buyer
from src.models.company import CompanyProfile
from src.models.eway_bill import EwayBillTransporter
from src.models.invoice import Invoice
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.eway_bill import (
    EwayBillFormData,
    EwayBillPreCheckResult,
    TransporterProfileCreate,
    TransporterProfileOut,
    TransporterProfileUpdate,
)
from src.services.company_access import company_role
from src.services.eway_bill_service import (
    clear_default_transporter,
    generate_eway_bill_json,
    get_or_create_default_transporter,
    pre_check,
    save_default_transporter,
    validate_form_against_invoice,
    validate_form_data,
    validate_invoice,
)

logger = logging.getLogger(__name__)

_TRANSPORTER_MANAGER_ROLES = (UserRole.admin, UserRole.manager)


class EwayBillSettingsOut(BaseModel):
    eway_enabled: bool = True
    eway_local_threshold: float = 50000
    eway_interstate_threshold: float = 50000
    eway_always_show_button: bool = True


router = APIRouter()


def _get_products_map(db: Session, invoice: Invoice, company_id: int) -> dict[int, Product]:
    """Build a product_id -> Product map for items in the invoice."""
    product_ids = [item.product_id for item in (invoice.items or [])]
    if not product_ids:
        return {}
    products = (
        db.query(Product)
        .filter(Product.id.in_(product_ids), Product.company_id == company_id)
        .all()
    )
    return {p.id: p for p in products}


def _get_eligible_invoice(db: Session, invoice_id: int, company: CompanyProfile) -> Invoice:
    """Load an invoice both e-way bill routes may act on, or raise why not.

    The one place the rules live, so pre-check and generate can't disagree.
    """
    if not company.eway_enabled:
        raise HTTPException(
            status_code=400,
            detail="E-Way Bill generation is turned off for this company. Turn it on in Company Settings.",
        )

    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.items))
        .filter(Invoice.id == invoice_id, Invoice.company_id == company.id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    if invoice.voucher_type != "sales":
        raise HTTPException(status_code=400, detail="E-Way Bill is only available for Sales invoices.")
    if invoice.status != "active":
        raise HTTPException(status_code=400, detail="E-Way Bill can only be generated for active invoices.")
    return invoice


def _get_invoice_buyer(db: Session, invoice: Invoice, company: CompanyProfile) -> Buyer | None:
    if not invoice.ledger_id:
        return None
    return (
        db.query(Buyer)
        .filter(Buyer.id == invoice.ledger_id, Buyer.company_id == company.id)
        .first()
    )


# ── Settings endpoint ──


@router.get("/eway-bill/settings", response_model=EwayBillSettingsOut)
def eway_bill_settings(
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Get the current E-Way Bill configuration for the active company."""
    return EwayBillSettingsOut(
        eway_enabled=active_company.eway_enabled,
        eway_local_threshold=active_company.eway_local_threshold,
        eway_interstate_threshold=active_company.eway_interstate_threshold,
        eway_always_show_button=active_company.eway_always_show_button,
    )


# ── Pre-check endpoint ──


@router.get("/invoices/{invoice_id}/eway-bill/precheck", response_model=EwayBillPreCheckResult)
def eway_bill_precheck(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Check what E-Way Bill data is available and what's missing for this invoice."""
    invoice = _get_eligible_invoice(db, invoice_id, active_company)
    buyer = _get_invoice_buyer(db, invoice, active_company)
    products_map = _get_products_map(db, invoice, active_company.id)

    result = pre_check(invoice, active_company, buyer, invoice.items or [], products_map)

    # Auto-fill default transporter if available
    default_transporter = get_or_create_default_transporter(db, active_company.id)
    if default_transporter:
        result.form_data.transporter_name = default_transporter.transporter_name or ""
        result.form_data.transporter_gstin = default_transporter.transporter_gstin or ""
        result.form_data.transport_mode = default_transporter.transport_mode or "1"
        result.form_data.vehicle_type = default_transporter.vehicle_type or "R"

    return result


# ── Generate E-Way Bill JSON ──


@router.post("/invoices/{invoice_id}/eway-bill/generate")
def eway_bill_generate(
    invoice_id: int,
    form_data: EwayBillFormData,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Generate the E-Way Bill JSON from invoice data and user-supplied form data."""
    invoice = _get_eligible_invoice(db, invoice_id, active_company)
    products_map = _get_products_map(db, invoice, active_company.id)

    errors = (
        validate_invoice(invoice, invoice.items or [], products_map)
        + validate_form_data(form_data)
        + validate_form_against_invoice(form_data, invoice)
    )
    if errors:
        raise HTTPException(status_code=422, detail={
            "message": "Some E-Way Bill details need fixing.",
            "errors": [e.model_dump() for e in errors],
        })

    # Viewing an invoice is enough to generate a bill, but saving the transporter
    # is a write to the same master data the transporter routes guard.
    save_transporter = form_data.save_transporter and bool(form_data.transporter_name.strip())
    if save_transporter and company_role(db, current_user, active_company.id) not in _TRANSPORTER_MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Only an admin or manager can save a transporter.")

    try:
        json_data = generate_eway_bill_json(invoice, invoice.items or [], products_map, form_data)
        if save_transporter:
            save_default_transporter(db, active_company.id, form_data)
            db.commit()
    except Exception:
        logger.exception("Error generating E-Way Bill JSON")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to generate E-Way Bill JSON")

    filename = f"EWB_{invoice.invoice_number or invoice.id}.json"
    json_str = json.dumps(json_data, indent=2, ensure_ascii=False)

    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Transporter profile management ──


@router.get("/eway-bill/transporters", response_model=list[TransporterProfileOut])
def list_transporters(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """List all saved transporter profiles."""
    return (
        db.query(EwayBillTransporter)
        .filter(EwayBillTransporter.company_id == active_company.id)
        .order_by(EwayBillTransporter.is_default.desc(), EwayBillTransporter.transporter_name.asc())
        .all()
    )


@router.post("/eway-bill/transporters", response_model=TransporterProfileOut)
def create_transporter(
    payload: TransporterProfileCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_company_role(*_TRANSPORTER_MANAGER_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Create a new transporter profile."""
    if payload.is_default:
        clear_default_transporter(db, active_company.id)

    transporter = EwayBillTransporter(
        company_id=active_company.id,
        transporter_name=payload.transporter_name,
        transporter_gstin=payload.transporter_gstin or "",
        transport_mode=payload.transport_mode or "1",
        vehicle_type=payload.vehicle_type or "R",
        is_default=payload.is_default,
    )
    db.add(transporter)
    db.commit()
    db.refresh(transporter)
    return transporter


@router.put("/eway-bill/transporters/{transporter_id}", response_model=TransporterProfileOut)
def update_transporter(
    transporter_id: int,
    payload: TransporterProfileUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_company_role(*_TRANSPORTER_MANAGER_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Update a transporter profile."""
    transporter = (
        db.query(EwayBillTransporter)
        .filter(EwayBillTransporter.id == transporter_id, EwayBillTransporter.company_id == active_company.id)
        .first()
    )
    if not transporter:
        raise HTTPException(status_code=404, detail="Transporter not found")

    if payload.transporter_name is not None:
        transporter.transporter_name = payload.transporter_name
    if payload.transporter_gstin is not None:
        transporter.transporter_gstin = payload.transporter_gstin
    if payload.transport_mode is not None:
        transporter.transport_mode = payload.transport_mode
    if payload.vehicle_type is not None:
        transporter.vehicle_type = payload.vehicle_type
    if payload.is_default is not None:
        if payload.is_default:
            clear_default_transporter(db, active_company.id, keep_id=transporter_id)
        transporter.is_default = payload.is_default

    db.commit()
    db.refresh(transporter)
    return transporter


@router.delete("/eway-bill/transporters/{transporter_id}")
def delete_transporter(
    transporter_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_company_role(*_TRANSPORTER_MANAGER_ROLES)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Delete a transporter profile."""
    transporter = (
        db.query(EwayBillTransporter)
        .filter(EwayBillTransporter.id == transporter_id, EwayBillTransporter.company_id == active_company.id)
        .first()
    )
    if not transporter:
        raise HTTPException(status_code=404, detail="Transporter not found")

    db.delete(transporter)
    db.commit()
    return {"detail": "Transporter deleted"}
