from decimal import Decimal, ROUND_HALF_UP


def suggest_withholding(section, base_amount, party_type: str | None, has_pan: bool) -> dict[str, float]:
    """Suggest a withholding rate and amount without preventing user overrides."""
    base = Decimal(str(base_amount))
    if base < 0:
        raise ValueError("Base amount cannot be negative")
    if not has_pan:
        rate = Decimal(str(section.rate_no_pan))
    elif party_type in {"individual", "huf"}:
        rate = Decimal(str(section.rate_individual_huf))
    else:
        rate = Decimal(str(section.rate_other))
    if section.kind == "tcs":
        rate = min(rate, Decimal("20"))
    amount = (base * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"rate": float(rate), "amount": float(amount)}
