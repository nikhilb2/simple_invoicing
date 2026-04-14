from pydantic import BaseModel, field_validator

from src.core.validation import normalize_gstin


class BuyerCreate(BaseModel):
    name: str
    address: str
    gst: str | None = None
    phone_number: str
    email: str | None = None
    website: str | None = None
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None

    @field_validator("gst")
    @classmethod
    def validate_gst(cls, value: str | None) -> str | None:
        return normalize_gstin(value)


class BuyerOut(BaseModel):
    id: int
    name: str
    address: str
    gst: str = ""
    phone_number: str
    email: str | None = None
    website: str | None = None
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None

    @field_validator("gst", mode="before")
    @classmethod
    def normalize_gst_output(cls, value: str | None) -> str:
        normalized = normalize_gstin(value)
        return normalized or ""

    class Config:
        from_attributes = True
