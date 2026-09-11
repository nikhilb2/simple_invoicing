"""The UPI link builder and the one decision every surface asks it."""

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest

from src.core.config import settings
from src.services.upi import (
    UPI_MAX_TXN_AMOUNT,
    build_upi_app_links,
    build_upi_uri,
    format_amount,
    is_valid_vpa,
    normalize_vpa,
    render_qr_png_data_uri,
    resolve_upi_payment,
)


@dataclass
class FakeAccount:
    """Stands in for a CompanyAccount row; the resolver only reads two attributes."""

    upi_vpa: str | None = None
    account_name: str | None = "Acme Traders"


def params(uri: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(uri).query).items()}


# ---------------------------------------------------------------------------
# VPA validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "vpa",
    [
        "acme@okhdfcbank",
        "ACME@OKHDFCBANK",              # case is legal and its significance undocumented
        "9876543210@ybl",               # mobile-number address: all digits, digit-leading
        "gaurav.kumar@okaxis",          # dot in the local part
        "12345@HDFC0000001.ifsc.npci",  # dots in the HANDLE
        "some_name@ptaxis",             # underscore: not in NPCI's set, but real and accepted
        "a-b@paytm",
    ],
)
def test_accepts_real_world_addresses(vpa):
    assert is_valid_vpa(vpa)


@pytest.mark.parametrize(
    "vpa",
    [
        None,
        "",
        "   ",
        "nohandle",
        "@okaxis",
        "acme@",
        "acme@1bank",                   # handle must start with a letter
        "acme name@okaxis",             # space
        "acme&pn=x@okaxis",             # the character that would truncate the link
        "acme+tag@okaxis",              # '+' excluded
        "acme/../@okaxis",
        "a" * 95 + "@okhdfcbank",       # over the 100-character practical cap
    ],
)
def test_rejects_malformed_addresses(vpa):
    assert not is_valid_vpa(vpa)


def test_the_chromium_character_range_bug_is_not_reproduced():
    """`[\\w.+-_]` parses `+-_` as a RANGE and silently admits these."""
    for ch in "@/:;<=>?[\\]^":
        assert not is_valid_vpa(f"ac{ch}me@okaxis"), ch


def test_normalize_trims_but_never_changes_case():
    # Resolution of the local part is delegated to each PSP's mapper and no spec says
    # it is case insensitive, so lowercasing here could break a working address.
    assert normalize_vpa("  Acme@OkAxis  ") == "Acme@OkAxis"
    assert normalize_vpa("   ") is None
    assert normalize_vpa(None) is None


# ---------------------------------------------------------------------------
# Link construction
# ---------------------------------------------------------------------------

def test_amount_is_a_plain_two_decimal_string():
    assert format_amount(Decimal("1234.5")) == "1234.50"
    assert format_amount(Decimal("1234")) == "1234.00"
    assert format_amount(Decimal("0.005")) == "0.01"
    # No grouping and no symbol: `am=1,234.56` or `am=Rs1234.56` is a broken link.
    assert "," not in format_amount(Decimal("1234567.89"))


def test_carries_only_the_parameters_we_mean_to_send():
    uri = build_upi_uri(
        vpa="acme@okhdfcbank", payee_name="Acme Traders",
        amount=Decimal("2500.00"), note="Invoice INV-1", ref="INV-2026/0042",
    )
    assert uri.startswith("upi://pay?pa=acme@okhdfcbank&")
    got = params(uri)
    assert got["pn"] == "Acme Traders"
    assert got["am"] == "2500.00"
    assert got["cu"] == "INR"
    # mam absent is what LOCKS the amount; sending it would make the field editable.
    # The rest are for PSP apps and acquirer-onboarded merchants, and a fabricated
    # value is worse than an absent one.
    for absent in ("mam", "mode", "sign", "orgid", "mc", "mid", "msid", "mtid"):
        assert absent not in got


def test_spaces_percent_encode_rather_than_becoming_plus():
    # urlencode's default quote_plus would emit '+', which is not RFC 3986 and not
    # what the UPI spec asks for.
    uri = build_upi_uri(vpa="acme@ybl", payee_name="Acme Traders", amount=Decimal("1.00"))
    assert "pn=Acme%20Traders" in uri
    assert "+" not in uri


def test_an_ampersand_in_a_value_cannot_truncate_the_link():
    uri = build_upi_uri(
        vpa="acme@ybl", payee_name="Tom & Jerry Ltd", amount=Decimal("10.00"), note="Invoice 1",
    )
    # The single most common way a hand-built UPI link breaks: everything after a raw
    # '&' is silently dropped by the receiving app.
    assert params(uri)["pn"] == "Tom & Jerry Ltd"
    assert params(uri)["am"] == "10.00"


def test_reference_is_stripped_to_bare_alphanumerics_and_capped():
    # NPCI declines a transaction whose reference carries a special character.
    uri = build_upi_uri(vpa="acme@ybl", payee_name="X", amount=Decimal("1.00"), ref="INV-2026/0042")
    assert params(uri)["tr"] == "INV20260042"

    uri = build_upi_uri(vpa="acme@ybl", payee_name="X", amount=Decimal("1.00"), ref="A" * 60)
    assert len(params(uri)["tr"]) == 35


