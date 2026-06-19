import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File as FastAPIFile, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from decimal import Decimal

from src.db.session import get_db
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.models.user import User, UserRole
from src.schemas.product import (
    ImportCSVResult,
    PaginatedProductOut,
    ProductCreate,
    ProductOut,
    ProductWithInventoryOut,
    ProductWithInventoryUpdate,
)
from src.api.deps import get_active_company, get_current_user, require_roles

router = APIRouter()


def _is_whole_number(value: float) -> bool:
    return Decimal(str(value)) == Decimal(str(value)).to_integral_value()


@router.post("", response_model=ProductOut, include_in_schema=False)
@router.post("/", response_model=ProductOut)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    if payload.gst_rate < 0 or payload.gst_rate > 100:
        raise HTTPException(status_code=400, detail="GST rate must be between 0 and 100")

    sku = payload.sku.strip().upper()
    existing = db.query(Product).filter(Product.company_id == active_company.id, Product.sku == sku).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product with this SKU already exists")

    product = Product(
        company_id=active_company.id,
        sku=sku,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        hsn_sac=payload.hsn_sac,
        price=payload.price,
        gst_rate=payload.gst_rate,
        unit=payload.unit,
        allow_decimal=payload.allow_decimal,
        maintain_inventory=payload.maintain_inventory,
        is_producable=payload.is_producable,
        production_cost=payload.production_cost,
    )
    db.add(product)
    db.flush()  # get product.id before committing

    if not payload.maintain_inventory and payload.initial_quantity != 0:
        raise HTTPException(
            status_code=400,
            detail="Initial quantity is only allowed when maintain inventory is enabled",
        )

    if not payload.allow_decimal and not _is_whole_number(payload.initial_quantity):
        raise HTTPException(status_code=400, detail="Initial quantity must be a whole number for this product")

    if payload.maintain_inventory:
        inventory = Inventory(
            company_id=active_company.id,
            product_id=product.id,
            quantity=payload.initial_quantity,
        )
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
    is_producable: bool | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    query = db.query(Product).filter(Product.company_id == active_company.id)
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(or_(Product.name.ilike(term), Product.sku.ilike(term)))
    if is_producable is not None:
        query = query.filter(Product.is_producable == is_producable)
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
    active_company: CompanyProfile = Depends(get_active_company),
):
    if payload.gst_rate < 0 or payload.gst_rate > 100:
        raise HTTPException(status_code=400, detail="GST rate must be between 0 and 100")

    product = db.query(Product).filter(Product.id == product_id, Product.company_id == active_company.id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    sku = payload.sku.strip().upper()
    sku_owner = db.query(Product).filter(
        Product.company_id == active_company.id,
        Product.sku == sku,
        Product.id != product_id,
    ).first()
    if sku_owner:
        raise HTTPException(status_code=400, detail="Product with this SKU already exists")

    product.sku = sku
    product.name = payload.name.strip()
    product.description = payload.description.strip() if payload.description else None
    product.hsn_sac = payload.hsn_sac
    product.price = payload.price
    product.gst_rate = payload.gst_rate
    product.unit = payload.unit
    product.is_producable = payload.is_producable
    product.production_cost = payload.production_cost

    if product.allow_decimal and not payload.allow_decimal:
        inventory = db.query(Inventory).filter(
            Inventory.product_id == product_id,
            Inventory.company_id == active_company.id,
        ).first()
        if inventory and not _is_whole_number(float(inventory.quantity or 0)):
            raise HTTPException(
                status_code=400,
                detail="Cannot disable decimal quantity while inventory has fractional stock",
            )

    product.allow_decimal = payload.allow_decimal
    was_tracking_inventory = bool(product.maintain_inventory)
    product.maintain_inventory = payload.maintain_inventory

    if not was_tracking_inventory and payload.maintain_inventory:
        inventory = db.query(Inventory).filter(
            Inventory.product_id == product_id,
            Inventory.company_id == active_company.id,
        ).first()
        if not inventory:
            db.add(Inventory(company_id=active_company.id, product_id=product_id, quantity=0))

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    product = db.query(Product).filter(Product.id == product_id, Product.company_id == active_company.id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    has_invoice_items = (
        db.query(InvoiceItem.id)
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .filter(InvoiceItem.product_id == product_id, Invoice.company_id == active_company.id)
        .first()
    )
    if has_invoice_items:
        raise HTTPException(status_code=400, detail="Cannot delete product linked to invoices")

    inventory = db.query(Inventory).filter(
        Inventory.product_id == product_id,
        Inventory.company_id == active_company.id,
    ).first()
    if inventory:
        db.delete(inventory)

    db.delete(product)
    db.commit()
    return {"message": "Product deleted"}


# ---------------------------------------------------------------------------
# Merged Products + Inventory endpoints
# ---------------------------------------------------------------------------

@router.get("/with-inventory", response_model=dict)
def list_products_with_inventory(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str = Query(""),
    status_filter: str = Query("", alias="status"),
    sort_by: str = Query("name"),
    sort_order: str = Query("asc"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Returns products joined with their inventory data for the unified grid."""
    quantity_expr = func.coalesce(Inventory.quantity, 0)

    query = (
        db.query(
            Product,
            quantity_expr.label("current_stock"),
        )
        .outerjoin(
            Inventory,
            and_(
                Inventory.product_id == Product.id,
                Inventory.company_id == active_company.id,
            ),
        )
        .filter(Product.company_id == active_company.id)
    )

    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(Product.name.ilike(term), Product.sku.ilike(term))
        )

    if status_filter == "active":
        query = query.filter(Product.maintain_inventory == True)
    elif status_filter == "inactive":
        query = query.filter(Product.maintain_inventory == False)

    total = query.count()

    if sort_by == "name":
        order_col = Product.name
    elif sort_by == "sku":
        order_col = Product.sku
    elif sort_by == "price":
        order_col = Product.price
    elif sort_by == "stock":
        order_col = quantity_expr
    else:
        order_col = Product.name

    if sort_order == "desc":
        query = query.order_by(order_col.desc().nulls_last())
    else:
        query = query.order_by(order_col.asc().nulls_last())

    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for product, current_stock in rows:
        items.append(
            {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "description": product.description,
                "hsn_sac": product.hsn_sac,
                "purchase_price": 0.0,  # Not stored on product; kept for grid compatibility
                "selling_price": float(product.price),
                "current_stock": float(current_stock),
                "reorder_level": 0.0,  # Not stored; kept for grid compatibility
                "status": "active" if product.maintain_inventory else "inactive",
                "unit": product.unit,
                "gst_rate": float(product.gst_rate),
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 1,
    }


@router.put("/{product_id}/with-inventory")
def update_product_with_inventory(
    product_id: int,
    payload: ProductWithInventoryUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Update product fields and optionally inventory quantity in one call."""
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.company_id == active_company.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    # Update product fields
    if payload.name is not None:
        product.name = payload.name.strip()
    if payload.sku is not None:
        new_sku = payload.sku.strip().upper()
        existing = (
            db.query(Product)
            .filter(
                Product.company_id == active_company.id,
                Product.sku == new_sku,
                Product.id != product_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Product with this SKU already exists")
        product.sku = new_sku
    if payload.description is not None:
        product.description = payload.description.strip() if payload.description else None
    if payload.hsn_sac is not None:
        product.hsn_sac = payload.hsn_sac
    if payload.selling_price is not None:
        product.price = payload.selling_price
    if payload.gst_rate is not None:
        if payload.gst_rate < 0 or payload.gst_rate > 100:
            raise HTTPException(status_code=400, detail="GST rate must be between 0 and 100")
        product.gst_rate = payload.gst_rate
    if payload.unit is not None:
        product.unit = payload.unit.strip()

    if payload.status is not None:
        if payload.status == "active":
            product.maintain_inventory = True
        elif payload.status == "inactive":
            product.maintain_inventory = False

    # Update inventory quantity if provided
    if payload.current_stock is not None:
        inventory = (
            db.query(Inventory)
            .filter(
                Inventory.product_id == product_id,
                Inventory.company_id == active_company.id,
            )
            .first()
        )
        if inventory:
            inventory.quantity = Decimal(str(payload.current_stock))
        else:
            db.add(
                Inventory(
                    company_id=active_company.id,
                    product_id=product_id,
                    quantity=Decimal(str(payload.current_stock)),
                )
            )

    db.commit()
    db.refresh(product)

    # Return joined data
    inv = (
        db.query(Inventory)
        .filter(
            Inventory.product_id == product.id,
            Inventory.company_id == active_company.id,
        )
        .first()
    )
    stock = float(inv.quantity) if inv else 0.0

    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "hsn_sac": product.hsn_sac,
        "purchase_price": 0.0,
        "selling_price": float(product.price),
        "current_stock": stock,
        "reorder_level": 0.0,
        "status": "active" if product.maintain_inventory else "inactive",
        "unit": product.unit,
        "gst_rate": float(product.gst_rate),
    }


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

@router.get("/export-csv")
def export_products_csv(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Export all products with inventory as CSV."""
    quantity_expr = func.coalesce(Inventory.quantity, 0)
    rows = (
        db.query(
            Product,
            quantity_expr.label("current_stock"),
        )
        .outerjoin(
            Inventory,
            and_(
                Inventory.product_id == Product.id,
                Inventory.company_id == active_company.id,
            ),
        )
        .filter(Product.company_id == active_company.id)
        .order_by(Product.name.asc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Item Name", "Item Code", "Category", "Purchase Price",
        "Selling Price", "Current Stock", "Reorder Level",
        "Description", "HSN Code", "Unit", "Tax",
    ])

    for product, stock in rows:
        writer.writerow([
            product.name,
            product.sku,
            "",  # Category — not stored
            "0.00",
            str(product.price),
            str(float(stock)),
            "0",  # Reorder level
            product.description or "",
            product.hsn_sac or "",
            product.unit or "",
            str(product.gst_rate),
        ])

    output.seek(0)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="products_inventory_{timestamp}.csv"'
        },
    )


# ---------------------------------------------------------------------------
# CSV Import
# ---------------------------------------------------------------------------

@router.post("/import-csv", response_model=ImportCSVResult)
async def import_products_csv(
    file: UploadFile = FastAPIFile(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.manager)),
    active_company: CompanyProfile = Depends(get_active_company),
):
    """Import products from CSV — upsert by Item Code (SKU).

    Accepts a multipart/form-data upload with a field named 'file'.
    Returns a summary of created, updated, and error counts.
    """
    content = await file.read()
    return _import_csv_from_content(content, db, active_company)


def _import_csv_from_content(content: bytes, db: Session, active_company: CompanyProfile) -> dict:
    created = 0
    updated = 0
    errors: list[dict] = []

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        return {"created": 0, "updated": 0, "errors": [{"row": 0, "message": f"Invalid file encoding: {e}"}]}

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return {"created": 0, "updated": 0, "errors": [{"row": 0, "message": "CSV file appears to be empty"}]}

    # Normalise column names
    normalised = [h.strip().lower().replace(" ", "_") for h in reader.fieldnames]

    row_num = 1  # header is row 0
    for row in reader:
        row_num += 1
        values = dict(zip(normalised, [v.strip() if v else "" for v in row.values()]))

        item_code = values.get("item_code") or values.get("sku") or values.get("item_code")
        item_name = values.get("item_name") or values.get("name")

        if not item_code:
            errors.append({"row": row_num, "message": "Missing Item Code / SKU"})
            continue
        if not item_name:
            errors.append({"row": row_num, "message": f"Missing Item Name for SKU {item_code}"})
            continue

        sku = item_code.strip().upper()

        try:
            selling_price = float(values.get("selling_price") or 0)
        except ValueError:
            errors.append({"row": row_num, "message": f"Invalid Selling Price for {sku}"})
            continue

        try:
            gst_rate = float(values.get("tax") or values.get("gst") or 0)
            if gst_rate < 0 or gst_rate > 100:
                gst_rate = 0
        except ValueError:
            gst_rate = 0

        try:
            stock = float(values.get("current_stock") or values.get("stock") or 0)
        except ValueError:
            stock = 0

        existing = (
            db.query(Product)
            .filter(
                Product.company_id == active_company.id,
                Product.sku == sku,
            )
            .first()
        )

        if existing:
            existing.name = item_name
            existing.price = selling_price
            existing.gst_rate = gst_rate
            if values.get("description"):
                existing.description = values["description"]
            if values.get("hsn_code"):
                existing.hsn_sac = values["hsn_code"]
            if values.get("unit"):
                existing.unit = values["unit"]

            # Update inventory
            inv = (
                db.query(Inventory)
                .filter(
                    Inventory.product_id == existing.id,
                    Inventory.company_id == active_company.id,
                )
                .first()
            )
            if inv:
                inv.quantity = Decimal(str(stock))
            elif existing.maintain_inventory:
                db.add(Inventory(company_id=active_company.id, product_id=existing.id, quantity=Decimal(str(stock))))

            updated += 1
        else:
            product = Product(
                company_id=active_company.id,
                sku=sku,
                name=item_name,
                description=values.get("description") or None,
                hsn_sac=values.get("hsn_code") or None,
                price=selling_price,
                gst_rate=gst_rate,
                unit=values.get("unit") or "Pieces",
            )
            db.add(product)
            db.flush()

            if product.maintain_inventory:
                db.add(Inventory(company_id=active_company.id, product_id=product.id, quantity=Decimal(str(stock))))

            created += 1

    db.commit()
    return {"created": created, "updated": updated, "errors": errors}
