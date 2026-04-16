from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Literal

from src.db.session import get_db
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.inventory import InventoryAdjust, InventoryOut
from src.api.deps import get_current_user, require_roles

router = APIRouter()


@router.post("/adjust")
def adjust_inventory(
    payload: InventoryAdjust,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    inventory = db.query(Inventory).filter(Inventory.product_id == payload.product_id).first()
    if not inventory:
        inventory = Inventory(product_id=payload.product_id, quantity=0)
        db.add(inventory)

    inventory.quantity += payload.quantity
    if inventory.quantity < 0:
        raise HTTPException(status_code=400, detail="Inventory cannot be negative")

    db.commit()
    return {"message": "Inventory updated"}


@router.get("", response_model=list[InventoryOut], include_in_schema=False)
@router.get("/", response_model=list[InventoryOut])
def list_inventory(
    search: str = Query(""),
    sort_by: Literal["name", "quantity", "date_added", "last_sold"] = Query("name"),
    sort_order: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Subquery: last invoice_date per product (non-cancelled invoices)
    last_sold_subq = (
        db.query(
            InvoiceItem.product_id,
            func.max(Invoice.invoice_date).label("last_sold_at"),
        )
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .filter(Invoice.status != "cancelled")
        .group_by(InvoiceItem.product_id)
        .subquery()
    )

    query = (
        db.query(Inventory, Product, last_sold_subq.c.last_sold_at)
        .join(Product, Inventory.product_id == Product.id)
        .outerjoin(last_sold_subq, last_sold_subq.c.product_id == Inventory.product_id)
    )

    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            Product.name.ilike(term) | Product.sku.ilike(term)
        )

    if sort_by == "name":
        order_col = Product.name
    elif sort_by == "quantity":
        order_col = Inventory.quantity
    elif sort_by == "date_added":
        order_col = Product.created_at
    else:  # last_sold
        order_col = last_sold_subq.c.last_sold_at

    if sort_order == "desc":
        query = query.order_by(order_col.desc().nulls_last())
    else:
        query = query.order_by(order_col.asc().nulls_last())

    rows = query.all()
    return [
        InventoryOut(
            product_id=inv.product_id,
            product_name=prod.name,
            sku=prod.sku,
            price=float(prod.price),
            quantity=inv.quantity,
            date_added=prod.created_at,
            last_sold_at=last_sold_at,
        )
        for inv, prod, last_sold_at in rows
    ]
