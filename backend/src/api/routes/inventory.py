from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.models.inventory import Inventory
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

    db.commit()
    if inventory.quantity < 0:
        return {"message": "Inventory updated with negative balance warning"}
    return {"message": "Inventory updated"}


@router.get("", response_model=list[InventoryOut], include_in_schema=False)
@router.get("/", response_model=list[InventoryOut])
def list_inventory(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = db.query(Inventory, Product).join(Product, Inventory.product_id == Product.id).all()
    return [
        {"product_id": inv.product_id, "product_name": prod.name, "quantity": inv.quantity}
        for inv, prod in rows
    ]
