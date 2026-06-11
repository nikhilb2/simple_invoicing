from pydantic import BaseModel, field_validator

from src.core.validation import normalize_gstin


class CompanyTermOut(BaseModel):
    id: int
    company_id: int
    serial_number: int
    content: str

    class Config:
        from_attributes = True


class CompanyTermCreate(BaseModel):
    content: str


class CompanyTermUpdate(BaseModel):
    content: str


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
    additional_company_info: str | None = None
    show_sku_on_pdf: bool = False


class CompanyProfileUpdate(CompanyProfileBase):
    @field_validator("gst")
    @classmethod
    def validate_gst(cls, value: str) -> str:
        return normalize_gstin(value) or ""


class CompanyProfileOut(CompanyProfileBase):
    id: int
    logo_data: str | None = None
    logo_mime_type: str | None = None
    terms: list[CompanyTermOut] = []

    class Config:
        from_attributes = True


class CompanyProfileOutWithLogo(CompanyProfileOut):
    """Extended output that includes logo as base64 data URI for frontend display."""
    logo_url: str | None = None


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


class CompanyCreationCapOut(BaseModel):
    max_companies: int
    current_companies: int
    can_create_company: bool
