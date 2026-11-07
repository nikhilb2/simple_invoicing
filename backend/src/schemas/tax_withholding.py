from datetime import date
from pydantic import BaseModel, ConfigDict


class TaxWithholdingSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    act: int
    section_ref: str
    legacy_code: str | None = None
    nature: str
    rate_individual_huf: float
    rate_other: float
    rate_no_pan: float
    threshold_single: float | None = None
    threshold_aggregate: float | None = None
    threshold_note: str | None = None
    base: str
    effective_from: date
    effective_to: date | None = None
