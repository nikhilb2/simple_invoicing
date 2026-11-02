from datetime import datetime

from pydantic import BaseModel, field_validator

from src.services.upi import is_valid_vpa, normalize_vpa


ACCOUNT_TYPES = ("bank", "cash")


class CompanyAccountBase(BaseModel):
    account_type: str = "bank"
    display_name: str
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None
    upi_vpa: str | None = None
    display_on_invoice: bool = True
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

    @field_validator("upi_vpa")
    @classmethod
    def validate_upi_vpa(cls, value: str | None) -> str | None:
        # Blank passes through as "" rather than collapsing to None. The update
        # route guards every field with `is not None`, so a client clears a value by
        # sending "" -- turning that into None here would silently make clearing a
        # no-op, which is how the neighbouring string fields already behave.
        if value is None:
            return None
        # normalize_vpa trims but deliberately does not lowercase: UPI delegates
        # resolution of the local part to each PSP's own mapper and no specification
        # says whether that lookup is case sensitive, so the only safe thing to store
        # is exactly what the user typed.
        normalized = normalize_vpa(value)
        if normalized is None:
            return ""
        if not is_valid_vpa(normalized):
            raise ValueError("Enter a valid UPI ID, for example name@bank")
        return normalized

class CompanyAccountCreate(CompanyAccountBase):
    @field_validator("opening_balance")
    @classmethod
    def validate_opening_balance(cls, value: float) -> float:
        if value < 0:
            raise ValueError("opening_balance must be greater than or equal to 0")
        return value


class CompanyAccountUpdate(BaseModel):
    account_type: str | None = None
    display_name: str | None = None
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None
    upi_vpa: str | None = None
    display_on_invoice: bool | None = None
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

    @field_validator("upi_vpa")
    @classmethod
    def validate_upi_vpa(cls, value: str | None) -> str | None:
        # Blank passes through as "" rather than collapsing to None. The update
        # route guards every field with `is not None`, so a client clears a value by
        # sending "" -- turning that into None here would silently make clearing a
        # no-op, which is how the neighbouring string fields already behave.
        if value is None:
            return None
        # normalize_vpa trims but deliberately does not lowercase: UPI delegates
        # resolution of the local part to each PSP's own mapper and no specification
        # says whether that lookup is case sensitive, so the only safe thing to store
        # is exactly what the user typed.
        normalized = normalize_vpa(value)
        if normalized is None:
            return ""
        if not is_valid_vpa(normalized):
            raise ValueError("Enter a valid UPI ID, for example name@bank")
        return normalized

    @field_validator("opening_balance")
    @classmethod
    def validate_opening_balance(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("opening_balance must be greater than or equal to 0")
        return value


class CompanyAccountOut(CompanyAccountBase):
    id: int
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
