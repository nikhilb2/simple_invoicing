"""
BOM (Bill of Materials) API endpoints.
"""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_current_user, require_roles
from src.models.user import UserRole, User
from src.models.product import Product
from src.models.bom import BillOfMaterial
from src.models.production_transaction import ProductionTransaction
from src.schemas.bom import (
    BOMCreate,
    BOMUpdate,
    BOMComponentOut,
    ProduceRequest,
    ProductionTransactionOut,
    PaginatedProductionTransactionOut,
)
from src.services import bom_service

router = APIRouter()


@router.get("/product/{product_id}", response_model=list[BOMComponentOut])
def get_product_bom(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get BOM for a producable product.
    Returns list of components with quantities required.
    """
    # Verify product exists and belongs to user's company
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.company_id == current_user.company_id,
    ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.is_producable:
        raise HTTPException(
            status_code=400, detail="Product is not marked as producable"
        )

    components = bom_service.get_bom_components(
        db, current_user.company_id, product_id
    )
    return components


@router.post("/", status_code=201, response_model=dict)
@require_roles(UserRole.admin, UserRole.manager)
def create_bom_entry(
    bom_create: BOMCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a component to a product's BOM.
    """
    # Verify product exists and is producable
    product = db.query(Product).filter(
        Product.id == bom_create.product_id,
        Product.company_id == current_user.company_id,
    ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not product.is_producable:
        raise HTTPException(
            status_code=400, detail="Product must be marked as producable"
        )

    # Verify component product exists
    component = db.query(Product).filter(
        Product.id == bom_create.component_product_id,
        Product.company_id == current_user.company_id,
    ).first()

    if not component:
        raise HTTPException(status_code=404, detail="Component product not found")

    # Check for circular BOM
    try:
        bom_service.validate_no_circular_bom(
            db,
            current_user.company_id,
            bom_create.product_id,
            bom_create.component_product_id,
        )
    except bom_service.CircularBOMError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check if entry already exists
    existing = db.query(BillOfMaterial).filter(
        BillOfMaterial.company_id == current_user.company_id,
        BillOfMaterial.product_id == bom_create.product_id,
        BillOfMaterial.component_product_id == bom_create.component_product_id,
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="BOM entry already exists")

    # Create BOM entry
    bom_entry = BillOfMaterial(
        company_id=current_user.company_id,
        product_id=bom_create.product_id,
        component_product_id=bom_create.component_product_id,
        quantity_required=Decimal(str(bom_create.quantity_required)),
    )

    db.add(bom_entry)
    db.commit()
    db.refresh(bom_entry)

    return {
        "id": bom_entry.id,
        "message": f"Added component to BOM",
    }


@router.put("/{bom_id}", response_model=dict)
@require_roles(UserRole.admin, UserRole.manager)
def update_bom_entry(
    bom_id: int,
    bom_update: BOMUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update quantity required for a BOM component.
    """
    bom_entry = db.query(BillOfMaterial).filter(
        BillOfMaterial.id == bom_id,
        BillOfMaterial.company_id == current_user.company_id,
    ).first()

    if not bom_entry:
        raise HTTPException(status_code=404, detail="BOM entry not found")

    bom_entry.quantity_required = Decimal(str(bom_update.quantity_required))
    db.commit()
    db.refresh(bom_entry)

    return {"id": bom_entry.id, "message": "BOM entry updated"}


@router.delete("/{bom_id}", response_model=dict)
@require_roles(UserRole.admin, UserRole.manager)
def delete_bom_entry(
    bom_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Remove a component from a product's BOM.
    """
    bom_entry = db.query(BillOfMaterial).filter(
        BillOfMaterial.id == bom_id,
        BillOfMaterial.company_id == current_user.company_id,
    ).first()

    if not bom_entry:
        raise HTTPException(status_code=404, detail="BOM entry not found")

    product_id = bom_entry.product_id
    db.delete(bom_entry)
    db.commit()

    return {
        "message": f"BOM entry deleted",
        "product_id": product_id,
    }
