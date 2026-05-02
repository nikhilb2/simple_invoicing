"""
BOM (Bill of Materials) business logic service.
Handles BOM calculations, validation, and production execution.
"""

from decimal import Decimal
from typing import Set
from sqlalchemy.orm import Session
from sqlalchemy import and_

from src.models.bom import BillOfMaterial
from src.models.product import Product
from src.models.inventory import Inventory
from src.models.production_transaction import ProductionTransaction
from src.schemas.bom import BOMComponentOut


class CircularBOMError(Exception):
    """Raised when a circular BOM reference is detected."""
    pass


class InsufficientInventoryError(Exception):
    """Raised when there's insufficient inventory for production."""
    pass


def _can_reach(
    db: Session,
    company_id: int,
    start: int,
    target: int,
    seen: Set[int] | None = None,
) -> bool:
    """
    Return True if `target` is reachable from `start` by following BOM edges.
    Uses `seen` to avoid revisiting nodes (handles diamonds and cycles safely).
    """
    if seen is None:
        seen = set()

    if start == target:
        return True

    if start in seen:
        return False

    seen.add(start)

    bom_entries = db.query(BillOfMaterial).filter(
        and_(
            BillOfMaterial.company_id == company_id,
            BillOfMaterial.product_id == start,
        )
    ).all()

    for bom in bom_entries:
        if _can_reach(db, company_id, bom.component_product_id, target, seen):
            return True

    return False


def validate_no_circular_bom(
    db: Session, company_id: int, product_id: int, component_product_id: int
) -> None:
    """
    Validate that adding component_product_id to product_id's BOM won't create cycles.
    A cycle exists if product_id is reachable FROM component_product_id (i.e. component
    already has product_id in its own BOM sub-tree).
    Raises CircularBOMError if validation fails.
    """
    if _can_reach(db, company_id, component_product_id, product_id):
        raise CircularBOMError(
            f"Cannot add product {component_product_id} as component of {product_id}: "
            "would create a circular BOM reference."
        )


def get_bom_components(
    db: Session,
    company_id: int,
    product_id: int,
) -> list[BOMComponentOut]:
    """
    Get all direct BOM components for a product with denormalized component product info.
    """
    bom_entries = db.query(BillOfMaterial).filter(
        and_(
            BillOfMaterial.company_id == company_id,
            BillOfMaterial.product_id == product_id,
        )
    ).all()

    result = []
    for bom in bom_entries:
        component = db.query(Product).filter(Product.id == bom.component_product_id).first()
        if component:
            result.append(
                BOMComponentOut(
                    id=bom.id,
                    product_id=bom.product_id,
                    component_product_id=bom.component_product_id,
                    quantity_required=float(bom.quantity_required),
                    created_at=bom.created_at,
                    component_sku=component.sku,
                    component_name=component.name,
                    component_price=float(component.price),
                    component_unit=component.unit,
                    component_allow_decimal=component.allow_decimal,
                )
            )

    return result


def calculate_bom_cost_recursive(
    db: Session,
    company_id: int,
    product_id: int,
    visited: Set[int] | None = None,
) -> Decimal:
    """
    Recursively calculate total cost of a BOM by summing component costs.
    Prevents infinite loops by tracking visited products.
    
    Returns cost as Decimal(12,2).
    """
    if visited is None:
        visited = set()

    if product_id in visited:
        return Decimal("0")

    visited.add(product_id)

    cost = Decimal("0")
    bom_entries = db.query(BillOfMaterial).filter(
        and_(
            BillOfMaterial.company_id == company_id,
            BillOfMaterial.product_id == product_id,
        )
    ).all()

    for bom in bom_entries:
        component = db.query(Product).filter(Product.id == bom.component_product_id).first()
        if component:
            # Component cost = component.price * quantity_required
            component_total = Decimal(str(component.price)) * Decimal(str(bom.quantity_required))
            
            # If component is also producable, use its production cost if available
            if component.is_producable and component.production_cost is not None:
                component_cost = Decimal(str(component.production_cost))
                component_total = component_cost * Decimal(str(bom.quantity_required))
            else:
                # Recursively sum sub-components if producable but no production_cost
                if component.is_producable:
                    sub_cost = calculate_bom_cost_recursive(
                        db, company_id, component.id, visited.copy()
                    )
                    component_total = sub_cost * Decimal(str(bom.quantity_required))

            cost += component_total

    return cost


