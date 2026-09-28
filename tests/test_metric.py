"""The three implementations of the official metric must agree, and the four
consequences the strategy rests on must hold.

Run:  python -m pytest tests/ -q      (or)      python tests/test_metric.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gems.metric import (ALPHA, BETA, FastDTI, dti_literal, dti_numpy,  # noqa: E402
                             elasticity_ratio, harmonic_form, kernel,
                             marginal_threshold, neighbourhood,
                             self_financing_distance)


def test_worked_example_from_the_problem_page():
    tp_w, fp_w, fn_w = 3.00, 1.89, 2.00
    value = tp_w / (tp_w + ALPHA * fp_w + BETA * fn_w)
    assert round(value, 2) == 0.60
    assert abs(value - harmonic_form(tp_w, fp_w, tp_w + fn_w)["dti"]) < 1e-12


def test_kernel_support_is_25_cells():
    nb = neighbourhood()
    assert len(nb) == 25, len(nb)
    assert max(abs(dy) for dy, _, _ in nb) == 2
    assert all(0.0 < k <= 1.0 for _, _, k in nb)
    assert kernel(0.0) == 1.0 and kernel(300.0) == 0.0 and kernel(301.0) == 0.0
    assert abs(kernel(150.0) - 0.5) < 1e-12


def _random_case(seed):
    rng = np.random.default_rng(seed)
    h, w = 28, 32
    truth = rng.random((h, w)) < 0.08
    mask = rng.random((h, w)) < 0.15
    valid = rng.random((h, w)) < 0.9
    pred = (rng.random((h, w)) < 0.2) * rng.random((h, w))
    return pred, truth, mask, valid


def test_three_implementations_agree():
    for seed in range(4):
        pred, truth, mask, valid = _random_case(seed)
        a = dti_numpy(pred, truth, mask=mask, valid=valid)
        b = FastDTI(truth, mask=mask, valid=valid)(pred)
        c = dti_literal(pred.tolist(), truth.tolist(),
                        mask_rows=mask.tolist(), valid_rows=valid.tolist())
        assert abs(a["dti"] - c["dti"]) < 1e-9
        assert abs(a["dti"] - b["dti"]) < 1e-5   # fast path is float32


def test_tp_plus_fn_equals_number_of_truth_pixels():
    for seed in range(3):
        pred, truth, mask, valid = _random_case(100 + seed)
        r = dti_numpy(pred, truth, mask=mask, valid=valid)
        assert abs(r["tp_w"] + r["fn_w"] - r["n_truth"]) < 1e-9


def test_marginal_rule_matches_actual_change():
    """The block rule, tested against what the scorer actually does.

    For each candidate block we read the real deltas out of two scorer runs and
    check that the sign of the DTI change matches `pi > alpha * DTI`, where pi is
    the block's own weighted precision.  This is the claim the emission strategy
    is built on, so it is checked numerically rather than asserted.
    """
    truth = np.zeros((40, 40), bool)
    truth[8:12, 8:12] = True
    truth[28:31, 29:33] = True
    valid = np.ones((40, 40), bool)
    base = np.zeros((40, 40), np.float32)
    base[9, 9] = 1.0
    scorer = FastDTI(truth, valid=valid)
    b = scorer(base)
    d0 = b["dti"]
    bar = marginal_threshold(d0)
    assert abs(bar - ALPHA * d0) < 1e-12

    checked = 0
    for (y, x) in [(10, 10), (30, 30), (0, 0), (20, 20), (7, 7), (12, 12),
                   (29, 32), (5, 9), (35, 35), (11, 12)]:
        plus = base.copy()
        plus[y, x] = 1.0
        a = scorer(plus)
        dtp = a["tp_w"] - b["tp_w"]
        dfp = a["fp_w"] - b["fp_w"]
        total = dtp + dfp
        if total <= 0:
            continue
        pi = dtp / total
        assert (a["dti"] > d0) == (pi > bar), (y, x, pi, bar, a["dti"], d0)
        checked += 1
    assert checked >= 6, checked


def test_scaling_toward_one_is_monotone():
    truth = np.zeros((30, 30), bool)
    truth[10:13, 5:15] = True
    valid = np.ones((30, 30), bool)
    field = np.zeros((30, 30), np.float32)
    field[9:12, 4:16] = 0.5
    scorer = FastDTI(truth, valid=valid)
    vals = [scorer(field * t)["dti"] for t in (0.1, 0.25, 0.5, 0.75, 1.0)]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))


def test_elasticity_boundary_is_quarter():
    assert elasticity_ratio(0.30, 0.60) > 1.0     # P > R/4
    assert elasticity_ratio(0.10, 0.60) < 1.0     # P < R/4
    assert abs(elasticity_ratio(0.15, 0.60) - 1.0) < 1e-12


def test_self_financing_radius_matches_the_rule():
    for dti in (0.1, 0.2, 0.3168, 0.5):
        r = self_financing_distance(dti)
        assert abs(r - 300.0 * (1.0 - ALPHA * dti)) < 1e-9
    assert 280.0 < self_financing_distance(0.3168) < 282.0


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS %s" % name)
            except AssertionError as exc:
                fails += 1
                print("FAIL %s  %s" % (name, exc))
    raise SystemExit(1 if fails else 0)
