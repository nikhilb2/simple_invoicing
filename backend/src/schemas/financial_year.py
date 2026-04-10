from datetime import date, datetime
from pydantic import BaseModel
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
