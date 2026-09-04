"""
SerialManager service — centralizes all per-unit serial / IMEI operations:
  * validating the serial numbers on a set of line items before anything is written
  * registering serials on a purchase and consuming them on a sale
  * computing the per-product set-diff when an invoice is edited
  * reversing / restoring invoice serials on cancel / restore
  * resolving a scanned code back to the unit it belongs to

Deliberately shaped like :class:`src.services.inventory_service.InventoryManager`
so it hooks into the same call sites.  The invariant the two of them hold
together is ``inventory.quantity == count(in_stock serials)`` for a tracked
product; every method below exists to keep that line.
"""

import logging
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.models.invoice import Invoice
from src.models.product import Product
from src.models.product_serial import (
    STATUS_IN_STOCK,
    STATUS_SOLD,
    STATUS_VOID,
    ProductSerial,
)
from src.schemas.invoice import InvoiceCreate

logger = logging.getLogger(__name__)


class SerialManager:
    """Centralises all serial-number operations for invoices."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Pure helpers
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(code: str | None) -> str:
        """Return *code* stripped, with any inner whitespace collapsed.

        Scanners and pasted distributor lists both introduce stray spacing.
        The result is stored exactly as entered; comparison is case-insensitive.
        """
        return " ".join((code or "").split())

    @classmethod
    def _codes_for(cls, item_schema) -> list[str]:
        """Normalized, blank-free serial numbers carried by a line-item schema."""
        raw = getattr(item_schema, "serial_numbers", None) or []
        return [code for code in (cls.normalize(value) for value in raw) if code]

    # ------------------------------------------------------------------
    # Row-level lookups
    # ------------------------------------------------------------------

    def _scoped(self, query, company_id: int | None):
        """Apply the tenant filter, tolerating legacy rows with a NULL company."""
        if company_id is None:
            return query
        return query.filter(
            or_(
                ProductSerial.company_id == company_id,
                ProductSerial.company_id.is_(None),
            )
        )

    def _live_row(self, code: str, company_id: int | None) -> ProductSerial | None:
        """Return the non-void row matching *code* case-insensitively, if any."""
        query = self.db.query(ProductSerial).filter(
            func.upper(ProductSerial.serial_number) == code.upper(),
            ProductSerial.status != STATUS_VOID,
        )
        return self._scoped(query, company_id).first()

    def _live_rows(
        self, codes, company_id: int | None
    ) -> dict[str, ProductSerial]:
        """Bulk-resolve *codes* to their non-void rows, keyed by upper-case code."""
        upper_codes = [code.upper() for code in codes]
        if not upper_codes:
            return {}
        query = self.db.query(ProductSerial).filter(
            func.upper(ProductSerial.serial_number).in_(upper_codes),
            ProductSerial.status != STATUS_VOID,
        )
        return {
            row.serial_number.upper(): row
            for row in self._scoped(query, company_id).all()
        }

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

    def _product_name(self, product_id: int) -> str:
        """Best-effort display name for an error message."""
        product = self.db.query(Product).filter(Product.id == product_id).first()
        return product.name if product else f"product {product_id}"

    def _invoice_number(self, invoice_id: int | None) -> str | None:
        """Best-effort invoice number for an error message."""
        if invoice_id is None:
            return None
        invoice = self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
        return invoice.invoice_number if invoice else None

    # ------------------------------------------------------------------
    # Guards — shared by validation and by the write paths that back it up
    # ------------------------------------------------------------------

    def _require_registrable(
        self, code: str, row: ProductSerial | None, *, invoice_id: int | None
    ) -> None:
        """Raise 400 unless *code* is free to be received on *invoice_id*."""
        if row is None or row.purchase_invoice_id == invoice_id:
            return
        detail = f"Serial {code} is already registered to {self._product_name(row.product_id)}"
        source = self._invoice_number(row.purchase_invoice_id)
        if source:
            detail += f" on {source}"
        logger.warning(
            "serials: registration collision for %s (existing_id=%s status=%s)",
            code,
            row.id,
            row.status,
        )
        raise HTTPException(status_code=400, detail=detail)

    def _require_sellable(
        self,
        code: str,
        row: ProductSerial | None,
        *,
        product_id: int,
        invoice_id: int | None,
    ) -> ProductSerial:
        """Raise 400 unless *code* is a unit of *product_id* that can go out."""
        if row is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Serial {code} is not in stock — check the code, "
                    "or receive it on a purchase entry first"
                ),
            )
        if row.product_id != product_id:
            raise HTTPException(
                status_code=400,
                detail=f"Serial {code} is already registered to {self._product_name(row.product_id)}",
            )
        if row.status == STATUS_SOLD and row.sales_invoice_id != invoice_id:
            sold_on = self._invoice_number(row.sales_invoice_id)
            detail = f"Serial {code} has already been sold"
            if sold_on:
                detail += f" on {sold_on}"
            logger.warning(
                "serials: attempt to re-sell %s (sold on invoice_id=%s)",
                code,
                row.sales_invoice_id,
            )
            raise HTTPException(status_code=400, detail=detail)
        return row

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_for_items(
        self,
        validated_items: list[tuple],
        *,
        voucher_type: str,
        company_id: int | None,
        invoice_id: int | None,
    ) -> None:
        """Reject any serial problem on *validated_items* before anything is written.

        *validated_items* is the ``(item_schema, product, quantity_decimal)``
        sequence returned by :meth:`InvoiceProcessor.validate_items`.  Rows
        already attached to *invoice_id* are treated as belonging to this
        invoice, so re-saving an edit does not collide with itself.
        """
        seen: dict[str, str] = {}
        lines: list[tuple[Product, list[str]]] = []
        tracked_product_ids: set[int] = set()

        for item_schema, product, quantity_value in validated_items:
            codes = self._codes_for(item_schema)

            if not product.track_serials:
                if codes:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"{product.name} is not serial-tracked — "
                            "remove the serial numbers from this line"
                        ),
                    )
                continue

            if product.id in tracked_product_ids:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{product.name} is serial-tracked and can only appear "
                        "on one line per invoice"
                    ),
                )
            tracked_product_ids.add(product.id)

            if quantity_value != quantity_value.to_integral_value():
                raise HTTPException(
                    status_code=400,
                    detail=f"{product.name} is serial-tracked, so its quantity must be a whole number",
                )

            required = int(quantity_value)
            if len(codes) != required:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{product.name} needs {required} serial "
                        f"number{'' if required == 1 else 's'} for quantity "
                        f"{required} ({len(codes)} provided)"
                    ),
                )

            for code in codes:
                if code.upper() in seen:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Serial {code} is listed more than once on this invoice",
                    )
                seen[code.upper()] = code

            lines.append((product, codes))

        if not lines:
            return

        existing = self._live_rows(seen.keys(), company_id)
        for product, codes in lines:
            for code in codes:
                row = existing.get(code.upper())
                if voucher_type == "purchase":
                    self._require_registrable(code, row, invoice_id=invoice_id)
                else:
                    self._require_sellable(
                        code, row, product_id=product.id, invoice_id=invoice_id
                    )

    # ------------------------------------------------------------------
    # Row-level state transitions
    # ------------------------------------------------------------------

    def _register(
        self,
        codes: list[str],
        *,
        product_id: int,
        company_id: int | None,
        invoice_id: int | None,
    ) -> None:
        """Receive *codes* as new in-stock units of *product_id*."""
        if not codes:
            return
        if company_id is None:
            raise HTTPException(
                status_code=400,
                detail="Serial numbers cannot be registered without an active company",
            )
        existing = self._live_rows(codes, company_id)
        for code in codes:
            self._require_registrable(code, existing.get(code.upper()), invoice_id=invoice_id)
            self.db.add(
                ProductSerial(
                    company_id=company_id,
                    product_id=product_id,
                    serial_number=code,
                    status=STATUS_IN_STOCK,
                    purchase_invoice_id=invoice_id,
                )
            )
        self.db.flush()
        logger.debug(
            "serials: registered %s unit(s) of product_id=%s on invoice_id=%s",
            len(codes),
            product_id,
            invoice_id,
        )

    def _consume(
        self,
        codes: list[str],
        *,
        product_id: int,
        company_id: int | None,
        invoice_id: int | None,
    ) -> None:
        """Send *codes* out on *invoice_id*, flipping them ``in_stock`` → ``sold``."""
        if not codes:
            return
        existing = self._live_rows(codes, company_id)
        for code in codes:
            row = self._require_sellable(
                code,
                existing.get(code.upper()),
                product_id=product_id,
                invoice_id=invoice_id,
            )
            row.status = STATUS_SOLD
            row.sales_invoice_id = invoice_id
        self.db.flush()
        logger.debug(
            "serials: consumed %s unit(s) of product_id=%s on invoice_id=%s",
            len(codes),
            product_id,
            invoice_id,
        )

    def _unregister(self, rows: list[ProductSerial]) -> None:
        """Drop *rows* from the purchase that received them, during an edit.

        Deleted rather than voided: ``void`` is reserved for cancellation, so
        that restoring a cancelled purchase resurrects exactly the set that
        cancel voided and not units an earlier edit had already dropped.
        """
        for row in rows:
            if row.status == STATUS_SOLD:
                sold_on = self._invoice_number(row.sales_invoice_id)
                detail = f"Serial {row.serial_number} cannot be removed — it has already been sold"
                if sold_on:
                    detail += f" on {sold_on}"
                raise HTTPException(status_code=400, detail=detail)
            self.db.delete(row)
        if rows:
            self.db.flush()

    def _release(self, rows: list[ProductSerial]) -> None:
        """Put *rows* back in stock, detached from the sale that carried them."""
        for row in rows:
            row.status = STATUS_IN_STOCK
            row.sales_invoice_id = None
        if rows:
            self.db.flush()

    # ------------------------------------------------------------------
    # Invoice-level operations
    # ------------------------------------------------------------------

    def _invoice_rows(
        self, invoice: Invoice, *, include_void: bool
    ) -> list[ProductSerial]:
        """Every serial row pointing at *invoice*, oldest first."""
        pointer = (
            ProductSerial.purchase_invoice_id
            if invoice.voucher_type == "purchase"
            else ProductSerial.sales_invoice_id
        )
        query = self.db.query(ProductSerial).filter(pointer == invoice.id)
        if not include_void:
            query = query.filter(ProductSerial.status != STATUS_VOID)
        return query.order_by(ProductSerial.id.asc()).all()

    def apply_new_items(
        self,
        items: list,
        voucher_type: str,
        *,
        company_id: int | None,
        invoice_id: int | None,
    ) -> None:
        """Apply serial changes for a freshly-created set of line items.

        *items* is a sequence of ``(item_schema, product, quantity_decimal)``
        tuples as returned by :meth:`InvoiceProcessor.validate_items`.  Only
        products with ``track_serials=True`` are touched.
        """
        for item_schema, product, _quantity_value in items:
            if not product.track_serials:
                continue
            codes = self._codes_for(item_schema)
            if voucher_type == "purchase":
                self._register(
                    codes,
                    product_id=product.id,
                    company_id=company_id,
                    invoice_id=invoice_id,
                )
            else:
                self._consume(
                    codes,
                    product_id=product.id,
                    company_id=company_id,
                    invoice_id=invoice_id,
                )

    def apply_invoice_changes(
        self,
        invoice: Invoice,
        payload: InvoiceCreate,
        *,
        company_id: int | None,
    ) -> None:
        """Apply the per-product set-diff of serials when editing an invoice.

        Compares the serials currently attached to *invoice* against the ones in
        *payload* and moves only the difference, so unchanged units keep their
        row — and their history — across a save.
        """
        logger.info(
            "serials: applying set-diff for invoice_id=%s company_id=%s",
            invoice.id,
            company_id,
        )
        existing: dict[int, dict[str, ProductSerial]] = {}
        for row in self._invoice_rows(invoice, include_void=False):
            existing.setdefault(row.product_id, {})[row.serial_number.upper()] = row

        incoming: dict[int, dict[str, str]] = {}
        for item in payload.items:
            for code in self._codes_for(item):
                incoming.setdefault(item.product_id, {})[code.upper()] = code

        diffs: list[tuple[int, list[ProductSerial], list[str]]] = []
        for product_id in set(existing) | set(incoming):
            product = self._get_product(
                product_id, company_id, f"editing invoice {invoice.id}"
            )
            # A product whose flag was switched off keeps its rows untouched —
            # the history of what already shipped stays readable.
            if not product.track_serials:
                continue
            current = existing.get(product_id, {})
            wanted = incoming.get(product_id, {})
            removed = [current[key] for key in current.keys() - wanted.keys()]
            added = [wanted[key] for key in wanted.keys() - current.keys()]
            if removed or added:
                diffs.append((product_id, removed, added))

        # Removals first across every product: a unit moved from one line to
        # another has to leave the first before the unique index will take it.
        for _product_id, removed, _added in diffs:
            if invoice.voucher_type == "purchase":
                self._unregister(removed)
            else:
                self._release(removed)

        for product_id, _removed, added in diffs:
            if invoice.voucher_type == "purchase":
                self._register(
                    added,
                    product_id=product_id,
                    company_id=company_id,
                    invoice_id=invoice.id,
                )
            else:
                self._consume(
                    added,
                    product_id=product_id,
                    company_id=company_id,
                    invoice_id=invoice.id,
                )

    def reverse_invoice_serials(self, invoice: Invoice) -> None:
        """Undo the serial effect of *invoice*.  Used when cancelling.

        A cancelled purchase voids the units it brought in, and refuses outright
        if any of them has already gone out to a customer.  A cancelled sale
        puts its units back in stock but *keeps* ``sales_invoice_id`` — it is the
        only record of which handsets went out on this invoice, and both the
        invoice view and :meth:`restore_invoice_serials` read it back.
        """
        logger.info(
            "serials: reversing invoice_id=%s voucher_type=%s",
            invoice.id,
            invoice.voucher_type,
        )
        rows = self._invoice_rows(invoice, include_void=False)
        if not rows:
            return

        if invoice.voucher_type == "purchase":
            for row in rows:
                if row.status == STATUS_SOLD:
                    sold_on = self._invoice_number(row.sales_invoice_id)
                    detail = (
                        f"Serial {row.serial_number} from this purchase has already been sold"
                    )
                    if sold_on:
                        detail += f" on {sold_on}"
                    logger.warning(
                        "serials: refusing to cancel purchase invoice_id=%s — %s is sold",
                        invoice.id,
                        row.serial_number,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=f"{detail}. Cancel that sale first",
                    )
            for row in rows:
                row.status = STATUS_VOID
        else:
            for row in rows:
                if row.status == STATUS_SOLD:
                    row.status = STATUS_IN_STOCK
        self.db.flush()

    def restore_invoice_serials(self, invoice: Invoice, *, company_id: int) -> None:
        """Re-apply the serial effect of a previously-cancelled *invoice*."""
        logger.info(
            "serials: restoring invoice_id=%s company_id=%s",
            invoice.id,
            company_id,
        )
        if invoice.voucher_type == "purchase":
            voided = [
                row
                for row in self._invoice_rows(invoice, include_void=True)
                if row.status == STATUS_VOID
            ]
            for row in voided:
                clash = self._live_row(row.serial_number, company_id)
                if clash is not None:
                    detail = (
                        f"Serial {row.serial_number} has been registered again "
                        "since this purchase was cancelled"
                    )
                    source = self._invoice_number(clash.purchase_invoice_id)
                    if source:
                        detail += f" on {source}"
                    raise HTTPException(
                        status_code=400,
                        detail=f"{detail}. Remove it there before restoring this purchase",
                    )
                row.status = STATUS_IN_STOCK
                # Flush per row so the partial unique index sees each one before
                # the next is checked.
                self.db.flush()
            return

        available: dict[int, list[ProductSerial]] = {}
        for row in self._invoice_rows(invoice, include_void=False):
            if row.status == STATUS_IN_STOCK:
                available.setdefault(row.product_id, []).append(row)

        for item in invoice.items:
            product = self._get_product(
                item.product_id, company_id, f"restoring invoice {invoice.id}"
            )
            if not product.track_serials:
                continue
            rows = available.get(item.product_id, [])
            required = int(Decimal(str(item.quantity)))
            if len(rows) < required:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{product.name} no longer has the {required} serial "
                        f"number{'' if required == 1 else 's'} it was invoiced "
                        "with — they have gone out on another invoice"
                    ),
                )
            for row in rows:
                row.status = STATUS_SOLD
                row.sales_invoice_id = invoice.id
        self.db.flush()

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    def lookup(self, code: str, company_id: int | None) -> ProductSerial | None:
        """Resolve a scanned *code* to its live unit, case-insensitively."""
        normalized = self.normalize(code)
        if not normalized:
            return None
        return self._live_row(normalized, company_id)

    def serials_for_invoices(
        self, invoices: list[Invoice]
    ) -> dict[int, dict[int, list[str]]]:
        """``{invoice_id: {product_id: [serial_number]}}`` for a whole page.

        One query for every invoice on the page — the invoice list would
        otherwise issue one per row.
        """
        wanted = {invoice.id for invoice in invoices if invoice.id is not None}
        if not wanted:
            return {}

        rows = (
            self.db.query(ProductSerial)
            .filter(
                or_(
                    ProductSerial.purchase_invoice_id.in_(wanted),
                    ProductSerial.sales_invoice_id.in_(wanted),
                )
            )
            .order_by(ProductSerial.id.asc())
            .all()
        )

        result: dict[int, dict[int, list[str]]] = {}
        for row in rows:
            for invoice_id in {row.purchase_invoice_id, row.sales_invoice_id} & wanted:
                result.setdefault(invoice_id, {}).setdefault(
                    row.product_id, []
                ).append(row.serial_number)
        return result

    def serials_for_invoice(self, invoice: Invoice) -> dict[int, list[str]]:
        """``{product_id: [serial_number]}`` for a single invoice."""
        return self.serials_for_invoices([invoice]).get(invoice.id, {})

    # ------------------------------------------------------------------
    # Stock-level operations — the flows with no invoice behind them
    # ------------------------------------------------------------------

    @classmethod
    def normalize_codes(cls, values: list[str] | None) -> list[str]:
        """Normalized, blank-free serial numbers from a raw payload list."""
        return [code for code in (cls.normalize(value) for value in values or []) if code]

    def _require_no_duplicates(self, codes: list[str]) -> None:
        """Reject a code listed twice in the same request.

        The partial unique index would catch it on a register, but only at flush
        time as a 500 — and on a write-off or a return it would not catch it at
        all, silently moving one unit where the caller counted two.
        """
        seen: set[str] = set()
        for code in codes:
            if code.upper() in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"Serial {code} is listed more than once",
                )
            seen.add(code.upper())

    def _require_unregistered(self, code: str, row: ProductSerial | None) -> None:
        """Raise 400 unless *code* is free to be taken into stock outside an invoice.

        :meth:`_require_registrable` lets a row through when it already belongs
        to the invoice being saved.  Stock registration has no invoice to match,
        and a ``NULL`` purchase pointer must not read as "the same invoice" —
        that would let opening stock silently adopt somebody else's unit.
        """
        if row is None:
            return
        detail = f"Serial {code} is already registered to {self._product_name(row.product_id)}"
        source = self._invoice_number(row.purchase_invoice_id)
        if source:
            detail += f" on {source}"
        logger.warning(
            "serials: stock registration collision for %s (existing_id=%s status=%s)",
            code,
            row.id,
            row.status,
        )
        raise HTTPException(status_code=400, detail=detail)

    def count_in_stock(self, product_id: int, *, company_id: int | None) -> int:
        """How many units of *product_id* are ``in_stock`` right now."""
        query = self.db.query(func.count(ProductSerial.id)).filter(
            ProductSerial.product_id == product_id,
            ProductSerial.status == STATUS_IN_STOCK,
        )
        return int(self._scoped(query, company_id).scalar() or 0)

    def register_stock(
        self,
        codes: list[str],
        *,
        product_id: int,
        company_id: int | None,
        note: str | None = None,
    ) -> None:
        """Receive *codes* as in-stock units of *product_id* outside any invoice.

        Backs a product's opening stock, the backfill that turns tracking on for
        a product that already has stock, and the positive side of a stock
        adjustment — none of which have a purchase entry to hang the units on.
        """
        if not codes:
            return
        self._require_no_duplicates(codes)
        existing = self._live_rows(codes, company_id)
        for code in codes:
            self._require_unregistered(code, existing.get(code.upper()))
        self._register(
            codes, product_id=product_id, company_id=company_id, invoice_id=None
        )
        if note:
            for row in self._live_rows(codes, company_id).values():
                row.note = note
            self.db.flush()

    def void_stock(
        self,
        codes: list[str],
        *,
        product_id: int,
        company_id: int | None,
        note: str | None = None,
    ) -> None:
        """Write *codes* off stock — the negative side of a stock adjustment.

        Voided rather than deleted: the unit existed, and the write-off with its
        note is the record of where it went.
        """
        if not codes:
            return
        self._require_no_duplicates(codes)
        existing = self._live_rows(codes, company_id)
        for code in codes:
            row = self._require_sellable(
                code, existing.get(code.upper()), product_id=product_id, invoice_id=None
            )
            if row.status != STATUS_IN_STOCK:
                raise HTTPException(
                    status_code=400,
                    detail=f"Serial {code} is not in stock and cannot be written off",
                )
            row.status = STATUS_VOID
            if note:
                row.note = note
        self.db.flush()
        logger.info(
            "serials: wrote off %s unit(s) of product_id=%s",
            len(codes),
            product_id,
        )

    # ------------------------------------------------------------------
    # Credit-note returns
    # ------------------------------------------------------------------

    def apply_credit_note_return(
        self,
        codes: list[str],
        *,
        product_id: int,
        company_id: int | None,
        invoice_id: int | None,
        note: str | None = None,
    ) -> None:
        """Take *codes* back into stock from the sale that carried them.

        Each code must be ``sold`` on *invoice_id* — a customer can only hand
        back the unit that invoice actually went out with.  ``sales_invoice_id``
        is left in place, exactly as on a cancelled sale: it is the only record
        of which handset went out on that invoice, and it is what
        :meth:`reverse_credit_note_return` reads back.
        """
        if not codes:
            return
        self._require_no_duplicates(codes)
        existing = self._live_rows(codes, company_id)
        for code in codes:
            row = existing.get(code.upper())
            if row is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Serial {code} is not a known unit — check the code",
                )
            if row.product_id != product_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Serial {code} is registered to {self._product_name(row.product_id)}",
                )
            if row.status != STATUS_SOLD or row.sales_invoice_id != invoice_id:
                sold_on = self._invoice_number(invoice_id) or f"invoice {invoice_id}"
                logger.warning(
                    "serials: return of %s rejected (status=%s sales_invoice_id=%s wanted=%s)",
                    code,
                    row.status,
                    row.sales_invoice_id,
                    invoice_id,
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Serial {code} did not go out on {sold_on}",
                )
            row.status = STATUS_IN_STOCK
            if note:
                row.note = note
        self.db.flush()
        logger.info(
            "serials: returned %s unit(s) of product_id=%s from invoice_id=%s",
            len(codes),
            product_id,
            invoice_id,
        )

    def apply_credit_note_supplier_return(
        self,
        codes: list[str],
        *,
        product_id: int,
        company_id: int | None,
        invoice_id: int | None,
        note: str | None = None,
    ) -> None:
        """Send *codes* back to the supplier they arrived from.

        Each code must be a unit still in stock that came in on *invoice_id* —
        you cannot return to one supplier what another shipped.  The row is
        voided rather than deleted, exactly as a cancelled purchase does it:
        the unit existed and this note is the record of where it went, and a
        voided row is outside ``ux_product_serials_company_number``, so the
        supplier can ship the same IMEI again later.
        """
        if not codes:
            return
        self._require_no_duplicates(codes)
        existing = self._live_rows(codes, company_id)
        for code in codes:
            row = existing.get(code.upper())
            if row is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Serial {code} is not a known unit — check the code",
                )
            if row.product_id != product_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Serial {code} is registered to {self._product_name(row.product_id)}",
                )
            if row.purchase_invoice_id != invoice_id:
                came_in_on = self._invoice_number(invoice_id) or f"invoice {invoice_id}"
                logger.warning(
                    "serials: supplier return of %s rejected (purchase_invoice_id=%s wanted=%s)",
                    code,
                    row.purchase_invoice_id,
                    invoice_id,
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Serial {code} did not come in on {came_in_on}",
                )
            if row.status != STATUS_IN_STOCK:
                sold_on = self._invoice_number(row.sales_invoice_id)
                detail = f"Serial {code} is no longer in stock"
                if row.status == STATUS_SOLD:
                    detail = f"Serial {code} has already been sold"
                    if sold_on:
                        detail += f" on {sold_on}"
                    detail += ". Cancel that sale before returning it to the supplier"
                raise HTTPException(status_code=400, detail=detail)
            row.status = STATUS_VOID
            if note:
                row.note = note
            # Flush per row so the partial unique index sees each void before
            # the next code is looked up.
            self.db.flush()
        logger.info(
            "serials: returned %s unit(s) of product_id=%s to the supplier on invoice_id=%s",
            len(codes),
            product_id,
            invoice_id,
        )

    def reverse_credit_note_supplier_return(
        self,
        *,
        product_id: int,
        company_id: int | None,
        invoice_id: int | None,
        note: str,
        quantity: int,
    ) -> None:
        """Bring back the units a cancelled purchase return sent out.

        Found by the *note* the return stamped on them rather than by product
        alone, so cancelling one of several returns against the same purchase
        restores exactly the units that return carried.
        """
        if quantity <= 0:
            return
        query = self.db.query(ProductSerial).filter(
            ProductSerial.product_id == product_id,
            ProductSerial.purchase_invoice_id == invoice_id,
            ProductSerial.status == STATUS_VOID,
            ProductSerial.note == note,
        )
        rows = (
            self._scoped(query, company_id)
            .order_by(ProductSerial.id.asc())
            .limit(quantity)
            .all()
        )
        if len(rows) < quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{self._product_name(product_id)} no longer has the {quantity} "
                    f"unit{'' if quantity == 1 else 's'} this credit note returned "
                    "to the supplier"
                ),
            )
        for row in rows:
            clash = self._live_row(row.serial_number, company_id)
            if clash is not None:
                detail = (
                    f"Serial {row.serial_number} has been registered again since "
                    "it was returned to the supplier"
                )
                source = self._invoice_number(clash.purchase_invoice_id)
                if source:
                    detail += f" on {source}"
                raise HTTPException(
                    status_code=400,
                    detail=f"{detail}. Remove it there before cancelling this credit note",
                )
            row.status = STATUS_IN_STOCK
            row.note = None
            # Flush per row so the partial unique index sees each restore
            # before the next is checked.
            self.db.flush()
        logger.info(
            "serials: brought back %s unit(s) of product_id=%s from a cancelled supplier return on invoice_id=%s",
            len(rows),
            product_id,
            invoice_id,
        )

    def reverse_credit_note_return(
        self,
        *,
        product_id: int,
        company_id: int | None,
        invoice_id: int | None,
        note: str,
        quantity: int,
    ) -> None:
        """Send the units a cancelled return brought back out on their sale again.

        The rows are found by the *note* the return stamped on them rather than
        by product alone, so cancelling one of several returns against the same
        invoice sends back exactly the units that return carried — serials are
        not fungible.
        """
        if quantity <= 0:
            return
        query = self.db.query(ProductSerial).filter(
            ProductSerial.product_id == product_id,
            ProductSerial.sales_invoice_id == invoice_id,
            ProductSerial.status == STATUS_IN_STOCK,
            ProductSerial.note == note,
        )
        rows = (
            self._scoped(query, company_id)
            .order_by(ProductSerial.id.asc())
            .limit(quantity)
            .all()
        )
        if len(rows) < quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{self._product_name(product_id)} no longer has the {quantity} "
                    f"returned unit{'' if quantity == 1 else 's'} this credit note "
                    "took back — they have gone out on another invoice"
                ),
            )
        for row in rows:
            row.status = STATUS_SOLD
            row.note = None
        self.db.flush()
        logger.info(
            "serials: reversed the return of %s unit(s) of product_id=%s onto invoice_id=%s",
            len(rows),
            product_id,
            invoice_id,
        )
