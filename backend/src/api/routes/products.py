from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.models.inventory import Inventory
from src.models.invoice import InvoiceItem
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.product import PaginatedProductOut, ProductCreate, ProductOut
from src.api.deps import get_current_user, require_roles

router = APIRouter()


@router.post("", response_model=ProductOut, include_in_schema=False)
@router.post("/", response_model=ProductOut)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    if payload.gst_rate < 0 or payload.gst_rate > 100:
        raise HTTPException(status_code=400, detail="GST rate must be between 0 and 100")

    sku = payload.sku.strip().upper()
    existing = db.query(Product).filter(Product.sku == sku).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product with this SKU already exists")

    product = Product(
        sku=sku,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        hsn_sac=payload.hsn_sac,
        price=payload.price,
        gst_rate=payload.gst_rate,
    )
    db.add(product)
    db.flush()  # get product.id before committing

    if payload.initial_quantity != 0:
        inventory = Inventory(product_id=product.id, quantity=payload.initial_quantity)
        db.add(inventory)
    else:
        inventory = Inventory(product_id=product.id, quantity=0)
        db.add(inventory)

    db.commit()
    db.refresh(product)
    return product


@router.get("", response_model=PaginatedProductOut, include_in_schema=False)
@router.get("/", response_model=PaginatedProductOut)
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Product)
    if search.strip():
        query = query.filter(Product.name.ilike(f"%{search.strip()}%"))
    total = query.count()
    items = (
        query.order_by(Product.name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedProductOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
    )


@router.put("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    if payload.gst_rate < 0 or payload.gst_rate > 100:
        raise HTTPException(status_code=400, detail="GST rate must be between 0 and 100")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    sku = payload.sku.strip().upper()
    sku_owner = db.query(Product).filter(Product.sku == sku, Product.id != product_id).first()
    if sku_owner:
        raise HTTPException(status_code=400, detail="Product with this SKU already exists")

    product.sku = sku
    product.name = payload.name.strip()
    product.description = payload.description.strip() if payload.description else None
    product.hsn_sac = payload.hsn_sac
    product.price = payload.price
    product.gst_rate = payload.gst_rate

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    has_invoice_items = db.query(InvoiceItem.id).filter(InvoiceItem.product_id == product_id).first()
    if has_invoice_items:
        raise HTTPException(status_code=400, detail="Cannot delete product linked to invoices")

    inventory = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if inventory:
        db.delete(inventory)

    db.delete(product)
    db.commit()
    return {"message": "Product deleted"}
