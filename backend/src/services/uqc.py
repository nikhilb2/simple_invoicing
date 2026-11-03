"""Mapping the product master's free-text unit onto a GST unit quantity code (UQC)."""

# Table 12 of GSTR-1 and the e-way bill both take UQC from a fixed list, so the
# product master's free-text unit has to be mapped onto it. Anything unmapped falls
# back to NOS, which is what every row carried before units were read at all.
HSN_UQC_BY_UNIT = {
    "pieces": "NOS", "piece": "NOS", "pcs": "PCS", "nos": "NOS", "unit": "UNT",
    "kg": "KGS", "kgs": "KGS", "g": "GMS", "gm": "GMS", "gram": "GMS", "grams": "GMS",
    "m": "MTR", "metre": "MTR", "meter": "MTR", "mtr": "MTR",
    "l": "LTR", "litre": "LTR", "liter": "LTR", "ltr": "LTR", "ml": "MLT",
    "box": "BOX", "set": "SET", "pair": "PRS", "dozen": "DOZ", "ton": "TON",
}


def uqc_for_unit(unit: str | None) -> str:
    """The UQC for a product's free-text unit."""
    return HSN_UQC_BY_UNIT.get((unit or "").strip().lower(), "NOS")


def hsn_uqc(hsn: str, unit: str | None) -> str:
    """The UQC to declare for an HSN line of GSTR-1 Table 12."""
    # Services carry no quantity, so the GSTN convention is UQC "NA" with qty 0.
    if hsn.startswith("99"):
        return "NA"
    return uqc_for_unit(unit)
