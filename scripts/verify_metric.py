#!/usr/bin/env python
"""Audit the scoring rule before trusting any model result.

Checks, in order:

  A. the transcription reproduces the problem page's own worked example
     (TP_w 3.00, FP_w 1.89, FN_w 2.00 -> 0.60);
  B. three independent implementations agree (vectorised, literal loop, fast
     sweep scorer);
  C. TP_w + FN_w = |G| exactly, which is what licenses the algebraic reduction;
  D. the reduction DTI = 1/(beta/R_w + alpha/P_w) -- a weighted harmonic mean of
     weighted recall (weight 0.8) and weighted precision (weight 0.2);
  E. the marginal-block rule: a block pays iff its weighted precision exceeds
     alpha * DTI;
  F. monotone scaling: pushing every value toward 1 raises DTI, so the optimum
     is binary;
  G. the elasticity ratio: a relative recall gain beats an equal relative
     precision gain iff P > (alpha/beta) R = R/4.

Writes docs/evidence/metric_audit.json.  Every number printed here is recomputed
on the spot; nothing is copied from a previous session.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.gems.metric import (ALPHA, BETA, FastDTI, dti_literal, dti_numpy,  # noqa: E402
                             elasticity_ratio, harmonic_form, marginal_threshold,
                             self_financing_distance)

OUT = os.path.join(ROOT, "docs", "evidence", "metric_audit.json")


def main() -> int:
    ev = {"alpha": ALPHA, "beta": BETA, "kernel_range_m": 300.0, "pixel_m": 100.0}
    ok = True

    # ---- A. the page's worked example ------------------------------------
    tp_w, fp_w, fn_w = 3.00, 1.89, 2.00
    den = tp_w + ALPHA * fp_w + BETA * fn_w
    value = tp_w / den
    h = harmonic_form(tp_w, fp_w, tp_w + fn_w)
    ev["A_worked_example"] = {
        "stated_by_page": 0.60,
        "denominator": den,
        "denominator_expanded": "3.00 + 0.2*1.89 + 0.8*2.00",
        "computed": value,
        "rounded_2dp": round(value, 2),
        "harmonic_form": h["dti"],
        "recall_w": h["recall_w"], "precision_w": h["precision_w"],
        "matches": round(value, 2) == 0.60 and abs(value - h["dti"]) < 1e-12,
    }
    ok &= ev["A_worked_example"]["matches"]

    # ---- B/C/D on random small rasters ----------------------------------
    rng = np.random.default_rng(7)
    worst_impl = worst_identity = worst_harmonic = 0.0
    for _ in range(8):
        hh, ww = 30, 34
        truth = rng.random((hh, ww)) < 0.07
        mask = rng.random((hh, ww)) < 0.12
        valid = rng.random((hh, ww)) < 0.92
        pred = (rng.random((hh, ww)) < 0.2) * rng.random((hh, ww))
        a = dti_numpy(pred, truth, mask=mask, valid=valid)
        b = FastDTI(truth, mask=mask, valid=valid)(pred)
        c = dti_literal(pred.tolist(), truth.tolist(),
                        mask_rows=mask.tolist(), valid_rows=valid.tolist())
        worst_impl = max(worst_impl, abs(a["dti"] - b["dti"]), abs(a["dti"] - c["dti"]))
        worst_identity = max(worst_identity, abs((a["tp_w"] + a["fn_w"]) - a["n_truth"]))
        hh2 = harmonic_form(a["tp_w"], a["fp_w"], a["n_truth"])
        worst_harmonic = max(worst_harmonic, abs(hh2["dti"] - a["dti"]))
    ev["B_implementations_agree_max_abs_diff"] = worst_impl
    ev["C_tp_plus_fn_equals_ng_max_abs_residual"] = worst_identity
    ev["D_harmonic_reduction_max_abs_residual"] = worst_harmonic
    ev["B_matches"] = worst_impl < 1e-5
    ev["C_matches"] = worst_identity < 1e-9
    ev["D_matches"] = worst_harmonic < 1e-9
    ok &= ev["B_matches"] and ev["C_matches"] and ev["D_matches"]

    # ---- E. marginal-block rule -----------------------------------------
    base_truth = np.zeros((40, 40), bool)
    base_truth[8:12, 8:12] = True
    base_truth[28:31, 29:33] = True
    valid = np.ones((40, 40), bool)
    base_pred = np.zeros((40, 40), np.float32)
    base_pred[9, 9] = 1.0
    base = FastDTI(base_truth, mask=None, valid=valid)(base_pred)
    d0 = base["dti"]
    thr = marginal_threshold(d0)
    trials = []
    # blocks that pay, blocks that do not, and blocks straddling the boundary
    for (yk, xk) in [(10, 10), (30, 30), (35, 35), (0, 0), (20, 20), (11, 12), (29, 32)]:
        block = base_pred.copy()
        block[yk, xk] = 1.0
        after = FastDTI(base_truth, mask=None, valid=valid)(block)
        from src.gems.emit import marginal_precision
        mp = marginal_precision(base_truth, np.zeros_like(base_truth), valid,
                                np.where(block > base_pred, 1.0, 0.0))
        pi = mp["weighted_precision"]
        predicted_pays = pi > thr
        actual_pays = after["dti"] > d0
        trials.append({"pixel": [yk, xk], "block_weighted_precision": pi,
                       "threshold_alpha_times_dti": thr,
                       "rule_says_pays": bool(predicted_pays),
                       "actual_dti_up": bool(actual_pays),
                       "rule_correct": bool(predicted_pays == actual_pays)})
    # a fine sweep over a single added pixel at increasing distance from truth
    sweep = []
    for d in range(0, 5):
        block = base_pred.copy()
        block[9 + d, 9] = 1.0
        after = FastDTI(base_truth, mask=None, valid=valid)(block)
        sweep.append({"distance_px": d, "dti": after["dti"], "dti_up": after["dti"] > d0})
    ev["E_marginal_rule"] = {
        "base_dti": d0,
        "alpha_times_dti": thr,
        "trials": trials,
        "single_pixel_distance_sweep": sweep,
        "all_trials_consistent": all(t["rule_correct"] for t in trials),
        "self_financing_distance_m_at_base": self_financing_distance(d0),
    }
    ok &= ev["E_marginal_rule"]["all_trials_consistent"]

    # ---- F. monotone scaling --------------------------------------------
    truth = np.zeros((30, 30), bool)
    truth[10:13, 5:15] = True
    valid = np.ones((30, 30), bool)
    field = np.zeros((30, 30), np.float32)
    field[9, 4:16] = 0.9
    field[10, 4:16] = 0.8
    field[11, 4:16] = 0.7
    scales, dtis = [], []
    for t in (0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0):
        r = FastDTI(truth, valid=valid)(field * t)
        scales.append(t)
        dtis.append(r["dti"])
    monotone = all(dtis[i] < dtis[i + 1] for i in range(len(dtis) - 1))
    ev["F_scaling_monotone"] = {
        "scales": scales, "dti": dtis, "strictly_increasing": monotone,
        "limit_precision_over_alpha": dtis[-1],
        "note": ("DTI(t) = t*TP_w / (beta|G| + alpha*t*(TP_w+FP_w)) is increasing in "
                 "t; the supremum is P_w/alpha, so the optimum is the binary "
                 "indicator of the support, at value 1."),
    }
    ok &= monotone

    # ---- G. elasticity --------------------------------------------------
    rows = []
    for P, R in [(0.20, 0.60), (0.30, 0.60), (0.15, 0.60), (0.10, 0.50), (0.50, 0.50)]:
        ratio = elasticity_ratio(P, R)
        rows.append({"precision_w": P, "recall_w": R, "ratio": ratio,
                     "recall_gain_wins": bool(ratio > 1.0),
                     "boundary_P_over_R": P / R if R else None,
                     "predicted_wins_iff_P_gt_R_over_4": bool((P > R / 4.0) == (ratio > 1.0))})
    ev["G_elasticity"] = {
        "formula": "(d ln DTI / d ln R) / (d ln DTI / d ln P) = (beta/alpha) * P/R = 4 P/R",
        "rows": rows,
        "all_consistent": all(r["predicted_wins_iff_P_gt_R_over_4"] for r in rows),
    }
    ok &= ev["G_elasticity"]["all_consistent"]

    # ---- strategic constants at observed leaderboard scores --------------
    board = {"leader_2026-09-28": 0.3168, "group_best_reported": 0.1563,
             "boundary_2026-09-14": 0.3049}
    ev["strategic_constants"] = {
        name: {
            "dti": s,
            "marginal_precision_bar": marginal_threshold(s),
            "self_financing_radius_m": self_financing_distance(s),
            "self_financing_radius_px": self_financing_distance(s) / 100.0,
            "recall_penalty_factor_beta": BETA,
            "precision_penalty_factor_alpha": ALPHA,
            "max_affordable_dti_from_precision": 5.0 * 1.0,
        } for name, s in board.items()
    }

    ev["all_checks_pass"] = bool(ok)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(ev, open(OUT, "w"), indent=1)

    print("A worked example              : %.6f -> %.2f  (page says 0.60)  %s"
          % (value, round(value, 2), "OK" if ev["A_worked_example"]["matches"] else "FAIL"))
    print("B implementations agree       : max |diff| %.2e  %s"
          % (worst_impl, "OK" if ev["B_matches"] else "FAIL"))
    print("C TP_w + FN_w = |G|           : max residual %.2e  %s"
          % (worst_identity, "OK" if ev["C_matches"] else "FAIL"))
    print("D harmonic reduction          : max residual %.2e  %s"
          % (worst_harmonic, "OK" if ev["D_matches"] else "FAIL"))
    print("E marginal rule pi > a*DTI    : %s  (bar %.4f at DTI %.4f)"
          % ("OK" if ev["E_marginal_rule"]["all_trials_consistent"] else "FAIL",
             thr, d0))
    print("F scaling monotone to binary  : %s" % ("OK" if monotone else "FAIL"))
    print("G elasticity 4P/R             : %s" % ("OK" if ev["G_elasticity"]["all_consistent"] else "FAIL"))
    for name, r in ev["strategic_constants"].items():
        print("   at DTI %.4f -> emit if local precision > %.4f ; a lone pixel pays out to %.0f m (%.2f px)"
              % (r["dti"], r["marginal_precision_bar"],
                 r["self_financing_radius_m"], r["self_financing_radius_px"]))
    print("\nall_checks_pass = %s ; wrote %s" % (ok, OUT))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
