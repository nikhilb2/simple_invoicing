from sqlalchemy import CheckConstraint, Column, Date, Index, Integer, Numeric, String, UniqueConstraint

from src.db.base import Base


class TaxWithholdingSection(Base):
    __tablename__ = "tax_withholding_sections"
    __table_args__ = (
        UniqueConstraint("kind", "act", "section_ref", "nature", "effective_from", name="uq_tax_withholding_section_version"),
        CheckConstraint("kind IN ('tds', 'tcs')", name="ck_tax_withholding_kind"),
        CheckConstraint("act IN (1961, 2025)", name="ck_tax_withholding_act"),
        CheckConstraint("base IN ('taxable', 'gross')", name="ck_tax_withholding_base"),
        CheckConstraint("rate_individual_huf >= 0 AND rate_other >= 0 AND rate_no_pan >= 0", name="ck_tax_withholding_rates_nonnegative"),
        Index("ix_tax_withholding_sections_lookup", "kind", "effective_from", "effective_to"),
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(3), nullable=False)
    act = Column(Integer, nullable=False)
    section_ref = Column(String(64), nullable=False)
    legacy_code = Column(String(16), nullable=True)
    nature = Column(String(160), nullable=False)
    rate_individual_huf = Column(Numeric(7, 3), nullable=False)
    rate_other = Column(Numeric(7, 3), nullable=False)
    rate_no_pan = Column(Numeric(7, 3), nullable=False)
    threshold_single = Column(Numeric(14, 2), nullable=True)
    threshold_aggregate = Column(Numeric(14, 2), nullable=True)
    threshold_note = Column(String(32), nullable=True)
    base = Column(String(16), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