def get_bom_requirements(
    db: Session,
    company_id: int,
    product_id: int,
    quantity: Decimal,
) -> dict[int, Decimal]:
    """
    Return direct BOM component requirements for producing `quantity` units of `product_id`.
    Returns dict: {component_product_id: total_quantity_needed}

    Deliberately does NOT recurse into producable sub-components — if a component
    is itself producable the user must produce it as a separate step first. This
    prevents double-deduction (consuming both B and B's raw-materials in one hit).
    """
    requirements: dict[int, Decimal] = {}

    bom_entries = db.query(BillOfMaterial).filter(
        and_(
            BillOfMaterial.company_id == company_id,
            BillOfMaterial.product_id == product_id,
        )
    ).all()

    for bom in bom_entries:
        component_id = bom.component_product_id
        qty_per_unit = Decimal(str(bom.quantity_required))
        total_qty = qty_per_unit * quantity
        requirements[component_id] = requirements.get(component_id, Decimal("0")) + total_qty

    return requirements


def validate_bom_availability(
    db: Session,
    company_id: int,
    product_id: int,
    quantity: Decimal,
) -> tuple[bool, str]:
    """
    Check if there's sufficient inventory for all BOM components.
    Returns: (is_valid, error_message)
    """
    requirements = get_bom_requirements(db, company_id, product_id, quantity)

    for component_id, required_qty in requirements.items():
        inventory = db.query(Inventory).filter(
            Inventory.product_id == component_id,
            Inventory.company_id == company_id,
        ).first()

        if not inventory:
            component = db.query(Product).filter(Product.id == component_id).first()
            return (
                False,
                f"No inventory record for component: {component.sku if component else 'Unknown'}",
            )

        available_qty = Decimal(str(inventory.quantity))
        if available_qty < required_qty:
            component = db.query(Product).filter(Product.id == component_id).first()
            return (
                False,
                f"Insufficient inventory for {component.sku if component else 'Unknown'}: "
                f"need {required_qty}, have {available_qty}",
            )

    return (True, "")


def execute_production(
    db: Session,
    company_id: int,
    product_id: int,
    quantity: Decimal,
    user_id: int,
    notes: str | None = None,
) -> dict:
    """
    Execute production: deduct all BOM components, increment producable item inventory.
    This is an atomic operation wrapped in a transaction.
    
    Returns: {
        "success": bool,
        "message": str,
        "transaction_id": int (if successful),
        "inventory_changes": {
            "component_id": {"product_sku": str, "before": float, "after": float}
        }
    }
    """
    # Validate product is producable
    product = db.query(Product).filter(
        and_(Product.id == product_id, Product.company_id == company_id)
    ).first()

    if not product or not product.is_producable:
        return {
            "success": False,
            "message": "Product is not marked as producable",
        }

    # Validate inventory availability
    is_available, error_msg = validate_bom_availability(db, company_id, product_id, quantity)
    if not is_available:
        return {
            "success": False,
            "message": f"Production blocked: {error_msg}",
        }

    # Get material requirements
    requirements = get_bom_requirements(db, company_id, product_id, quantity)

    try:
        inventory_changes = {}

        # Deduct all components
        for component_id, required_qty in requirements.items():
            inventory = db.query(Inventory).filter(
                Inventory.product_id == component_id,
                Inventory.company_id == company_id,
            ).first()

            component = db.query(Product).filter(Product.id == component_id).first()

            before_qty = float(inventory.quantity)
            inventory.quantity -= required_qty

            after_qty = float(inventory.quantity)
            inventory_changes[component_id] = {
                "product_sku": component.sku,
                "before": before_qty,
                "after": after_qty,
            }

            db.add(inventory)

        # Increment producable item inventory
        product_inventory = db.query(Inventory).filter(
            Inventory.product_id == product_id,
            Inventory.company_id == company_id,
        ).first()

        if not product_inventory:
            product_inventory = Inventory(
                company_id=company_id, product_id=product_id, quantity=Decimal("0")
            )
            db.add(product_inventory)

        before_produced = float(product_inventory.quantity)
        product_inventory.quantity += quantity
        after_produced = float(product_inventory.quantity)

        inventory_changes[product_id] = {
            "product_sku": product.sku,
            "before": before_produced,
            "after": after_produced,
        }

        # Log transaction
        transaction = ProductionTransaction(
            company_id=company_id,
            product_id=product_id,
            quantity_produced=quantity,
            user_id=user_id,
            notes=notes,
        )
        db.add(transaction)

        db.flush()  # populate transaction.id before commit
        transaction_id = transaction.id
        db.commit()

        return {
            "success": True,
            "message": f"Successfully produced {quantity} units of {product.sku}",
            "transaction_id": transaction_id,
            "inventory_changes": inventory_changes,
        }

    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "message": f"Production failed: {str(e)}",
        }
