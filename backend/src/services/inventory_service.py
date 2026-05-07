"""
InventoryManager service — centralizes all inventory quantity operations:
  * applying voucher effects
  * checking stock availability before sales
  * updating quantities (create row if absent, guard against negative stock)
  * reversing / restoring invoice inventory on cancel / restore
  * computing net deltas when an invoice is edited
"""

import logging
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.models.inventory import Inventory
from src.models.invoice import Invoice
from src.models.product import Product
from src.schemas.invoice import InvoiceCreate

logger = logging.getLogger(__name__)


class InventoryManager:
    """Centralises all inventory quantity operations for invoices."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Pure helpers
    # ------------------------------------------------------------------

    @staticmethod
    def effect_for_voucher_type(quantity: float, voucher_type: str) -> Decimal:
        """Return the signed inventory delta for *quantity* and *voucher_type*.

        Sales reduce stock (negative); purchases increase it (positive).
        """
        quantity_value = Decimal(str(quantity))
        return -quantity_value if voucher_type == "sales" else quantity_value

    # ------------------------------------------------------------------
    # Row-level operations
    # ------------------------------------------------------------------

    def update_quantity(
        self,
        product_id: int,
        quantity_delta: Decimal,
        *,
        company_id: int | None,
        context: str,
    ) -> None:
        """Apply *quantity_delta* to the inventory row for *product_id*.

        Creates the row if it does not exist yet.  Raises HTTP 400 if the
        resulting quantity would drop below zero.
        """
        query = self.db.query(Inventory).filter(Inventory.product_id == product_id)
        if company_id is not None:
            query = query.filter(
                or_(
                    Inventory.company_id == company_id,
                    Inventory.company_id.is_(None),
                )
            )
        inventory = query.first()
        if not inventory:
            inventory = Inventory(
                company_id=company_id, product_id=product_id, quantity=0
            )
            self.db.add(inventory)
            self.db.flush()
            logger.debug(
                "inventory: created new row for product_id=%s company_id=%s",
                product_id,
                company_id,
            )

        new_quantity = Decimal(str(inventory.quantity or 0)) + quantity_delta
        if new_quantity < 0:
            logger.warning(
                "inventory: quantity would go negative for product_id=%s "
                "(current=%s delta=%s context=%s)",
                product_id,
                inventory.quantity,
                quantity_delta,
                context,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient inventory while {context}",
            )
        inventory.quantity = new_quantity
        logger.debug(
            "inventory: updated product_id=%s delta=%s new_qty=%s (%s)",
            product_id,
            quantity_delta,
            new_quantity,
            context,
        )

    def check_availability(
        self,
        product_id: int,
        quantity: Decimal,
        *,
        company_id: int | None,
        product_name: str,
    ) -> None:
        """Raise HTTP 400 if there is insufficient stock for a sales item.

        Only call this when *voucher_type* is ``"sales"``.
        """
        inventory_query = self.db.query(Inventory).filter(
            Inventory.product_id == product_id
        )
        if company_id is not None:
            inventory_query = inventory_query.filter(
                or_(
                    Inventory.company_id == company_id,
                    Inventory.company_id.is_(None),
                )
            )
        inventory = inventory_query.first()
        if not inventory or Decimal(str(inventory.quantity or 0)) < quantity:
            logger.warning(
                "inventory: insufficient stock for product_id=%s "
                "(available=%s required=%s)",
                product_id,
                inventory.quantity if inventory else 0,
                quantity,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient inventory for {product_name}",
            )

    # ------------------------------------------------------------------
    # Invoice-level operations
    # ------------------------------------------------------------------

    def _get_product(
        self, product_id: int, company_id: int | None, context: str
    ) -> Product:
        """Fetch a product scoped to *company_id*, raising 404 if absent."""
        query = self.db.query(Product).filter(Product.id == product_id)
        if company_id is not None:
            query = query.filter(
                or_(
                    Product.company_id == company_id,
                    Product.company_id.is_(None),
                )
            )
        product = query.first()
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product {product_id} not found",
            )
        return product

    def reverse_invoice_inventory(self, invoice: Invoice) -> None:
        """Undo the inventory effect of all line items on *invoice*.

        Used when cancelling an invoice.
        """
        logger.info(
            "inventory: reversing invoice_id=%s voucher_type=%s",
            invoice.id,
            invoice.voucher_type,
        )
        for item in invoice.items:
            product = self._get_product(
                item.product_id, invoice.company_id, f"reversing invoice {invoice.id}"
            )
            if not product.maintain_inventory:
                continue

            reverse_delta = (
                Decimal(str(item.quantity))
                if invoice.voucher_type == "sales"
                else -Decimal(str(item.quantity))
            )
            self.update_quantity(
                item.product_id,
                reverse_delta,
                company_id=invoice.company_id,
                context=f"reversing invoice {invoice.id}",
            )

    def restore_invoice_inventory(
        self, invoice: Invoice, *, company_id: int
    ) -> None:
        """Re-apply the inventory effect of a previously-cancelled invoice.

        Used when restoring an invoice.
        """
        logger.info(
            "inventory: restoring invoice_id=%s company_id=%s",
            invoice.id,
            company_id,
        )
        for item in invoice.items:
            product = self._get_product(
                item.product_id, company_id, f"restoring invoice {invoice.id}"
            )
            if not product.maintain_inventory:
                continue

            restore_delta = (
                -Decimal(str(item.quantity))
                if invoice.voucher_type == "sales"
                else Decimal(str(item.quantity))
            )
            self.update_quantity(
                item.product_id,
                restore_delta,
                company_id=company_id,
                context=f"restoring invoice {invoice.id}",
            )

    def apply_invoice_changes(
        self,
        invoice: Invoice,
        payload: InvoiceCreate,
        *,
        company_id: int | None,
    ) -> None:
        """Compute and apply the *net* inventory delta when editing an invoice.

        Compares existing line items against incoming payload items and applies
        only the difference, avoiding a full reverse-then-reapply cycle.
        """
        logger.info(
            "inventory: applying net delta for invoice_id=%s company_id=%s",
            invoice.id,
            company_id,
        )
        existing_effect: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        for item in invoice.items:
            existing_effect[item.product_id] += self.effect_for_voucher_type(
                item.quantity, invoice.voucher_type
            )

        next_effect: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        for item in payload.items:
            next_effect[item.product_id] += self.effect_for_voucher_type(
                item.quantity, payload.voucher_type
            )

        for product_id in set(existing_effect) | set(next_effect):
            delta = next_effect[product_id] - existing_effect[product_id]
            if delta == 0:
                continue

            product = self._get_product(
                product_id, company_id, f"editing invoice {invoice.id}"
            )
            if not product.maintain_inventory:
                continue

            self.update_quantity(
                product_id,
                delta,
                company_id=company_id,
                context=f"editing invoice {invoice.id}",
            )

    def apply_new_items(
        self,
        items: list,
        voucher_type: str,
        *,
        company_id: int | None,
        invoice_id: int | None,
    ) -> None:
        """Apply inventory changes for a freshly-created set of line items.

        *items* is a sequence of ``(item_schema, product, quantity_decimal)``
        tuples as returned by :meth:`InvoiceProcessor.validate_items`.
        Only products with ``maintain_inventory=True`` are touched.
        """
        context = f"applying invoice {invoice_id or 'new'}"
        for item_schema, product, quantity_value in items:
            if not product.maintain_inventory:
                continue
            delta = self.effect_for_voucher_type(item_schema.quantity, voucher_type)
            self.update_quantity(
                item_schema.product_id,
                delta,
                company_id=company_id,
                context=context,
            )
