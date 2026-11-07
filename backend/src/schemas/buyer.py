from pydantic import BaseModel, field_validator, model_validator

from src.core.validation import normalize_gstin, normalize_gstin_format, normalize_pan, pan_from_gstin


class BuyerCreate(BaseModel):
    name: str
    address: str
    gst: str | None = None
    pan: str | None = None
    party_type: str | None = None
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

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, value: str | None) -> str | None:
        return normalize_pan(value)

    @field_validator("party_type")
    @classmethod
    def validate_party_type(cls, value: str | None) -> str | None:
        if value is not None and value not in {"individual", "huf", "company", "firm", "other"}:
            raise ValueError("Party type must be individual, huf, company, firm or other")
        return value

    @model_validator(mode="after")
    def derive_pan_from_gstin(self):
        if not self.pan:
            self.pan = pan_from_gstin(self.gst)
        return self


class BuyerOut(BaseModel):
    id: int
    name: str
    address: str
    gst: str = ""
    pan: str | None = None
    party_type: str | None = None
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
        normalized = normalize_gstin_format(value)
        return normalized or ""

    class Config:
        from_attributes = True
