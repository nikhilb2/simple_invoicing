from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _FromAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Gstr3bRowComponent(_FromAttributes):
    label: str
    taxable_value: float | None = None
    igst: float
    cgst: float
    sgst: float


class Gstr3bRow(_FromAttributes):
    """One line of the return.

    A ``not_tracked`` row has null figures rather than zeros: zero would read as
    "you have none" when the truth is "your books do not record this".
    """

    key: str
    table: str
    label: str
    source: Literal["from_books", "not_tracked"]
    note: str | None = None
    taxable_value: float | None = None
    igst: float | None = None
    cgst: float | None = None
    sgst: float | None = None
    components: list[Gstr3bRowComponent] = []


class Gstr3bSection(_FromAttributes):
    key: str
    title: str
    note: str | None = None
    rows: list[Gstr3bRow]


class Gstr3bSetOffLine(_FromAttributes):
    head: Literal["igst", "cgst", "sgst"]
    output_tax: float
    input_credit: float
    credit_used: float
    payable: float
    credit_carried_forward: float


class Gstr3bSetOff(_FromAttributes):
    source: Literal["from_books"]
    note: str
    lines: list[Gstr3bSetOffLine]
    total_payable: float
    total_credit_carried_forward: float
    rows: list[Gstr3bRow]


class Gstr3bWarningDocument(_FromAttributes):
    kind: Literal["invoice", "credit_note"]
    id: int
    number: str
    detail: str | None = None


class Gstr3bWarning(_FromAttributes):
    code: str
    severity: Literal["warning", "info"]
    title: str
    message: str
    documents: list[Gstr3bWarningDocument] = []


class Gstr3bWorksheetOut(_FromAttributes):
    title: str
    headline: str
    disclaimer: str
    from_date: date
    to_date: date
    period_type: Literal["month", "quarter"]
    period_label: str
    warnings: list[Gstr3bWarning]
    known_limits: list[str]
    sections: list[Gstr3bSection]
    setoff: Gstr3bSetOff
    table_5_1_note: str
