import re

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[A-Z0-9]{1}Z[A-Z0-9]{1}$")
# GST allows an HSN/SAC of 4, 6 or 8 digits only. The GST portal rejects a
# 5- or 7-digit code outright, so accepting one here just moves the failure to
# filing day, where it is much more expensive to fix.
HSN_SAC_REGEX = re.compile(r"^(?:[0-9]{4}|[0-9]{6}|[0-9]{8})$")

# The rate slabs the GSTR-1 HSN summary accepts. A rate that merely rounds to a
# slab — 17.99 for 18 — is rejected along with the rest of the table.
GST_RATE_SLABS = (0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 18.0, 28.0)


def normalize_gstin(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip().upper()
    if not normalized:
        return None

    if not GSTIN_REGEX.fullmatch(normalized):
        raise ValueError("Invalid GSTIN format. Expected 15-character GSTIN, e.g. 27ABCDE1234F1Z5")

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


def is_gst_rate_slab(rate: float | None) -> bool:
    """Whether a GST rate is one of the slabs the GST portal accepts."""
    if rate is None:
        return False
    return any(abs(float(rate) - slab) < 0.001 for slab in GST_RATE_SLABS)
