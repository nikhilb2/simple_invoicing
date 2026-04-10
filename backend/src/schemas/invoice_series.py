from datetime import datetime
from pydantic import BaseModel
from typing import Literal, Optional


class InvoiceSeriesOut(BaseModel):
    id: int
    voucher_type: str
    financial_year_id: Optional[int] = None
    prefix: str
    include_year: bool
    year_format: str
    separator: str
    next_sequence: int
    pad_digits: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InvoiceSeriesUpdate(BaseModel):
    prefix: str
    include_year: bool = True
    year_format: Literal["YYYY", "MM-YYYY", "FY"] = "YYYY"
    separator: str = "-"
    pad_digits: Literal[2, 3, 4] = 3
