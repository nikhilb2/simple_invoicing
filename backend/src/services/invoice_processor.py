"""
InvoiceProcessor service — encapsulates invoice payload application, inventory
delta calculation, and ledger/item validation that used to live in the route
handler.  Separating this logic makes it independently testable and reusable
outside of the HTTP layer.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.models.buyer import Buyer as Ledger
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.invoice import Invoice, InvoiceItem
from src.models.product import Product
from src.schemas.invoice import InvoiceCreate
from src.services.gst_tax_service import (
    assign_invoice_tax_totals,
    assign_item_tax_split,
    is_interstate_supply,
    money as _money,
)
from src.services.series import generate_next_number


# ---------------------------------------------------------------------------
# Module-level helpers (pure / stateless)
# ---------------------------------------------------------------------------

def inventory_effect_for_voucher_type(quantity: float, voucher_type: str) -> Decimal:
    """Return the signed inventory delta for *quantity* depending on voucher type.

    Sales reduce stock (negative), purchases increase it (positive).
    """
    quantity_value = Decimal(str(quantity))
    return -quantity_value if voucher_type == "sales" else quantity_value


def change_inventory_quantity(
    db: Session,
    product_id: int,
    quantity_delta: Decimal,
    *,
    company_id: int | None,
    context: str,
) -> None:
    """Apply *quantity_delta* to the inventory row for *product_id*.

    Creates the inventory row if it does not exist yet.  Raises 400 if the
    resulting quantity would drop below zero.
    """
    query = db.query(Inventory).filter(Inventory.product_id == product_id)
    if company_id is not None:
        query = query.filter(
            or_(Inventory.company_id == company_id, Inventory.company_id.is_(None))
        )
    inventory = query.first()
    if not inventory:
        inventory = Inventory(company_id=company_id, product_id=product_id, quantity=0)
        db.add(inventory)
        db.flush()

    inventory.quantity = Decimal(str(inventory.quantity or 0)) + quantity_delta
    if Decimal(str(inventory.quantity or 0)) < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient inventory while {context}",
        )


# ---------------------------------------------------------------------------
# InvoiceProcessor class
# ---------------------------------------------------------------------------

class InvoiceProcessor:
    """Encapsulates invoice payload application and inventory management."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Ledger helpers
    # ------------------------------------------------------------------

    def require_ledger(self, ledger_id: int, company_id: int | None) -> Ledger:
        """Fetch the ledger by *ledger_id*, scoped to *company_id*.

        Raises 404 if not found.
        """
        query = self.db.query(Ledger).filter(Ledger.id == ledger_id)
        if company_id is not None:
            query = query.filter(
                or_(Ledger.company_id == company_id, Ledger.company_id.is_(None))
            )
        ledger = query.first()
        if not ledger:
            raise HTTPException(
                status_code=404, detail=f"Ledger {ledger_id} not found"
            )
        return ledger

    # ------------------------------------------------------------------
    # Inventory helpers
    # ------------------------------------------------------------------

    def reverse_inventory(self, invoice: Invoice) -> None:
        """Undo the inventory effect of an existing invoice's line items.

        Used when cancelling an invoice.
        """
        for item in invoice.items:
            product_query = self.db.query(Product).filter(
                Product.id == item.product_id
            )
            if invoice.company_id is not None:
                product_query = product_query.filter(
                    or_(
                        Product.company_id == invoice.company_id,
                        Product.company_id.is_(None),
                    )
                )
            product = product_query.first()
            if not product:
                raise HTTPException(
                    status_code=404,
                    detail=f"Product {item.product_id} not found",
                )
            if not product.maintain_inventory:
                continue

            reverse_delta = (
                Decimal(str(item.quantity))
                if invoice.voucher_type == "sales"
                else -Decimal(str(item.quantity))
            )
            change_inventory_quantity(
                self.db,
                item.product_id,
                reverse_delta,
                company_id=invoice.company_id,
                context=f"reversing invoice {invoice.id}",
            )

    def restore_inventory(self, invoice: Invoice, *, company_id: int) -> None:
        """Re-apply the inventory effect of a previously-cancelled invoice.

        Used when restoring an invoice.
        """
        for item in invoice.items:
            product_query = self.db.query(Product).filter(
                Product.id == item.product_id
            )
            product_query = product_query.filter(
                or_(
                    Product.company_id == company_id,
                    Product.company_id.is_(None),
                )
            )
            product = product_query.first()
            if not product:
                raise HTTPException(
                    status_code=404,
                    detail=f"Product {item.product_id} not found",
                )
            if not product.maintain_inventory:
                continue

            restore_delta = (
                -Decimal(str(item.quantity))
                if invoice.voucher_type == "sales"
                else Decimal(str(item.quantity))
            )
            change_inventory_quantity(
                self.db,
                item.product_id,
                restore_delta,
                company_id=company_id,
                context=f"restoring invoice {invoice.id}",
            )

    def apply_inventory_delta_for_update(
        self,
        invoice: Invoice,
        payload: InvoiceCreate,
        *,
        company_id: int | None,
    ) -> None:
        """Compute and apply the *net* inventory delta when editing an invoice.

        Compares the existing items against the incoming payload items and only
        adjusts the difference, avoiding full reverse-then-reapply churn.
        """
        existing_effect_by_product: dict[int, Decimal] = defaultdict(
            lambda: Decimal("0")
        )
        for item in invoice.items:
            existing_effect_by_product[item.product_id] += (
                inventory_effect_for_voucher_type(
                    item.quantity,
                    invoice.voucher_type,
                )
            )

        next_effect_by_product: dict[int, Decimal] = defaultdict(
            lambda: Decimal("0")
        )
        for item in payload.items:
            next_effect_by_product[item.product_id] += (
                inventory_effect_for_voucher_type(
                    item.quantity,
                    payload.voucher_type,
                )
            )

        for product_id in set(existing_effect_by_product) | set(
            next_effect_by_product
        ):
            quantity_delta = (
                next_effect_by_product[product_id]
                - existing_effect_by_product[product_id]
            )
            if quantity_delta == 0:
                continue

            product_query = self.db.query(Product).filter(
                Product.id == product_id
            )
            if company_id is not None:
                product_query = product_query.filter(
                    or_(
                        Product.company_id == company_id,
                        Product.company_id.is_(None),
                    )
                )
            product = product_query.first()
            if not product:
                raise HTTPException(
                    status_code=404,
                    detail=f"Product {product_id} not found",
                )
            if not product.maintain_inventory:
                continue

            change_inventory_quantity(
                self.db,
                product_id,
                quantity_delta,
                company_id=company_id,
                context=f"editing invoice {invoice.id}",
            )

    # ------------------------------------------------------------------
    # Item validation
    # ------------------------------------------------------------------

    def validate_items(
        self,
        items: list,
        company_id: int | None,
        voucher_type: str,
        apply_inventory_changes: bool = True,
        invoice_id: int | None = None,
    ) -> list[tuple]:
        """Validate each line item and return a list of (item_schema, product, quantity_decimal)
        tuples, raising 400/404 errors for invalid data.
        """
        if not items:
            raise HTTPException(
                status_code=400,
                detail="Invoice must have at least one line item",
            )

        validated: list[tuple] = []
        for item in items:
            quantity_value = Decimal(str(item.quantity))
            if quantity_value <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Item quantity must be greater than zero",
                )

            product_query = self.db.query(Product).filter(
                Product.id == item.product_id
            )
            if company_id is not None:
                product_query = product_query.filter(
                    or_(
                        Product.company_id == company_id,
                        Product.company_id.is_(None),
                    )
                )
            product = product_query.first()
            if not product:
                raise HTTPException(
                    status_code=404,
                    detail=f"Product {item.product_id} not found",
                )

            if not product.allow_decimal and quantity_value != quantity_value.to_integral_value():
                raise HTTPException(
                    status_code=400,
                    detail=f"Quantity for {product.name} must be a whole number",
                )

            if apply_inventory_changes and product.maintain_inventory:
                inventory_query = self.db.query(Inventory).filter(
                    Inventory.product_id == item.product_id
                )
                if company_id is not None:
                    inventory_query = inventory_query.filter(
                        or_(
                            Inventory.company_id == company_id,
                            Inventory.company_id.is_(None),
                        )
                    )
                inventory = inventory_query.first()
                if voucher_type == "sales" and (
                    not inventory
                    or Decimal(str(inventory.quantity or 0)) < quantity_value
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient inventory for {product.name}",
                    )

            validated.append((item, product, quantity_value))
        return validated

    # ------------------------------------------------------------------
    # Totals calculation
    # ------------------------------------------------------------------

    def calculate_totals(
        self,
        validated_items: list[tuple],
        tax_inclusive: bool,
    ) -> list[dict]:
        """Compute per-line tax and total amounts.

        Accepts the output of :meth:`validate_items` and returns a list of
        dicts with the calculated fields for each line item.
        """
        results = []
        for item_schema, product, quantity_value in validated_items:
            unit_price = (
                Decimal(str(item_schema.unit_price))
                if item_schema.unit_price is not None
                else Decimal(str(product.price))
            )
            gst_rate = Decimal(str(product.gst_rate or 0))

            if tax_inclusive:
                line_total = _money(unit_price * quantity_value)
                taxable_amount = _money(
                    line_total / (1 + gst_rate / Decimal("100"))
                )
                tax_amount = _money(line_total - taxable_amount)
            else:
                taxable_amount = _money(unit_price * quantity_value)
                tax_amount = _money(
                    taxable_amount * gst_rate / Decimal("100")
                )
                line_total = _money(taxable_amount + tax_amount)

            results.append(
                {
                    "item_schema": item_schema,
                    "product": product,
                    "quantity_value": quantity_value,
                    "unit_price": unit_price,
                    "gst_rate": gst_rate,
                    "taxable_amount": taxable_amount,
                    "tax_amount": tax_amount,
                    "line_total": line_total,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Main payload application
    # ------------------------------------------------------------------

    def apply_payload(
        self,
        invoice: Invoice,
        payload: InvoiceCreate,
        active_company: CompanyProfile | None = None,
        created_by: int | None = None,
        financial_year_id: int | None = None,
        active_financial_year_id: int | None = None,
        regenerate_number: bool = True,
        apply_inventory_changes: bool = True,
    ) -> None:
        """Apply *payload* data onto *invoice*, updating all scalar fields,
        creating new InvoiceItem rows, and recalculating totals.

        This is the primary entry-point used by both create and update routes.
        """
        company = active_company or (
            self.db.query(CompanyProfile)
            .order_by(CompanyProfile.id.asc())
            .first()
        )
        company_id = company.id if company else None
        ledger = self.require_ledger(payload.ledger_id, company_id)

        # Snapshot company / ledger fields onto the invoice record
        invoice.company_id = company_id
        invoice.ledger_id = ledger.id
        invoice.ledger_name = ledger.name
        invoice.ledger_address = ledger.address
        invoice.ledger_gst = ledger.gst
        invoice.ledger_phone = ledger.phone_number
        invoice.company_name = company.name if company else None
        invoice.company_address = company.address if company else None
        invoice.company_gst = company.gst if company else None
        invoice.company_phone = company.phone_number if company else None
        invoice.company_email = company.email if company else None
        invoice.company_website = company.website if company else None
        invoice.company_currency_code = company.currency_code if company else None
        invoice.company_bank_name = company.bank_name if company else None
        invoice.company_branch_name = company.branch_name if company else None
        invoice.company_account_name = company.account_name if company else None
        invoice.company_account_number = company.account_number if company else None
        invoice.company_ifsc_code = company.ifsc_code if company else None
        invoice.voucher_type = payload.voucher_type
        invoice.supplier_invoice_number = payload.supplier_invoice_number
        invoice.reference_notes = payload.reference_notes
        if created_by is not None:
            invoice.created_by = created_by
        if financial_year_id is not None:
            invoice.financial_year_id = financial_year_id

        if payload.invoice_date is not None:
            invoice.invoice_date = datetime.combine(
                payload.invoice_date, datetime.min.time()
            )

        invoice.due_date = (
            datetime.combine(payload.due_date, datetime.min.time())
            if payload.due_date is not None
            else None
        )

        invoice.tax_inclusive = payload.tax_inclusive
        invoice.apply_round_off = payload.apply_round_off

        if regenerate_number:
            invoice.invoice_number = generate_next_number(
                self.db,
                invoice.voucher_type,
                financial_year_id,
                payload.invoice_date,
                active_financial_year_id,
                company_id=company_id,
            )

        # Validate items and check inventory availability
        validated = self.validate_items(
            payload.items,
            company_id,
            payload.voucher_type,
            apply_inventory_changes=apply_inventory_changes,
            invoice_id=invoice.id,
        )

        interstate_supply = is_interstate_supply(
            invoice.company_gst, invoice.ledger_gst
        )

        # Apply inventory changes for new items
        if apply_inventory_changes:
            for item_schema, product, quantity_value in validated:
                if product.maintain_inventory:
                    quantity_delta = inventory_effect_for_voucher_type(
                        item_schema.quantity, payload.voucher_type
                    )
                    change_inventory_quantity(
                        self.db,
                        item_schema.product_id,
                        quantity_delta,
                        company_id=company_id,
                        context=f"applying invoice {invoice.id or 'new'}",
                    )

        # Calculate per-line totals
        line_results = self.calculate_totals(validated, payload.tax_inclusive)

        # Create InvoiceItem ORM objects
        taxable_total = Decimal("0")
        created_items: list[InvoiceItem] = []
        for result in line_results:
            taxable_total += result["taxable_amount"]
            invoice_item = InvoiceItem(
                invoice_id=invoice.id,
                product_id=result["product"].id,
                quantity=float(result["quantity_value"]),
                hsn_sac=result["product"].hsn_sac,
                unit_price=float(result["unit_price"]),
                gst_rate=float(result["gst_rate"]),
                taxable_amount=float(result["taxable_amount"]),
                tax_amount=float(result["tax_amount"]),
                line_total=float(result["line_total"]),
                description=result["item_schema"].description,
            )
            created_items.append(invoice_item)
            self.db.add(invoice_item)

        taxable_total = _money(taxable_total)
        invoice.taxable_amount = float(taxable_total)

        assign_item_tax_split(created_items, interstate_supply=interstate_supply)

        tax_total = assign_invoice_tax_totals(
            invoice, created_items, interstate_supply=interstate_supply
        )
        raw_total = _money(taxable_total + tax_total)
        if invoice.apply_round_off:
            rounded_total = raw_total.quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            round_off_amount = _money(rounded_total - raw_total)
            invoice.round_off_amount = float(round_off_amount)
            invoice.total_amount = float(_money(rounded_total))
        else:
            invoice.round_off_amount = 0
            invoice.total_amount = float(raw_total)
