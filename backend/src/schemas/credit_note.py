from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class CreditNoteItemCreate(BaseModel):
    invoice_id: int
    invoice_item_id: int
    quantity: int = Field(..., gt=0)


class CreditNoteCreate(BaseModel):
    ledger_id: int
    invoice_ids: List[int] = Field(..., min_length=1)
    credit_note_type: Literal["return", "discount", "adjustment"] = "return"
    reason: Optional[str] = None
    items: List[CreditNoteItemCreate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_item_invoice_ids(self) -> "CreditNoteCreate":
        invoice_id_set = set(self.invoice_ids)
        for item in self.items:
            if item.invoice_id not in invoice_id_set:
                raise ValueError(
                    f"Item invoice_id {item.invoice_id} is not in the provided invoice_ids list"
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

    class Config:
        from_attributes = True


class PaginatedCreditNoteOut(BaseModel):
    items: List[CreditNoteOut]
    total: int
    page: int
    page_size: int
    total_pages: int
