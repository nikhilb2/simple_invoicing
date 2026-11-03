"""Set-off of input tax credit against output tax liability.

Pure arithmetic: no database, no FastAPI. Callers pass the output tax and the
input credit for the period per head (CGST, SGST, IGST) and get back what was
spent where, what is still payable in cash and what credit carries forward.

The rule (CGST Act ss.49(5), 49A, 49B; CGST Rules r.88A; CBIC Circular
98/17/2019; the portal's GSTR-3B Table 6.1 guide):

* IGST credit pays IGST first. What is left may pay CGST or SGST, in any order.
* The IGST credit must be completely exhausted before any CGST or SGST credit
  is used, on any head. So IGST credit cannot be left to carry forward while
  CGST or SGST credit is spent.
* CGST credit then pays CGST first; what is left may pay IGST.
* SGST credit likewise pays SGST first, then IGST.
* CGST credit never pays SGST and SGST credit never pays CGST.

Where the rule leaves a choice, this module takes the one that minimises cash
payable. The choice does change the cash due: with output CGST 100, SGST 100
and credit IGST 100, CGST 100, putting the IGST credit on CGST leaves 100 in
cash, putting it on SGST leaves none. IGST credit therefore goes first to the
head whose own credit cannot cover it. Ties settle in a fixed order, IGST
credit to CGST before SGST and surplus CGST credit to IGST before surplus SGST
credit, so results are deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

HEADS = ("cgst", "sgst", "igst")


@dataclass(frozen=True)
class HeadSetOff:
    """Outcome for one tax head.

    `output_tax` and `input_credit` echo the (signed) net amounts passed in.
    `credit_used` is credit, from any head, spent against this head's
    liability. In general payable = max(0, output) + max(0, -input) - credit_used;
    with non-negative nets that is output_tax - credit_used.
    """

    output_tax: float
    input_credit: float
    credit_used: float
    payable: float
    credit_carried_forward: float


@dataclass(frozen=True)
class SetOffResult:
    cgst: HeadSetOff
    sgst: HeadSetOff
    igst: HeadSetOff


def compute_setoff(
    output_tax: Mapping[str, float],
    input_credit: Mapping[str, float],
) -> SetOffResult:
    """Set input credit off against output tax, minimising cash payable.

    Both mappings are keyed "cgst", "sgst", "igst" (missing keys count as 0)
    and hold the net amount for the period, which may be negative: an output
    reversal beyond the output itself becomes credit, and an input reversal
    beyond the input becomes liability. Each head's liability is therefore
    max(0, output) + max(0, -input) and its credit max(0, input) + max(0, -output).
    """
    out = {h: float(output_tax.get(h, 0.0)) for h in HEADS}
    inp = {h: float(input_credit.get(h, 0.0)) for h in HEADS}

    liability = {h: max(0.0, out[h]) + max(0.0, -inp[h]) for h in HEADS}
    credit = {h: max(0.0, inp[h]) + max(0.0, -out[h]) for h in HEADS}
    used = dict.fromkeys(HEADS, 0.0)

    def spend(source: str, target: str, cap: float = float("inf")) -> None:
        amount = min(credit[source], liability[target], cap)
        if amount <= 0:
            return
        credit[source] -= amount
        liability[target] -= amount
        used[target] += amount

    # IGST credit clears IGST first, then must be exhausted before any CGST or
    # SGST credit is used (Circular 98/17/2019).
    spend("igst", "igst")
    # It goes first to the shortfall its head's own credit cannot cover; this
    # is what keeps cash minimal, as own-head credit still pays the rest later.
    spend("igst", "cgst", cap=max(0.0, liability["cgst"] - credit["cgst"]))
    spend("igst", "sgst", cap=max(0.0, liability["sgst"] - credit["sgst"]))
    # Any IGST credit still left pays CGST, then SGST (order is a tie-break).
    spend("igst", "cgst")
    spend("igst", "sgst")
    # Only now may CGST and SGST credit pay their own head, then surplus IGST.
    spend("cgst", "cgst")
    spend("sgst", "sgst")
    spend("cgst", "igst")
    spend("sgst", "igst")

    return SetOffResult(
        **{
            h: HeadSetOff(
                output_tax=out[h],
                input_credit=inp[h],
                credit_used=used[h],
                payable=liability[h],
                credit_carried_forward=credit[h],
            )
            for h in HEADS
        }
    )
