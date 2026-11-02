"""generate_next_number skips only numbers this company already used, of the same kind.

Numbers are unique per company (uq_*_company_*_number), so another company's
documents must never push a series forward, and a credit note number is
checked against credit_notes -- where it will be stored -- not invoices.
"""

from datetime import date

import pytest

from src.core.config import settings
from src.models.company import CompanyProfile
from src.models.credit_note import CreditNote
from src.models.financial_year import FinancialYear
from src.models.invoice import Invoice
from src.models.invoice_series import InvoiceSeries
from src.services.series import generate_next_number


@pytest.fixture(params=["single_tenant", "shared_hosting"])
def mode(request, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", request.param)
    return request.param


def _company_with_series(db, name: str, voucher_type: str, prefix: str) -> tuple[int, int]:
    company = CompanyProfile(name=name, address="")
    db.add(company)
    db.flush()
    fy = FinancialYear(
        company_id=company.id,
        label="2026-27",
        start_date=date(2026, 4, 1),
        end_date=date(2027, 3, 31),
        is_active=True,
    )
    db.add(fy)
    db.flush()
    db.add(InvoiceSeries(
        company_id=company.id,
        voucher_type=voucher_type,
        financial_year_id=fy.id,
        prefix=prefix,
        suffix="",
        include_year=False,
        year_format="YYYY",
        separator="-",
        next_sequence=1,
        pad_digits=3,
    ))
    db.commit()
    return company.id, fy.id


def _credit_note(db, company_id: int, number: str) -> None:
    db.add(CreditNote(
        credit_note_number=number,
        company_id=company_id,
        ledger_id=1,
        created_by=1,
    ))
    db.commit()


def test_credit_note_already_used_in_the_company_is_skipped(db_session, mode):
    company_id, fy_id = _company_with_series(db_session, "A", "credit_note", "CN")
    _credit_note(db_session, company_id, "CN-001")

    assert generate_next_number(db_session, "credit_note", fy_id, company_id=company_id) == "CN-002"


def test_another_companys_numbers_do_not_advance_the_series(db_session, mode):
    company_a, fy_a = _company_with_series(db_session, "A", "credit_note", "CN")
    company_b, _ = _company_with_series(db_session, "B", "credit_note", "CN")
    _credit_note(db_session, company_b, "CN-001")

    assert generate_next_number(db_session, "credit_note", fy_a, company_id=company_a) == "CN-001"


def test_an_invoice_with_the_same_text_does_not_block_a_credit_note(db_session, mode):
    company_id, fy_id = _company_with_series(db_session, "A", "credit_note", "CN")
    db_session.add(Invoice(invoice_number="CN-001", company_id=company_id, total_amount=0, created_by=1))
    db_session.commit()

    assert generate_next_number(db_session, "credit_note", fy_id, company_id=company_id) == "CN-001"


def test_series_less_fallback_numbers_per_company(db_session, mode):
    company_a = CompanyProfile(name="A", address="")
    company_b = CompanyProfile(name="B", address="")
    db_session.add_all([company_a, company_b])
    db_session.commit()
    db_session.add(Invoice(invoice_number="INV-000000", company_id=company_b.id, total_amount=0, created_by=1))
    db_session.commit()

    assert generate_next_number(db_session, "sales", company_id=company_a.id) == "INV-000000"
    assert generate_next_number(db_session, "sales", company_id=company_b.id) == "INV-000001"


def test_a_company_never_draws_from_a_legacy_shared_series(db_session, mode):
    """Two companies drawing on one counter is what per-company numbering rules out."""
    company = CompanyProfile(name="No Series Co", address="")
    db_session.add(company)
    db_session.flush()
    legacy = InvoiceSeries(
        company_id=None,
        voucher_type="sales",
        financial_year_id=None,
        prefix="SHARED",
        suffix="",
        include_year=False,
        year_format="YYYY",
        separator="-",
        next_sequence=7,
        pad_digits=3,
    )
    db_session.add(legacy)
    db_session.commit()

    number = generate_next_number(db_session, "sales", None, company_id=company.id)

    assert not number.startswith("SHARED")
    db_session.refresh(legacy)
    assert legacy.next_sequence == 7


def test_a_company_uses_its_own_undated_series(db_session, mode):
    company = CompanyProfile(name="Own Series Co", address="")
    db_session.add(company)
    db_session.flush()
    for owner, prefix in ((None, "SHARED"), (company.id, "OWN")):
        db_session.add(InvoiceSeries(
            company_id=owner,
            voucher_type="sales",
            financial_year_id=None,
            prefix=prefix,
            suffix="",
            include_year=False,
            year_format="YYYY",
            separator="-",
            next_sequence=1,
            pad_digits=3,
        ))
    db_session.commit()

    assert generate_next_number(db_session, "sales", None, company_id=company.id) == "OWN-001"
