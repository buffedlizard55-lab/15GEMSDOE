"""Turn a ranked score field into emitted prediction mass.

The metric dictates the shape of this module.

  * TP_w is a MAX over the 300 m neighbourhood of each truth pixel, so two
    emitted pixels that sit on the same truth pixel earn credit once but are
    both billed in FP_w: redundancy is strictly expensive.  Hence thinning
    (`nms`) and the ability to keep the emitted band narrow (`ridge_width`).

  * A block of predictions pays for itself iff its weighted precision exceeds
    alpha * DTI (proved in docs/METRIC_AUDIT.md and tested in tests/test_metric.py).
    At a competitive DTI near 0.3 that bar is ~0.06, so the best map runs far
    below any calibrated 0.5 cutoff.  `budget_threshold` turns that rule into a
    threshold on a field whose values are interpreted as local precision.

  * Scaling every value up is monotone-improving (proof in docs/METRIC_AUDIT.md),
    so the optimum is binary: emit 1.0 or 0.0.  `binarise` does that, and the
    graded field is used only to rank pixels.

Everything here is pure numpy and operates on the competition grid in place-free
style (each call returns a new array).
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage


def nms_ridge(score: np.ndarray, radius_px: int = 1) -> np.ndarray:
    """Keep only pixels that are the local max of `score` within `radius_px`.

    Thinning operation: it removes the redundant parallel emission that can only
    add false-positive mass, because TP_w credits a truth pixel once.
    """
    if radius_px <= 0:
        return score
    size = 2 * radius_px + 1
    mx = ndimage.maximum_filter(score, size=size, mode="constant")
    return np.where(score >= mx, score, 0.0)


def orient_ridge(score: np.ndarray, ridge_width: int = 1) -> np.ndarray:
    """Grow a thinned line across its normal?  No: narrow it instead.

    Implemented as `nms_ridge` followed by an optional single-pixel dilation when
    `ridge_width > 1`.  Widening past ~1 px is expected to hurt (each extra pixel
    on the same truth cell is pure FP), and the sweep in scripts/tune_emission.py
    measures that rather than assuming it.
    """
    thin = nms_ridge(score, 1)
    if ridge_width <= 1:
        return thin
    grown = thin
    for _ in range(ridge_width - 1):
        grown = ndimage.grey_dilation(grown, size=(3, 3), mode="constant")
    return grown


def binarise(score: np.ndarray, threshold: float) -> np.ndarray:
    return (score > threshold).astype(np.float32)


def budget_thresholds(score: np.ndarray, valid: np.ndarray,
                      areas_px: Sequence[int]) -> Dict[int, float]:
    """One partial sort, many thresholds.

    `budget_threshold` costs a full O(N) partition per call, so sweeping six
    operating areas used to cost six passes.  Partitioning once at all the
    needed orders makes the sweep nearly free, which is what lets the grid be
    wide enough to find an interior optimum instead of stopping at the edge of
    the sweep ((the first run stopped at the edge, which is itself a result).
    """
    flat = score[valid & (score > 0)]
    if flat.size == 0:
        return {int(a): 1.0 for a in areas_px}
    ks = sorted({int(np.clip(flat.size - a, 0, flat.size - 1)) for a in areas_px})
    part = np.partition(flat, ks)
    return {int(a): float(part[int(np.clip(flat.size - a, 0, flat.size - 1))])
            for a in areas_px}


def budget_threshold(score: np.ndarray, target_emitted_px: int) -> float:
    """Lowest threshold whose support is at most `target_emitted_px` pixels.

    The marginal rule gives a precision bar, not an area bar; the two are linked
    only through the score field's calibration, which we do not claim to know.
    Sweeping emitted area is therefore the honest way to locate the operating
    point, and scripts/tune_emission.py reports the DTI surface over area.
    """
    flat = score[np.isfinite(score)]
    if flat.size == 0 or target_emitted_px <= 0:
        return 1.0
    k = int(np.clip(flat.size - target_emitted_px, 0, flat.size - 1))
    return float(np.partition(flat, k)[k])


def marginal_precision(truth: np.ndarray, mask: np.ndarray, valid: np.ndarray,
                       emitted: np.ndarray, pixel_metres: float = 100.0,
                       r_metres: float = 300.0) -> Dict[str, float]:
    """Weighted precision of the emitted block, in the same units the metric uses.

    delta TP_w = sum over truth pixels of their best emitted kernel weight;
    delta FP_w = sum over emitted pixels of (1 - best kernel weight to truth).
    """
    w = int(round(r_metres / pixel_metres))
    k = np.zeros((2 * w + 1, 2 * w + 1), np.float32)
    for dy in range(-w, w + 1):
        for dx in range(-w, w + 1):
            d = np.hypot(dy, dx) * pixel_metres
            if d <= r_metres:
                k[dy + w, dx + w] = 1.0 - d / r_metres

    em = np.where(valid & ~mask, emitted, 0.0).astype(np.float32)
    tr = np.where(valid & ~mask, truth, False)
    credit = ndimage.maximum_filter(em, footprint=(k > 0), mode="constant")
    # maximum_filter does not weight; do the weighted max explicitly
    best = np.zeros_like(em)
    for dy in range(-w, w + 1):
        for dx in range(-w, w + 1):
            kv = k[dy + w, dx + w]
            if kv <= 0:
                continue
            best = np.maximum(best, kv * np.roll(np.roll(em, dy, 0), dx, 1))
    dtp = float(best[tr].sum()) if tr.any() else 0.0
    nearest = np.zeros_like(em)
    for dy in range(-w, w + 1):
        for dx in range(-w, w + 1):
            kv = k[dy + w, dx + w]
            if kv <= 0:
                continue
            nearest = np.maximum(nearest, kv * np.roll(np.roll(tr.astype(np.float32), dy, 0), dx, 1))
    dfp = float((em * (1.0 - nearest)).sum())
    prec = dtp / (dtp + dfp) if (dtp + dfp) > 0 else 0.0
    return {"delta_tp_w": dtp, "delta_fp_w": dfp, "weighted_precision": prec}


def sweep(score: np.ndarray, truth: np.ndarray, mask: np.ndarray, valid: np.ndarray,
          areas_px: Sequence[int], ridge_widths: Sequence[int] = (1,),
          nms_radii: Sequence[int] = (0, 1, 2),
          scorer=None) -> list:
    """Grid-search threshold x ridge width x spacing on one holdout.

    `scorer(pred) -> float` should return the holdout DTI.  Returns a list of
    records sorted by score, best first.
    """
    from .metric import dti
    results = []
    base = score
    for r in nms_radii:
        thin = nms_ridge(base, r) if r > 0 else base
        for wid in ridge_widths:
            shaped = orient_ridge(thin, wid) if (r > 0 or wid > 1) else thin
            for area in areas_px:
                thr = budget_threshold(shaped, area)
                pred = binarise(shaped, thr)
                em = int(pred.sum())
                if em == 0:
                    continue
                res = (scorer or (lambda p: dti(p, truth, mask=mask, valid=valid))) (pred)
                results.append({
                    "nms_radius": r, "ridge_width": wid,
                    "target_area_px": int(area), "emitted_px": em,
                    "threshold": thr, "dti": res["dti"],
                    "tp_w": res["tp_w"], "fp_w": res["fp_w"], "fn_w": res["fn_w"],
                })
    results.sort(key=lambda r: -r["dti"])
    return results
