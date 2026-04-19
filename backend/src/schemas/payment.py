from datetime import datetime
from pydantic import BaseModel, field_validator, model_validator
from typing import List, Optional


PAYMENT_VOUCHER_TYPES = ("receipt", "payment", "opening_balance")


class PaymentUpdate(BaseModel):
    voucher_type: str
    amount: float
    account_id: int | None = None
    date: datetime | None = None
    mode: str | None = None
    reference: str | None = None
    notes: str | None = None

    @field_validator("voucher_type")
    @classmethod
    def validate_voucher_type(cls, value: str) -> str:
        if value not in PAYMENT_VOUCHER_TYPES:
            raise ValueError("voucher_type must be 'receipt', 'payment' or 'opening_balance'")
        return value

    @model_validator(mode="after")
    @classmethod
    def validate_amount(cls, values: "PaymentUpdate") -> "PaymentUpdate":
        if values.voucher_type == "opening_balance":
            if values.amount == 0:
                raise ValueError("amount must be non-zero for opening_balance")
            return values

        if values.amount <= 0:
            raise ValueError("amount must be greater than 0")
        return values


class PaymentCreate(BaseModel):
    ledger_id: int | None = None
    voucher_type: str  # "receipt", "payment" or "opening_balance"
    amount: float
    account_id: int | None = None
    date: datetime | None = None
    mode: str | None = None
    reference: str | None = None
    notes: str | None = None

    @field_validator("voucher_type")
    @classmethod
    def validate_voucher_type(cls, value: str) -> str:
        if value not in PAYMENT_VOUCHER_TYPES:
            raise ValueError("voucher_type must be 'receipt', 'payment' or 'opening_balance'")
        return value

    @model_validator(mode="after")
    @classmethod
    def validate_amount(cls, values: "PaymentCreate") -> "PaymentCreate":
        if values.voucher_type == "opening_balance":
            if values.amount == 0:
                raise ValueError("amount must be non-zero for opening_balance")
            return values

        if values.amount <= 0:
            raise ValueError("amount must be greater than 0")
        return values


class PaymentOut(BaseModel):
    id: int
    ledger_id: int | None = None
    voucher_type: str
    amount: float
    account_id: int | None = None
    account_display_name: str | None = None
    account_type: str | None = None
    date: datetime
    payment_number: str | None = None
    mode: str | None = None
    reference: str | None = None
    notes: str | None = None
    financial_year_id: Optional[int] = None
    status: str = "active"
    warnings: List[str] = []
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True
