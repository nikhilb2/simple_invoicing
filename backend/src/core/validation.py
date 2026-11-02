import re

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[A-Z0-9]{1}Z[A-Z0-9]{1}$")
GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# GST allows an HSN/SAC of 4, 6 or 8 digits only. The GST portal rejects a
# 5- or 7-digit code outright, so accepting one here just moves the failure to
# filing day, where it is much more expensive to fix.
HSN_SAC_REGEX = re.compile(r"^(?:[0-9]{4}|[0-9]{6}|[0-9]{8})$")

# The rate slabs the GSTR-1 HSN summary accepts. A rate that merely rounds to a
# slab — 17.99 for 18 — is rejected along with the rest of the table.
# 40 came in with GST 2.0 on 22 Sep 2025; 12 and 28 stay for older invoices and
# for the items still taxed at them.
GST_RATE_SLABS = (0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 18.0, 28.0, 40.0)

# GSTR-1 takes invoice and note numbers of at most 16 characters, made of
# letters, digits, "-" and "/" (RET191115). One bad number rejects the whole file.
GSTR1_DOCUMENT_NUMBER_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/-]{0,15}$")
GSTR1_DOCUMENT_NUMBER_RULE = 'at most 16 characters, starting with a letter or digit and using only letters, digits, "-" and "/"'

# GST state codes, as they appear at the start of a GSTIN.
GST_STATE_NAMES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "28": "Andhra Pradesh (before division)", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory",
}


def is_valid_gstin_checksum(gstin: str) -> bool:
    """Check the Luhn mod-36 digit of an uppercase, 15-character GSTIN."""
    if len(gstin) != 15 or any(char not in GSTIN_ALPHABET for char in gstin):
        return False

    total = 0
    for index, char in enumerate(reversed(gstin[:-1])):
        factor = 2 if index % 2 == 0 else 1
        product = GSTIN_ALPHABET.index(char) * factor
        total += product // 36 + product % 36

    check_digit = GSTIN_ALPHABET[(36 - total % 36) % 36]
    return gstin[-1] == check_digit


def normalize_gstin_format(value: str | None) -> str | None:
    """Normalize the existing format, including when reading legacy records."""
    if value is None:
        return None

    normalized = value.strip().upper()
    if not normalized:
        return None

    if not GSTIN_REGEX.fullmatch(normalized):
        raise ValueError("Invalid GSTIN format. Expected 15-character GSTIN, e.g. 27ABCDE1234F1Z0")

    return normalized


def normalize_gstin(value: str | None) -> str | None:
    """Normalize a submitted GSTIN and validate its state code and check digit."""
    normalized = normalize_gstin_format(value)
    if normalized is None:
        return None

    state_code = int(normalized[:2])
    if not (1 <= state_code <= 38 or state_code in (97, 99)):
        raise ValueError("Invalid GSTIN state code. Expected 01-38, 97 or 99")
    if not is_valid_gstin_checksum(normalized):
        raise ValueError("Invalid GSTIN checksum. Check the 15th character")

    return normalized


def normalize_hsn_sac(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if not HSN_SAC_REGEX.fullmatch(normalized):
        raise ValueError("HSN/SAC must be 4, 6 or 8 digits")

    return normalized


def normalize_place_of_supply(value: str | None) -> str | None:
    """Normalize a place of supply to its two-digit GST state code."""
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if not is_place_of_supply(normalized):
        raise ValueError("Place of supply must be a two-digit GST state code: 01-38 or 97")

    return normalized


def is_place_of_supply(code: str | None) -> bool:
    """Whether a state code can be a place of supply. 99 starts some GSTINs but cannot."""
    return bool(code) and code.isdigit() and len(code) == 2 and (1 <= int(code) <= 38 or code == "97")


def is_gstr1_document_number(number: str | None) -> bool:
    """Whether GSTR-1 accepts this as an invoice or credit note number."""
    return bool(number) and GSTR1_DOCUMENT_NUMBER_REGEX.fullmatch(number) is not None


def is_gst_rate_slab(rate: float | None) -> bool:
    """Whether a GST rate is one of the slabs the GST portal accepts."""
    if rate is None:
        return False
    return any(abs(float(rate) - slab) < 0.001 for slab in GST_RATE_SLABS)
