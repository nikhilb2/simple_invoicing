from datetime import date as Date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.models.tax_withholding_section import TaxWithholdingSection
from src.schemas.tax_withholding import TaxWithholdingSectionOut

router = APIRouter()


@router.get("/tax-withholding-sections", response_model=list[TaxWithholdingSectionOut])
def list_tax_withholding_sections(
    kind: str = Query("tds", pattern="^(tds|tcs)$"),
    on_date: Date = Query(default_factory=Date.today, alias="date"),
    db: Session = Depends(get_db),
):
    """Return the TDS/TCS sections in force on the requested transaction date."""
    return (
        db.query(TaxWithholdingSection)
        .filter(
            TaxWithholdingSection.kind == kind,
            TaxWithholdingSection.effective_from <= on_date,
            (TaxWithholdingSection.effective_to.is_(None) | (TaxWithholdingSection.effective_to >= on_date)),
        )
        .order_by(TaxWithholdingSection.section_ref, TaxWithholdingSection.nature)
        .all()
    )
