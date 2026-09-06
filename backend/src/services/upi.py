"""UPI payment links and QR codes.

Deliberately pure: no ``Session``, no HTML, no import from ``pdf_templates``. That is
what lets ``share_documents``, ``public_share`` and ``email`` all import it without
cycle risk -- ``share_documents`` already works around one circular import and must
not acquire a second.

What this builds is an *unsigned* UPI intent. The ``sign`` mechanism in NPCI's spec
needs an RSA keypair registered with an acquiring bank, which a self-hosted invoicing
app does not have, so these links carry no signature -- the same thing every
non-gateway invoicing tool ships.

Nothing here can tell you whether a payment happened. A UPI push settles bank to
bank: there is no order, no merchant id and no acquirer, so there is nothing for
anyone to call back about. Invoices are still closed by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Sequence
from urllib.parse import quote, urlencode

import segno

from src.core.config import settings

# UPI settles INR and nothing else -- `cu` has exactly one legal value.
UPI_CURRENCY = "INR"

# The P2P per-transaction ceiling, which is what a personal or P2PM virtual address
# is subject to. The higher P2M limits (up to Rs 5 lakh under NPCI OC-185B) require
# "Verified Merchant" status obtained through an acquiring bank, which the people
# pasting a VPA into this app's settings will not have. Offering a QR above this
# only produces a decline in the payer's app, which is worse than offering nothing.
UPI_MAX_TXN_AMOUNT = Decimal("100000.00")

# A typo-catcher, not an authority. Four things most published UPI regexes get wrong
# and this one does not:
#
#   * the local part may be entirely numeric and start with a digit -- mobile-number
#     addresses are first-class;
#   * the handle may contain dots (`@ok.axis`, and SEBI's mandated `@valid*` family);
#   * case is permitted, and whether it is *significant* is undocumented, because
#     resolving the local part is delegated to each PSP's own mapper;
#   * the hyphen is last in every character class. Chromium's widely-copied version
#     writes `[\w.+-_]`, where `+-_` silently parses as the range U+002B-U+005F and
#     admits `@ / : ; < = > ? [ \ ] ^`.
#
# There is deliberately no allowlist of handles. Around 700 banks are live, NPCI
# allots handles on rolling application with no published enumeration, and the 2024
# Paytm Payments Bank migration would have broken any list shipped the year before.
UPI_VPA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_]{0,98}@[A-Za-z][A-Za-z0-9.\-]{1,63}$")

# 255 on the wire, but RazorpayX and Cashfree Payouts both cap at 100, so anything
# longer is unusable in practice even though the switch would carry it.
UPI_VPA_MAX_LENGTH = 100

# `tr` is not a soft limit. NPCI OC-193/2023-24 mandates 35-character alphanumeric
# transaction references, and a follow-up effective 1 Feb 2025 declines any
# transaction whose reference carries a special character.
_TR_MAX_LENGTH = 35
_TN_MAX_LENGTH = 50
_PN_MAX_LENGTH = 50

_TR_STRIP_RE = re.compile(r"[^A-Za-z0-9]")
_TN_STRIP_RE = re.compile(r"[^A-Za-z0-9 ]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_vpa(raw: str | None) -> str | None:
    """Trim a virtual payment address, mapping blank to ``None``.

    Deliberately does NOT lowercase. UPI resolves the local part through the PSP's
    own mapper and no specification says whether that lookup is case sensitive, so
    the only safe thing to send is exactly what the user typed. Lowercase separately
    if you ever need to compare two addresses.
    """
    if raw is None:
        return None
    trimmed = raw.strip()
    return trimmed or None


def is_valid_vpa(raw: str | None) -> bool:
    value = normalize_vpa(raw)
    if value is None or len(value) > UPI_VPA_MAX_LENGTH:
        return False
    return bool(UPI_VPA_RE.match(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_decimal(value: Decimal | float | int | str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        # str() first: Decimal(float) carries the float's binary error into the
        # amount, and `am` is the number the customer is about to be charged.
        return _money(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def format_amount(amount: Decimal) -> str:
    """``1234.50`` -- what `am` takes.

    Never `_fmt_currency`, which renders a human-facing string with a symbol and
    thousands separators. A grouped amount in `am` is a broken link.
    """
    return format(_money(amount), "f")


def _clean_payee_name(raw: str | None) -> str:
    # Printable ASCII only. A rupee sign or a Devanagari company name in `pn`
    # percent-encodes to several bytes per character and pushes the QR version up
    # for a field the payer's app may not even display (see resolve_upi_payment).
    # Whitespace is collapsed AFTER that filtering, so a dropped character does not
    # leave a double space behind it.
    text = "".join(ch for ch in (raw or "") if 32 <= ord(ch) < 127)
    return _WHITESPACE_RE.sub(" ", text).strip()[:_PN_MAX_LENGTH].strip()


def _clean_note(raw: str | None) -> str:
    text = _WHITESPACE_RE.sub(" ", _TN_STRIP_RE.sub(" ", raw or "")).strip()
    return text[:_TN_MAX_LENGTH].strip()


def _clean_ref(raw: str | None) -> str:
    return _TR_STRIP_RE.sub("", raw or "")[:_TR_MAX_LENGTH]


def build_upi_uri(
    *,
    vpa: str,
    payee_name: str,
    amount: Decimal,
    note: str = "",
    ref: str = "",
) -> str:
    """A ``upi://pay?...`` intent for one payment.

    Carries `pa`, `pn`, `am`, `cu` and optionally `tn`/`tr`, and nothing else. The
    spec marks `mode`, `sign` and `orgid` mandatory, but that table is written for
    PSP applications and acquirer-onboarded merchants; every UPI app accepts a bare
    link without them, and a fabricated `mc` or `orgid` is worse than an absent one.

    `mam` is likewise omitted on purpose, and its absence is load-bearing: the spec
    says that with `mam` absent or empty the amount field "should NOT be editable".
    Emitting it would let the payer change what they owe.
    """
    params: list[tuple[str, str]] = [
        ("pn", _clean_payee_name(payee_name)),
        ("am", format_amount(amount)),
        ("cu", UPI_CURRENCY),
    ]
    cleaned_note = _clean_note(note)
    if cleaned_note:
        params.append(("tn", cleaned_note))
    cleaned_ref = _clean_ref(ref)
    if cleaned_ref:
        params.append(("tr", cleaned_ref))

    # quote_via=quote, not the default quote_plus: the spec asks for RFC 3986 percent
    # encoding, so a space is %20 and never "+". And every value must go through it --
    # a raw "&" inside a payee name silently truncates the rest of the link, which is
    # the single most common way a hand-built UPI URL breaks.
    query = urlencode(params, quote_via=quote, safe="")
    # `pa` is appended raw. Every character UPI_VPA_RE admits is unreserved under RFC
    # 3986, so there is nothing to escape -- and an address that would need escaping
    # fails validation long before it reaches here.
    return f"upi://pay?pa={vpa}&{query}"


def build_android_intent_uri(uri: str, fallback_url: str) -> str:
    """The Android ``intent://`` form of a ``upi://pay`` link.

    Chrome on Android resolves this to the system chooser listing every installed UPI
    app. The point of preferring it over the bare scheme is `browser_fallback_url`:
    without one, a device with no UPI app installed is a silent dead end, which is a
    documented failure class inside chat-app webviews -- exactly where a forwarded
    invoice gets opened.

    No ``package=`` is set, so the chooser keeps listing every app rather than pinning
    one. Note the host is ``pay``: ``upi://pay`` has host "pay", so the intent form is
    ``intent://pay?...``, not ``intent://upi/pay?...``.
    """
    _, _, query = uri.partition("upi://pay?")
    return (
        f"intent://pay?{query}#Intent;scheme=upi;"
        f"S.browser_fallback_url={quote(fallback_url, safe='')};end"
    )


@dataclass(frozen=True)
class UpiPaymentRequest:
    """One resolved offer to pay a document by UPI."""

    vpa: str
    payee_name: str
    amount: Decimal
    note: str
    ref: str

    def uri(self) -> str:
        return build_upi_uri(
            vpa=self.vpa,
            payee_name=self.payee_name,
            amount=self.amount,
            note=self.note,
            ref=self.ref,
        )


def resolve_upi_payment(
    *,
    accounts: Sequence | Iterable,
    currency_code: str | None,
    payee_fallback: str | None,
    amount: Decimal | float | int | None,
    note: str = "",
    ref: str = "",
) -> UpiPaymentRequest | None:
    """The single "may this document be paid by UPI, and for how much" decision.

    Every surface asks this and nothing else decides, so a rule added here is a rule
    everywhere. Returns ``None`` -- meaning render no payment block at all -- rather
    than raising, because "this document cannot be paid this way" is the ordinary
    case, not an error.

    `accounts` arrives in the caller's existing display order and the FIRST one
    carrying a usable address wins. Exactly one offer is ever produced: two UPI QRs
    on one document is a mis-payment waiting to happen.

    Note that `payee_name` is not necessarily what the payer will see. Since NPCI
    OC-101A (compliance 30 Jun 2025) UPI apps display only the banking name fetched
    from Validate Address -- "names extracted from QR codes ... should not be
    displayed to the payer" -- so this is a hint to the app, not a label.
    """
    if not settings.UPI_QR_ENABLED:
        return None

    if (currency_code or "").strip().upper() != UPI_CURRENCY:
        return None

    value = _to_decimal(amount)
    if value is None or value <= 0 or value > UPI_MAX_TXN_AMOUNT:
        return None

    for account in accounts or []:
        # Re-validated rather than trusted. The schema validates on write, but a row
        # restored from a backup or written before that validator existed would
        # otherwise produce a QR that fails in the payer's app.
        vpa = normalize_vpa(getattr(account, "upi_vpa", None))
        if vpa is None or not is_valid_vpa(vpa):
            continue

        payee_name = _clean_payee_name(getattr(account, "account_name", None) or payee_fallback)
        if not payee_name:
            # `pn` is effectively mandatory in the wild; a nameless payee reads as
            # a scam to anyone who scans it.
            continue

        return UpiPaymentRequest(
            vpa=vpa,
            payee_name=payee_name,
            amount=value,
            note=_clean_note(note),
            ref=_clean_ref(ref),
        )

    return None


def render_qr_png_data_uri(text: str, *, scale: int = 6, border: int = 4) -> str:
    """A ``data:image/png;base64,...`` QR of `text`.

    Error correction M. Not H: at the ~150 characters a UPI intent runs to, H pushes
    the symbol version up far enough that the modules get too small to scan reliably
    off paper. H is only worth it if a logo is ever overlaid.

    `scale` is module size in pixels and is deliberately generous -- both call sites
    render the result smaller than it is generated, so the browser and WeasyPrint
    downsample a sharp bitmap instead of upscaling a soft one.

    A data URI rather than a served image on purpose: it costs no second request on a
    slow connection, and the public share page's CSP allows `img-src 'self' data:`
    but no third party.
    """
    qr = segno.make(text, error="m", micro=False)
    return qr.png_data_uri(scale=scale, border=border)
