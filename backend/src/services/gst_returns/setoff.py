"""Set-off of input tax credit against output tax liability.

Pure arithmetic: no database, no FastAPI. Callers pass the output tax and the
input credit for the period per head (CGST, SGST, IGST) and get back what was
spent where, what is still payable in cash and what credit carries forward.

The rule (CGST Act ss.49(5), 49A, 49B; CGST Rules r.88A; the portal's GSTR-3B
Table 6.1 guide):

* IGST credit pays IGST first. What is left may pay CGST or SGST, in any order.
* CGST credit pays CGST first. What is left may pay IGST, and only once the
  IGST credit has been used up.
* SGST credit pays SGST first, then IGST on the same terms.
* CGST credit never pays SGST and SGST credit never pays CGST.

Where the rule leaves a choice, the choice never changes the total cash due,
so this module takes the one that minimises it and settles ties in a fixed
order: IGST credit goes to CGST before SGST, and surplus CGST credit goes to
IGST before surplus SGST credit. That keeps results deterministic.
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

    def spend(source: str, target: str) -> None:
        amount = min(credit[source], liability[target])
        if amount <= 0:
            return
        credit[source] -= amount
        liability[target] -= amount
        used[target] += amount

    # CGST and SGST credit clear their own head first.
    spend("cgst", "cgst")
    spend("sgst", "sgst")
    # IGST credit clears IGST before anything else, so by the time CGST or SGST
    # credit is allowed onto IGST, the IGST credit is already used up or the
    # IGST liability is gone.
    spend("igst", "igst")
    # What is left of IGST credit goes to whichever of CGST and SGST still owes.
    # Order only moves the shortfall between the two, not its total.
    spend("igst", "cgst")
    spend("igst", "sgst")
    # Surplus CGST and SGST credit may pay IGST that IGST credit could not.
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
