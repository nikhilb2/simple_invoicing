from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from typing import Literal
from decimal import Decimal

from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.production_transaction import ProductionTransaction
from src.models.user import User, UserRole
from src.schemas.inventory import InventoryAdjust, InventoryOut, PaginatedInventoryOut
from src.schemas.bom import ProduceRequest, ProductionTransactionOut, PaginatedProductionTransactionOut
from src.api.deps import get_active_company, get_current_user, require_roles
from src.services import bom_service

router = APIRouter()


def _is_whole_number(value: float) -> bool:
    return Decimal(str(value)) == Decimal(str(value)).to_integral_value()


@router.post("/adjust")
def adjust_inventory(
    payload: InventoryAdjust,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    product = db.query(Product).filter(
        Product.id == payload.product_id,
        Product.company_id == active_company.id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.maintain_inventory:
        raise HTTPException(status_code=400, detail="Inventory is disabled for this product")
    if not product.allow_decimal and not _is_whole_number(payload.quantity):
        raise HTTPException(status_code=400, detail="Quantity must be a whole number for this product")

    inventory = db.query(Inventory).filter(
        Inventory.product_id == payload.product_id,
        Inventory.company_id == active_company.id,
    ).first()
    if not inventory:
        inventory = Inventory(company_id=active_company.id, product_id=payload.product_id, quantity=0)
        db.add(inventory)

    inventory.quantity = Decimal(str(inventory.quantity or 0)) + Decimal(str(payload.quantity))
    if Decimal(str(inventory.quantity or 0)) < 0:
        raise HTTPException(status_code=400, detail="Inventory cannot be negative")

    db.commit()
    return {"message": "Inventory updated"}


@router.get("", response_model=PaginatedInventoryOut, include_in_schema=False)
@router.get("/", response_model=PaginatedInventoryOut)
def list_inventory(
    search: str = Query(""),
    sort_by: Literal["name", "quantity", "date_added", "last_sold"] = Query("name"),
    sort_order: Literal["asc", "desc"] = Query("asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    # Subquery: last invoice_date per product (non-cancelled invoices)
    last_sold_subq = (
        db.query(
            InvoiceItem.product_id,
            func.max(Invoice.invoice_date).label("last_sold_at"),
        )
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .filter(
            Invoice.status != "cancelled",
            Invoice.company_id == active_company.id,
        )
        .group_by(InvoiceItem.product_id)
        .subquery()
    )

    quantity_expr = func.coalesce(Inventory.quantity, 0)
    query = (
        db.query(Product, quantity_expr.label("quantity"), last_sold_subq.c.last_sold_at)
        .outerjoin(
            Inventory,
            and_(
                Inventory.product_id == Product.id,
                Inventory.company_id == active_company.id,
            ),
        )
        .outerjoin(last_sold_subq, last_sold_subq.c.product_id == Product.id)
        .filter(Product.company_id == active_company.id)
    )

    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            Product.name.ilike(term) | Product.sku.ilike(term)
        )

    if sort_by == "name":
        order_col = Product.name
    elif sort_by == "quantity":
        order_col = quantity_expr
    elif sort_by == "date_added":
        order_col = Product.created_at
    else:  # last_sold
        order_col = last_sold_subq.c.last_sold_at

    total = query.count()

    if sort_order == "desc":
        query = query.order_by(order_col.desc().nulls_last())
    else:
        query = query.order_by(order_col.asc().nulls_last())

    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [
        InventoryOut(
            product_id=product.id,
            product_name=product.name,
            sku=product.sku,
            unit=product.unit,
            allow_decimal=bool(product.allow_decimal),
            price=float(product.price),
            maintain_inventory=bool(product.maintain_inventory),
            quantity=float(quantity),
            date_added=product.created_at,
            last_sold_at=last_sold_at,
        )
        for product, quantity, last_sold_at in rows
    ]
    return PaginatedInventoryOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
    )


@router.post("/produce")
def produce_item(
    payload: ProduceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """
    Produce an item by consuming its BOM components and increasing inventory.
    """
    result = bom_service.execute_production(
        db,
        active_company.id,
        payload.product_id,
        Decimal(str(payload.quantity)),
        current_user.id,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/production-history", response_model=PaginatedProductionTransactionOut)
def get_production_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """
    Get production transaction history for the active company.
    """
    query = db.query(ProductionTransaction).filter(
        ProductionTransaction.company_id == active_company.id
    ).order_by(ProductionTransaction.created_at.desc())

    total = query.count()
    transactions = query.offset((page - 1) * page_size).limit(page_size).all()

    items = [
        ProductionTransactionOut(
            id=t.id,
            company_id=t.company_id,
            product_id=t.product_id,
            quantity_produced=float(t.quantity_produced),
            user_id=t.user_id,
            notes=t.notes,
            created_at=t.created_at,
        )
        for t in transactions
    ]

    return PaginatedProductionTransactionOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
    )
