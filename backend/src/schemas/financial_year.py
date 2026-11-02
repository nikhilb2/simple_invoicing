from datetime import date, datetime
from pydantic import BaseModel, model_validator, field_validator
from typing import Optional


class FinancialYearOut(BaseModel):
    id: int
    label: str
    start_date: date
    end_date: date
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FinancialYearCreate(BaseModel):
    label: str
    start_date: date
    end_date: date

    @field_validator("label", mode="before")
    @classmethod
    def strip_and_validate_label(cls, value):
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("label must not be blank")
        return value

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self
