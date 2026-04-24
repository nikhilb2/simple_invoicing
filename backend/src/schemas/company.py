from pydantic import BaseModel, field_validator

from src.core.validation import normalize_gstin


class CompanyProfileBase(BaseModel):
    name: str
    address: str
    gst: str = ""
    phone_number: str = ""
    currency_code: str | None = None
    email: str | None = None
    website: str | None = None
    bank_name: str | None = None
    branch_name: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None


class CompanyProfileUpdate(CompanyProfileBase):
    @field_validator("gst")
    @classmethod
    def validate_gst(cls, value: str) -> str:
        return normalize_gstin(value) or ""


class CompanyProfileOut(CompanyProfileBase):
    id: int

    class Config:
        from_attributes = True


class CompanyListItem(BaseModel):
    id: int
    name: str
    gst: str = ""
    currency_code: str | None = None
    is_active: bool = False

    class Config:
        from_attributes = True


class CompanySelectOut(BaseModel):
    active_company_id: int