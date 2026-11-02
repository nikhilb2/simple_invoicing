"""Database-free coverage for the GST input-credit set-off (r.88A, s.49-49B)."""

from itertools import product

import pytest

from src.services.gst_returns.setoff import HEADS, compute_setoff


def run(out, inp):
    return compute_setoff(
        dict(zip(HEADS, out)),
        dict(zip(HEADS, inp)),
    )


def assert_balanced(result):
    """Every head: liability less credit used is what is payable."""
    for head in HEADS:
        h = getattr(result, head)
        liability = max(0.0, h.output_tax) + max(0.0, -h.input_credit)
        assert liability - h.credit_used == pytest.approx(h.payable)
        assert h.payable >= -1e-9
        assert h.credit_carried_forward >= -1e-9
    credit = sum(
        max(0.0, getattr(result, h).input_credit) + max(0.0, -getattr(result, h).output_tax)
        for h in HEADS
    )
    used = sum(getattr(result, h).credit_used for h in HEADS)
    carried = sum(getattr(result, h).credit_carried_forward for h in HEADS)
    assert used + carried == pytest.approx(credit)


# Argument order everywhere: (cgst, sgst, igst).


def test_igst_credit_pays_sgst_when_cgst_credit_covers_cgst():
    """The reported defect: nothing may be stranded, nothing is due."""
    r = run(out=(100, 100, 0), inp=(100, 0, 100))
    assert r.cgst.credit_used == 100 and r.cgst.payable == 0
    assert r.sgst.credit_used == 100 and r.sgst.payable == 0
    assert r.igst.credit_used == 0
    assert sum(getattr(r, h).credit_carried_forward for h in HEADS) == 0
    assert_balanced(r)


def test_output_igst_only_is_paid_by_every_head():
    r = run(out=(0, 0, 300), inp=(100, 80, 50))
    assert r.igst.credit_used == 230
    assert r.igst.payable == 70
    assert r.cgst.credit_carried_forward == 0
    assert r.sgst.credit_carried_forward == 0
    assert_balanced(r)


def test_igst_credit_pays_igst_before_other_heads():
    r = run(out=(50, 50, 30), inp=(0, 0, 100))
    assert r.igst.payable == 0
    assert r.igst.credit_used == 30
    assert r.cgst.credit_used + r.sgst.credit_used == 70
    assert r.cgst.payable + r.sgst.payable == 30
    assert_balanced(r)


def test_credit_in_one_head_only():
    r = run(out=(0, 100, 0), inp=(100, 0, 0))  # CGST credit cannot pay SGST
    assert r.sgst.payable == 100
    assert r.cgst.credit_carried_forward == 100
    r = run(out=(100, 0, 0), inp=(0, 100, 0))  # nor the other way round
    assert r.cgst.payable == 100
    assert r.sgst.credit_carried_forward == 100
    r = run(out=(0, 0, 100), inp=(100, 0, 0))  # but CGST credit can pay IGST
    assert r.igst.payable == 0
    assert_balanced(r)


def test_surplus_credit_carries_forward():
    r = run(out=(10, 10, 10), inp=(40, 25, 60))
    assert sum(getattr(r, h).payable for h in HEADS) == 0
    assert sum(getattr(r, h).credit_carried_forward for h in HEADS) == 125 - 30
    assert_balanced(r)


def test_input_surplus_with_no_output():
    r = run(out=(0, 0, 0), inp=(5, 6, 7))
    assert [getattr(r, h).credit_carried_forward for h in HEADS] == [5, 6, 7]
    assert_balanced(r)


def test_negative_output_becomes_credit():
    """Credit notes beyond the output turn that head into spendable credit."""
    r = run(out=(-40, 0, 0), inp=(0, 0, 0))
    assert r.cgst.credit_carried_forward == 40
    assert r.cgst.payable == 0
    # ...which can then pay IGST, not SGST.
    r = run(out=(-40, 30, 30), inp=(0, 0, 0))
    assert r.igst.payable == 0
    assert r.sgst.payable == 30
    assert r.cgst.credit_carried_forward == 10
    assert_balanced(r)


def test_negative_input_becomes_liability():
    """Input reversed beyond what was claimed is owed, and IGST credit can pay it."""
    r = run(out=(0, 0, 0), inp=(-25, 0, 40))
    assert r.cgst.payable == 0
    assert r.cgst.credit_used == 25
    assert r.igst.credit_carried_forward == 15
    r = run(out=(0, 0, 0), inp=(-25, 0, 0))
    assert r.cgst.payable == 25
    assert_balanced(r)


def test_missing_keys_count_as_zero():
    r = compute_setoff({"igst": 10}, {"cgst": 10})
    assert r.igst.payable == 0
    assert r.cgst.credit_used == 0


def test_issue_81_free_gst_billing_software_example():
    """CGST/SGST credit 360 each against 810 IGST leaves 90 to pay (their issue #81)."""
    r = run(out=(0, 0, 810), inp=(360, 360, 0))
    assert r.igst.credit_used == 720
    assert r.igst.payable == 90
    assert_balanced(r)


def _min_cash_by_brute_force(liab, cred):
    """Lowest cash over every allocation the rule allows.

    Deliberately looser than the implementation: own-head-first is not forced,
    only that IGST credit clears IGST first, CGST/SGST credit reaches IGST
    once IGST credit is fully spent, and CGST and SGST never meet.
    """
    lc, ls, li = liab
    cc, cs, ci = cred
    best = None
    for ii, ic, is_ in product(range(ci + 1), repeat=3):
        # r.88A: IGST credit must clear IGST before it goes anywhere else.
        if ii != min(ci, li) or ii + ic + is_ > ci or ic > lc or is_ > ls:
            continue
        for cc_c, cc_i in product(range(cc + 1), range(cc + 1)):
            if cc_c + cc_i > cc or ic + cc_c > lc:
                continue
            for ss_s, ss_i in product(range(cs + 1), range(cs + 1)):
                if ss_s + ss_i > cs or is_ + ss_s > ls:
                    continue
                if ii + cc_i + ss_i > li:
                    continue
                if (cc_i or ss_i) and ii + ic + is_ != ci:
                    continue
                cash = (lc - ic - cc_c) + (ls - is_ - ss_s) + (li - ii - cc_i - ss_i)
                best = cash if best is None else min(best, cash)
    return best


def test_no_legal_allocation_beats_the_result():
    values = range(4)
    checked = 0
    for lc, ls, li, cc, cs, ci in product(values, repeat=6):
        r = run(out=(lc, ls, li), inp=(cc, cs, ci))
        cash = sum(getattr(r, h).payable for h in HEADS)
        assert cash == _min_cash_by_brute_force((lc, ls, li), (cc, cs, ci)), (
            (lc, ls, li),
            (cc, cs, ci),
        )
        assert_balanced(r)
        checked += 1
    assert checked == 4096
