import pytest
from pydantic import ValidationError

from src.core.validation import (
    is_gst_rate_slab,
    is_valid_gstin_checksum,
    normalize_gstin,
    normalize_hsn_sac,
)
from src.schemas.buyer import BuyerCreate, BuyerOut
from src.schemas.company import CompanyProfileUpdate
from src.schemas.ledger import LedgerCreate, LedgerOut


@pytest.mark.parametrize("value, expected", [
    ("  27abcde1234f1z0  ", "27ABCDE1234F1Z0"),
    ("27AAPFU0939F1ZV", "27AAPFU0939F1ZV"),
    ("29ABCDE1234F1ZW", "29ABCDE1234F1ZW"),
    ("01ABCDE1234F1ZE", "01ABCDE1234F1ZE"),
    ("38ABCDE1234F1ZX", "38ABCDE1234F1ZX"),
    ("97ABCDE1234F1ZT", "97ABCDE1234F1ZT"),
    ("99ABCDE1234F1ZP", "99ABCDE1234F1ZP"),
])
def test_normalize_gstin_valid(value, expected):
    assert normalize_gstin(value) == expected


@pytest.mark.parametrize("gstin", [
    "27ABCDE1234F1Z5",  # The old example has the wrong check digit.
    "27AAPFU0939F1ZO",  # Check-digit typo.
    "27AAPFU0938F1ZV",  # Numeric typo in the PAN.
    "27AAQFU0939F1ZV",  # Alphabetic typo in the PAN.
])
def test_normalize_gstin_invalid_checksum(gstin):
    with pytest.raises(ValueError, match="Invalid GSTIN checksum"):
        normalize_gstin(gstin)


@pytest.mark.parametrize("gstin", [
    "00ABCDE1234F1ZG",
    "39ABCDE1234F1ZV",
    "96ABCDE1234F1ZV",
    "98ABCDE1234F1ZR",
])
def test_normalize_gstin_invalid_state_code(gstin):
    # These check digits are correct: the state-code check must reject them.
    with pytest.raises(ValueError, match="Invalid GSTIN state code"):
        normalize_gstin(gstin)


@pytest.mark.parametrize("schema", [BuyerCreate, LedgerCreate, CompanyProfileUpdate])
@pytest.mark.parametrize("gstin", ["27ABCDE1234F1Z5", "39ABCDE1234F1ZV"])
def test_request_schemas_reject_invalid_gstin(schema, gstin):
    with pytest.raises(ValidationError, match="Invalid GSTIN"):
        schema(name="Test", address="Address", phone_number="", gst=gstin)


@pytest.mark.parametrize("schema", [BuyerCreate, LedgerCreate, CompanyProfileUpdate])
def test_request_schemas_normalize_valid_gstin(schema):
    value = schema(name="Test", address="Address", phone_number="", gst=" 27abcde1234f1z0 ")
    assert value.gst == "27ABCDE1234F1Z0"


@pytest.mark.parametrize("schema", [BuyerOut, LedgerOut])
@pytest.mark.parametrize("gstin", ["27ABCDE1234F1Z5", "00ABCDE1234F1ZG"])
def test_response_schemas_keep_legacy_gstin_readable(schema, gstin):
    # A newly tightened write rule must not prevent reading previously saved rows.
    value = schema(id=1, name="Legacy", address="Address", phone_number="", gst=f" {gstin.lower()} ")
    assert value.gst == gstin


@pytest.mark.parametrize("gstin", ["27AAPFU0939F1ZV", "27ABCDE1234F1Z0", "00ABCDE1234F1ZG"])
def test_is_valid_gstin_checksum(gstin):
    # The checksum helper is independent of the state-code policy.
    assert is_valid_gstin_checksum(gstin) is True


@pytest.mark.parametrize("check_digit", "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
def test_is_valid_gstin_checksum_rejects_every_other_check_digit(check_digit):
    assert is_valid_gstin_checksum(f"27AAPFU0939F1Z{check_digit}") is (check_digit == "V")


@pytest.mark.parametrize("gstin", [
    "", "27AAPFU0939F1Z", "27AAPFU0939F1ZVV", "27aapfu0939f1zv",
    "27AAPFU0939F1Z!", "27AAPFU0939F1Z\u0660", "27AAPFU0939F1ZV\n",
])
def test_is_valid_gstin_checksum_malformed(gstin):
    assert is_valid_gstin_checksum(gstin) is False


def test_normalize_gstin_none():
    assert normalize_gstin(None) is None


def test_normalize_gstin_blank():
    assert normalize_gstin("   ") is None
    assert normalize_gstin("") is None


def test_normalize_gstin_invalid_length():
    with pytest.raises(ValueError, match="Invalid GSTIN format"):
        normalize_gstin("27ABCDE1234F1Z")


def test_normalize_gstin_bad_14th_character():
    # 14th character must be Z
    with pytest.raises(ValueError, match="Invalid GSTIN format"):
        normalize_gstin("27ABCDE1234F1A5")


def test_normalize_hsn_sac_valid_4():
    assert normalize_hsn_sac("1234") == "1234"


def test_normalize_hsn_sac_valid_6():
    assert normalize_hsn_sac("  123456  ") == "123456"


def test_normalize_hsn_sac_valid_8():
    assert normalize_hsn_sac("12345678") == "12345678"


def test_normalize_hsn_sac_none():
    assert normalize_hsn_sac(None) is None


def test_normalize_hsn_sac_blank():
    assert normalize_hsn_sac("   ") is None
    assert normalize_hsn_sac("") is None


def test_normalize_hsn_sac_invalid_5_digits():
    with pytest.raises(ValueError, match="HSN/SAC must be 4, 6 or 8 digits"):
        normalize_hsn_sac("12345")


def test_normalize_hsn_sac_invalid_7_digits():
    with pytest.raises(ValueError, match="HSN/SAC must be 4, 6 or 8 digits"):
        normalize_hsn_sac("1234567")


def test_normalize_hsn_sac_letters():
    with pytest.raises(ValueError, match="HSN/SAC must be 4, 6 or 8 digits"):
        normalize_hsn_sac("ABCD")


def test_is_gst_rate_slab_accepted():
    for slab in (0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 18.0, 28.0):
        assert is_gst_rate_slab(slab) is True
        assert is_gst_rate_slab(float(slab)) is True


def test_is_gst_rate_slab_rejected():
    assert is_gst_rate_slab(17.99) is False
    assert is_gst_rate_slab(None) is False
    assert is_gst_rate_slab(2.0) is False
    assert is_gst_rate_slab(100.0) is False
