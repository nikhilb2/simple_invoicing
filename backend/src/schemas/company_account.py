from datetime import datetime

from pydantic import BaseModel, field_validator


ACCOUNT_TYPES = ("bank", "cash")


class CompanyAccountBase(BaseModel):
    account_type: str = "bank"
    display_name: str
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None
    opening_balance: float = 0
    is_active: bool = True

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ACCOUNT_TYPES:
            raise ValueError("account_type must be 'bank' or 'cash'")
        return normalized

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name is required")
        return normalized


class CompanyAccountCreate(CompanyAccountBase):
    pass


class CompanyAccountUpdate(BaseModel):
    account_type: str | None = None
    display_name: str | None = None
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None
    opening_balance: float | None = None
    is_active: bool | None = None

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ACCOUNT_TYPES:
            raise ValueError("account_type must be 'bank' or 'cash'")
        return normalized

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name cannot be empty")
        return normalized


class CompanyAccountOut(CompanyAccountBase):
    id: int
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
