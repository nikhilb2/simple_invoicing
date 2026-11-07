import pytest
from pydantic import ValidationError

from src.schemas.company import CompanyProfileUpdate
from src.schemas.ledger import LedgerCreate


def _ledger(**overrides):
    values = {"name": "Supplier", "address": "Mumbai", "gst": None, "phone_number": "9876543210"}
    values.update(overrides)
    return LedgerCreate(**values)


def _company(**overrides):
    values = {"name": "Company", "address": "Mumbai", "gst": "", "phone_number": "", "currency_code": "INR", "email": "", "website": ""}
    values.update(overrides)
    return CompanyProfileUpdate(**values)


def test_ledger_pan_is_derived_from_gstin_when_missing():
    assert _ledger(gst="27ABCDE1234F1Z0").pan == "ABCDE1234F"


def test_ledger_pan_is_normalized_and_party_type_is_preserved():
    ledger = _ledger(pan=" abcde1234f ", party_type="individual")
    assert ledger.pan == "ABCDE1234F"
    assert ledger.party_type == "individual"


@pytest.mark.parametrize("pan", ["ABCDE123F", "ABCDE1234FF", "123451234A", "ABCDE1234!"])
def test_ledger_rejects_invalid_pan(pan):
    with pytest.raises(ValidationError, match="Invalid PAN format"):
        _ledger(pan=pan)


def test_company_pan_is_derived_from_gstin_and_tan_is_normalized():
    company = _company(gst="27ABCDE1234F1Z0", tan="abcd12345e")
    assert company.pan == "ABCDE1234F"
    assert company.tan == "ABCD12345E"


@pytest.mark.parametrize("tan", ["ABCD1234E", "ABCD123456", "123412345E"])
def test_company_rejects_invalid_tan(tan):
    with pytest.raises(ValidationError, match="Invalid TAN format"):
        _company(tan=tan)


def test_party_pan_and_type_are_persisted(db_session):
    from src.models.buyer import Buyer

    party = Buyer(
        name="Supplier",
        address="Mumbai",
        phone_number="9876543210",
        pan="ABCDE1234F",
        party_type="individual",
    )
    db_session.add(party)
    db_session.commit()
    saved = db_session.query(Buyer).filter(Buyer.id == party.id).one()
    assert saved.pan == "ABCDE1234F"
    assert saved.party_type == "individual"


def test_company_pan_and_tan_are_persisted(db_session):
    from src.models.company import CompanyProfile

    company = CompanyProfile(
        name="Company",
        address="Mumbai",
        pan="ABCDE1234F",
        tan="ABCD12345E",
    )
    db_session.add(company)
    db_session.commit()
    saved = db_session.query(CompanyProfile).filter(CompanyProfile.id == company.id).one()
    assert saved.pan == "ABCDE1234F"
    assert saved.tan == "ABCD12345E"
