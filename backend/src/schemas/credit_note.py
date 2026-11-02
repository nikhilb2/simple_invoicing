from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class CreditNoteItemCreate(BaseModel):
    invoice_id: int
    invoice_item_id: int
    quantity: Optional[int] = Field(default=None, gt=0)
    discount_amount_inclusive: Optional[Decimal] = Field(default=None, gt=0)
    # Which physical units are coming back — required on a return over a
    # serial-tracked product.
    serial_numbers: Optional[List[str]] = None


class CreditNoteCreate(BaseModel):
    ledger_id: int
    invoice_ids: List[int] = Field(..., min_length=1)
    credit_note_type: Literal["return", "discount", "adjustment"] = "return"
    # Outward is one we issued against a sales invoice; inward is the
    # supplier's own note against a purchase. The service checks this against
    # the invoices themselves rather than trusting it.
    direction: Literal["outward", "inward"] = "outward"
    supplier_credit_note_number: Optional[str] = None
    supplier_credit_note_date: Optional[date] = None
    reason: Optional[str] = None
    items: List[CreditNoteItemCreate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_supplier_document(self) -> "CreditNoteCreate":
        number = (self.supplier_credit_note_number or "").strip()
        if self.direction == "inward":
            # We file nothing for an inward note; the supplier's number and
            # date are the whole of its identity against GSTR-2B, so a note
            # without them cannot be reconciled later.
            if not number:
                raise ValueError(
                    "The supplier's credit note number is required on a note received from a supplier"
                )
            if self.supplier_credit_note_date is None:
                raise ValueError(
                    "The supplier's credit note date is required on a note received from a supplier"
                )
            self.supplier_credit_note_number = number
        else:
            if number or self.supplier_credit_note_date is not None:
                raise ValueError(
                    "Supplier credit note details belong only on a note received from a supplier"
                )
            self.supplier_credit_note_number = None
        return self

    @model_validator(mode="after")
    def validate_item_invoice_ids(self) -> "CreditNoteCreate":
        invoice_id_set = set(self.invoice_ids)
        for item in self.items:
            if item.invoice_id not in invoice_id_set:
                raise ValueError(
                    f"Item invoice_id {item.invoice_id} is not in the provided invoice_ids list"
                )

            if self.credit_note_type == "discount":
                if item.discount_amount_inclusive is None:
                    raise ValueError(
                        "discount_amount_inclusive is required for discount credit note items"
                    )
                if item.quantity is not None:
                    raise ValueError("quantity is not allowed for discount credit note items")
            else:
                if item.quantity is None:
                    raise ValueError("quantity is required for return/adjustment credit note items")
                if item.discount_amount_inclusive is not None:
                    raise ValueError(
                        "discount_amount_inclusive is only allowed for discount credit note items"
                    )

            # Only a return moves stock, so only a return can move serials.
            if self.credit_note_type != "return" and item.serial_numbers:
                raise ValueError(
                    "serial_numbers is only allowed for return credit note items"
                )
        return self


class CreditNoteItemOut(BaseModel):
    id: int
    invoice_id: Optional[int] = None
    invoice_item_id: Optional[int] = None
    product_id: Optional[int] = None
    quantity: int
    unit_price: float
    gst_rate: float
    taxable_amount: float
    tax_amount: float
    line_total: float

    class Config:
        from_attributes = True


class CreditNoteOut(BaseModel):
    id: int
    credit_note_number: str
    ledger_id: int
    financial_year_id: Optional[int] = None
    credit_note_type: str
    direction: str = "outward"
    supplier_credit_note_number: Optional[str] = None
    supplier_credit_note_date: Optional[date] = None
    reason: Optional[str] = None
    status: str
    taxable_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    total_amount: float
    created_at: datetime
    cancelled_at: Optional[datetime] = None
    invoice_ids: List[int] = Field(default_factory=list)
    items: List[CreditNoteItemOut] = Field(default_factory=list)

    @field_validator("direction", mode="before")
    @classmethod
    def default_direction(cls, value):
        # Rows written before the column existed carry NULL, and nothing this
        # system issued before then was inward.
        return value or "outward"

    class Config:
        from_attributes = True


class PaginatedCreditNoteOut(BaseModel):
    items: List[CreditNoteOut]
    total: int
    page: int
    page_size: int
    total_pages: int
