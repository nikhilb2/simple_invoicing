from datetime import date
from decimal import Decimal

from app_main import app
from src.api.deps import get_current_user
from src.models.tax_withholding_section import TaxWithholdingSection
from src.services.tax_withholding import suggest_withholding


def _section(**overrides):
    values = {
        "kind": "tds", "act": 2025, "section_ref": "393(1) Sl. No. 6(i)", "legacy_code": "194C",
        "nature": "Payment to contractor", "rate_individual_huf": Decimal("1"), "rate_other": Decimal("2"),
        "rate_no_pan": Decimal("20"), "threshold_single": Decimal("30000"), "threshold_aggregate": Decimal("100000"),
        "threshold_note": "per bill / tax year", "base": "taxable", "effective_from": date(2026, 4, 1), "effective_to": None,
    }
    values.update(overrides)
    return TaxWithholdingSection(**values)


def test_tax_sections_switch_on_the_april_2026_boundary(client, db_session):
    db_session.add_all([
        _section(act=1961, section_ref="194C", effective_from=date(2025, 4, 1), effective_to=date(2026, 3, 31)),
        _section(act=2025, effective_from=date(2026, 4, 1)),
    ])
    db_session.commit()
    march = client.get("/api/tax-withholding-sections", params={"kind": "tds", "date": "2026-03-31"})
    april = client.get("/api/tax-withholding-sections", params={"kind": "tds", "date": "2026-04-01"})
    assert march.status_code == 200
    assert [row["act"] for row in march.json()] == [1961]
    assert april.status_code == 200
    assert [row["act"] for row in april.json()] == [2025]


def test_suggest_withholding_uses_party_type_rate_and_rounds_to_paise():
    section = _section()
    assert suggest_withholding(section, 50000, "individual", True) == {"rate": 1.0, "amount": 500.0}
    assert suggest_withholding(section, 50000, "huf", True) == {"rate": 1.0, "amount": 500.0}
    assert suggest_withholding(section, 50000, "company", True) == {"rate": 2.0, "amount": 1000.0}


def test_missing_pan_uses_higher_rate_and_tcs_is_capped_at_twenty_percent():
    tcs = _section(kind="tcs", rate_individual_huf=Decimal("2"), rate_other=Decimal("2"), rate_no_pan=Decimal("25"))
    assert suggest_withholding(tcs, 1000, "company", False) == {"rate": 20.0, "amount": 200.0}


def test_no_pan_tds_uses_section_specific_rate():
    section = _section(rate_no_pan=Decimal("5"))
    assert suggest_withholding(section, 1000, "individual", False) == {"rate": 5.0, "amount": 50.0}


def test_tax_sections_require_sign_in(client):
    current_user_override = app.dependency_overrides.pop(get_current_user)
    try:
        response = client.get("/api/tax-withholding-sections")
    finally:
        app.dependency_overrides[get_current_user] = current_user_override
    assert response.status_code == 401
