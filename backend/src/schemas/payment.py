from datetime import datetime
from pydantic import BaseModel, field_validator
from typing import List, Optional


class PaymentCreate(BaseModel):
    ledger_id: int
    voucher_type: str  # "receipt" or "payment"
    amount: float
    date: datetime | None = None
    mode: str | None = None
    reference: str | None = None
    notes: str | None = None

    @field_validator("voucher_type")
    @classmethod
    def validate_voucher_type(cls, value: str) -> str:
        if value not in ("receipt", "payment"):
            raise ValueError("voucher_type must be 'receipt' or 'payment'")
        return value

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("amount must be greater than 0")
        return value


class PaymentOut(BaseModel):
    id: int
    ledger_id: int
    voucher_type: str
    amount: float
    date: datetime
    payment_number: str | None = None
    mode: str | None = None
    reference: str | None = None
    notes: str | None = None
    financial_year_id: Optional[int] = None
    warnings: List[str] = []
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True