def test_note_and_payee_are_truncated_deterministically():
    uri = build_upi_uri(
        vpa="acme@ybl", payee_name="N" * 90, amount=Decimal("1.00"), note="Invoice " + "x" * 90,
    )
    assert len(params(uri)["pn"]) == 50
    assert len(params(uri)["tn"]) == 50


def test_non_ascii_payee_is_dropped_rather_than_bloating_the_payload():
    uri = build_upi_uri(vpa="acme@ybl", payee_name="Acme ₹ नमस्ते Ltd", amount=Decimal("1.00"))
    assert params(uri)["pn"] == "Acme Ltd"


def test_empty_note_and_ref_are_omitted_not_sent_blank():
    got = params(build_upi_uri(vpa="acme@ybl", payee_name="X", amount=Decimal("1.00")))
    assert "tn" not in got and "tr" not in got


def test_app_links_carry_the_same_payment_under_each_apps_scheme():
    uri = build_upi_uri(
        vpa="acme@okaxis", payee_name="Acme & Sons", amount=Decimal("15000.00"), ref="INV-26/0042"
    )
    built = build_upi_app_links(uri)
    links = {label: href for _, label, href in built}

    # The keys are what the share page finds each app's logo by.
    assert [key for key, _, _ in built] == ["gpay", "phonepe", "paytm"]
    assert list(links) == ["Google Pay", "PhonePe", "Paytm"]
    assert links["Google Pay"].startswith("gpay://upi/pay?pa=acme@okaxis&")
    assert links["PhonePe"].startswith("phonepe://pay?pa=acme@okaxis&")
    assert links["Paytm"].startswith("paytmmp://pay?pa=acme@okaxis&")
    # Only the scheme changes: payee, amount and reference are exactly what the
    # upi:// intent carries, encoding included.
    for href in links.values():
        assert params(href) == params(uri)


def test_app_links_refuse_anything_but_a_upi_pay_intent():
    assert build_upi_app_links("https://evil.example/pay?pa=attacker@okaxis") == ()


# ---------------------------------------------------------------------------
# resolve_upi_payment -- the single gate
# ---------------------------------------------------------------------------

def offer(**kwargs):
    base = dict(
        accounts=[FakeAccount(upi_vpa="acme@okhdfcbank")],
        currency_code="INR",
        payee_fallback="Acme Traders",
        amount=Decimal("500.00"),
        note="Invoice 1",
        ref="INV1",
    )
    base.update(kwargs)
    return resolve_upi_payment(**base)


def test_resolves_when_everything_lines_up():
    payment = offer()
    assert payment is not None
    assert payment.vpa == "acme@okhdfcbank"
    assert payment.amount == Decimal("500.00")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"currency_code": "USD"},        # UPI settles INR only
        {"currency_code": None},
        {"amount": Decimal("0")},        # nothing owed
        {"amount": Decimal("-10")},
        {"amount": None},
        {"accounts": []},
        {"accounts": [FakeAccount(upi_vpa=None)]},
        {"accounts": [FakeAccount(upi_vpa="   ")]},
        {"accounts": [FakeAccount(upi_vpa="not a vpa")]},
        {"accounts": [FakeAccount(upi_vpa="acme@ybl", account_name=None)], "payee_fallback": None},
    ],
)
def test_declines_and_returns_none_rather_than_raising(kwargs):
    assert offer(**kwargs) is None


def test_declines_above_the_per_transaction_ceiling():
    # A personal or P2PM address cannot take more than Rs 1,00,000 in one go, and a
    # QR the payer's app will decline is worse than no QR.
    assert offer(amount=UPI_MAX_TXN_AMOUNT) is not None
    assert offer(amount=UPI_MAX_TXN_AMOUNT + Decimal("0.01")) is None


def test_first_usable_account_wins_and_only_one_offer_is_made():
    payment = offer(
        accounts=[
            FakeAccount(upi_vpa=None),
            FakeAccount(upi_vpa="first@okaxis", account_name="First"),
            FakeAccount(upi_vpa="second@okaxis", account_name="Second"),
        ]
    )
    assert payment.vpa == "first@okaxis"


def test_a_stored_address_that_is_now_invalid_is_skipped_not_rendered():
    # Rows restored from a backup, or written before the schema validator existed.
    payment = offer(
        accounts=[FakeAccount(upi_vpa="broken vpa"), FakeAccount(upi_vpa="good@okaxis")]
    )
    assert payment.vpa == "good@okaxis"


def test_payee_falls_back_to_the_company_when_the_account_has_no_name():
    payment = offer(accounts=[FakeAccount(upi_vpa="acme@ybl", account_name=None)])
    assert payment.payee_name == "Acme Traders"


def test_the_kill_switch_disables_every_offer(monkeypatch):
    monkeypatch.setattr(settings, "UPI_QR_ENABLED", False)
    assert offer() is None


def test_float_amounts_do_not_carry_binary_error_into_the_link():
    payment = offer(amount=0.1 + 0.2)
    assert format_amount(payment.amount) == "0.30"


# ---------------------------------------------------------------------------
# QR rendering
# ---------------------------------------------------------------------------

def test_renders_a_png_data_uri():
    uri = render_qr_png_data_uri("upi://pay?pa=acme@okaxis&pn=Acme&am=1.00&cu=INR")
    assert uri.startswith("data:image/png;base64,")
    # Long enough to be a real symbol rather than an empty placeholder.
    assert len(uri) > 500
