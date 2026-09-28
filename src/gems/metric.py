"""Official distance-weighted Tversky index (DTI) for the DOE GEMS Prize.

Transcribed from the competition problem description, page 967
(https://www.drivendata.org/competitions/306/competition-doe-gems/page/967/),
"Mathematical representation" and "Scoring example".  Verbatim equations:

    k(d) = (1 - d/R)_+ = max(1 - d/R, 0),  R = 300 m

    TP_w = sum_{g in G}  max_{x : d(x,g) <= R} p(x) k(d(x,g))
    FP_w = sum_{x : p(x) > 0} p(x) [1 - max_{g in G} k(d(x,g))]
    FN_w = sum_{g in G} [1 - max_{x : d(x,g) <= R} p(x) k(d(x,g))]

    DTI(a, b) = TP_w / (TP_w + a FP_w + b FN_w + eps),  a = 0.2, b = 0.8

Two consequences of that definition are proved and tested here, because the whole
strategy of the project rests on them.

(1) TP_w + FN_w = |G| exactly (each truth pixel contributes W + (1 - W) = 1).
    Therefore, with a + b = 1,

        TP_w + a FP_w + b FN_w = TP_w + a FP_w + b |G| - b TP_w
                               = a TP_w + a FP_w + b |G|

    so DTI = TP_w / (a TP_w + a FP_w + b |G|).  Writing weighted recall
    R_w = TP_w / |G| and weighted precision P_w = TP_w / (TP_w + FP_w), this is

        DTI = 1 / (b / R_w + a / P_w)

    i.e. a weighted harmonic mean of weighted recall (weight b = 0.8) and
    weighted precision (weight a = 0.2).  `python -m gems.metric` prints the
    algebraic check against the page's own worked example.

(2) Marginal-block rule.  Adding prediction mass that contributes t to TP_w and
    f to FP_w changes the denominator to D + a(t + f) and the numerator to
    TP_w + t, because D = b|G| + a(TP_w + FP_w).  The added block pays iff

        t / (t + f)  >  a * DTI

    i.e. iff the block's own weighted precision exceeds a * DTI = 0.2 * DTI.
    Derivation in docs/METRIC_AUDIT.md; tested in tests/test_metric.py.

Scoring semantics fixed by organizer statements (see data/sources.json):
  * the known-fault mask is pixel-exact and identical to the training labels
    (chrisk-dd, forum topic 11516 post 4, 2026-09-21);
  * the mask is applied in both rounds (topic 11516 post 2, 2026-09-16);
  * masked pixels are score-neutral: "for scoring purposes it should not matter
    whether these known faults are included with predictions or not"
    (topic 11516 post 2) -- so they neither earn TP credit nor incur FP penalty;
  * false positives are measured against the new-fault ground truth only, so the
    300 m buffer does NOT apply around known traces (topic 11516 post 4).

This module runs with numpy when available and falls back to a pure-Python
implementation otherwise, so the metric can be re-audited without any install.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

try:  # numpy is optional: the exact metric must be auditable without it
    import numpy as _np
except Exception:  # pragma: no cover - exercised only on numpy-free hosts
    _np = None

ALPHA = 0.2
BETA = 0.8
R_METRES = 300.0
PIXEL_METRES = 100.0


# --------------------------------------------------------------------------
# kernel and neighbours
# --------------------------------------------------------------------------
def kernel(d_metres: float, r_metres: float = R_METRES) -> float:
    """Triangular kernel k(d) = max(1 - d/R, 0)."""
    return max(1.0 - d_metres / r_metres, 0.0)


def neighbourhood(r_metres: float = R_METRES, pixel_metres: float = PIXEL_METRES
                  ) -> Sequence[Tuple[int, int, float]]:
    """(dy, dx, k) for every cell offset whose centre is within the kernel support.

    R = 300 m at 100 m pixels gives a 7x7 neighbourhood (offsets up to 3 px).
    """
    reach = int(math.floor(r_metres / pixel_metres + 1e-9))
    out = []
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            d = math.hypot(dy * pixel_metres, dx * pixel_metres)
            k = kernel(d, r_metres)
            if k > 0.0:
                out.append((dy, dx, k))
    if not out:  # pragma: no cover - defensive
        raise ValueError("empty neighbourhood: check r_metres/pixel_metres")
    return tuple(out)


# --------------------------------------------------------------------------
# numpy implementation (fast path)
# --------------------------------------------------------------------------
def _shift(a, dy: int, dx: int, fill: float):
    """Return b with b[y, x] = a[y + dy, x + dx], out-of-range filled with `fill`."""
    np = _np
    h, w = a.shape
    out = np.full(a.shape, fill, dtype=a.dtype)
    ys, yd = (slice(dy, h), slice(0, h - dy)) if dy >= 0 else (slice(0, h + dy), slice(-dy, h))
    xs, xd = (slice(dx, w), slice(0, w - dx)) if dx >= 0 else (slice(0, w + dx), slice(-dx, w))
    out[ys, xs] = a[yd, xd]
    return out


def dti_numpy(pred, truth, alpha: float = ALPHA, beta: float = BETA,
              r_metres: float = R_METRES, pixel_metres: float = PIXEL_METRES,
              mask: Optional[object] = None, valid: Optional[object] = None,
              return_parts: bool = False) -> Dict[str, float]:
    """Vectorised DTI.  `pred` and `truth` are 2-D float/bool arrays.

    mask  : Boolean array, True where the known-fault mask applies.  Those pixels
            are score-neutral (no penalty, no credit), per the organizer.
    valid : Boolean array, True inside the data footprint.  Predictions outside
            are ignored, matching the requirement that outside values be NaN.

    TP_w is evaluated with the masked pixels *removed as prediction sources* for
    masked truth cells is NOT needed here: the truth set never contains masked
    pixels, so a masked pixel can only ever supply credit through its numerical
    value.  To keep masked pixels strictly score-neutral we zero the prediction
    there before computing credit -- see `mask_mode`.
    """
    np = _np
    if not isinstance(pred, np.ndarray):
        pred = np.asarray(pred, dtype=np.float64)
    else:
        pred = pred.astype(np.float64, copy=False)
    truth_b = np.asarray(truth).astype(bool)
    n = pred.shape
    if truth_b.shape != n:
        raise ValueError("pred and truth must have the same shape")

    pred = np.nan_to_num(pred, nan=0.0, posinf=0.0, neginf=0.0)
    if valid is not None:
        valid_b = np.asarray(valid).astype(bool)
        pred = np.where(valid_b, pred, 0.0)
        truth_b = truth_b & valid_b
    if mask is not None:
        mask_b = np.asarray(mask).astype(bool)
        # masked pixels are score-neutral: no credit can come from them, and
        # they never enter either sum.
        pred = np.where(mask_b, 0.0, pred)
        truth_b = truth_b & ~mask_b

    n_truth = float(truth_b.sum())
    w_truth = truth_b.astype(np.float64)

    credit = np.zeros(pred.shape, dtype=np.float64)
    nearest = np.zeros(pred.shape, dtype=np.float64)
    for dy, dx, k in neighbourhood(r_metres, pixel_metres):
        credit = np.maximum(credit, k * _shift(pred, dy, dx, 0.0))
        nearest = np.maximum(nearest, k * _shift(w_truth, dy, dx, 0.0))

    tp_w = float(credit[truth_b].sum())
    fn_w = n_truth - tp_w
    contrib = np.where(pred > 0.0, pred * (1.0 - nearest), 0.0)
    fp_w = float(contrib.sum())
    value = tp_w / (tp_w + alpha * fp_w + beta * fn_w) if (tp_w + alpha * fp_w + beta * fn_w) > 0 else 0.0
    out = {"dti": value, "tp_w": tp_w, "fp_w": fp_w, "fn_w": fn_w, "n_truth": n_truth}
    if return_parts:
        out["credit"] = credit
        out["nearest_k"] = nearest
    return out


# --------------------------------------------------------------------------
# pure-Python implementation (literal transcription of the page)
# --------------------------------------------------------------------------
def dti_literal(pred_rows: Sequence[Sequence[float]],
                truth_rows: Sequence[Sequence[int]],
                alpha: float = ALPHA, beta: float = BETA,
                r_metres: float = R_METRES,
                pixel_metres: float = PIXEL_METRES,
                mask_rows: Optional[Sequence[Sequence[bool]]] = None,
                valid_rows: Optional[Sequence[Sequence[bool]]] = None) -> Dict[str, float]:
    """Loop-for-loop transcription of the published equations.

    Deliberately naive O(N * 49): used as the independent reference that the
    vectorised path must reproduce, and as the executable form of the audit.
    """
    h = len(truth_rows)
    w = len(truth_rows[0])
    offsets = neighbourhood(r_metres, pixel_metres)

    def neutral(y: int, x: int) -> bool:
        """Masked (score-neutral) or outside the data footprint."""
        if mask_rows is not None and mask_rows[y][x]:
            return True
        if valid_rows is not None and not valid_rows[y][x]:
            return True
        return False

    truth_cells = [(y, x) for y in range(h) for x in range(w)
                   if truth_rows[y][x] and not neutral(y, x)]

    tp_w = 0.0
    fn_w = 0.0
    for (gy, gx) in truth_cells:
        best = 0.0
        for dy, dx, k in offsets:
            y, x = gy + dy, gx + dx
            if 0 <= y < h and 0 <= x < w:
                if neutral(y, x):
                    continue  # masked / outside footprint: score-neutral
                v = pred_rows[y][x] or 0.0
                if v * k > best:
                    best = v * k
        tp_w += best
        fn_w += 1.0 - best

    fp_w = 0.0
    for y in range(h):
        for x in range(w):
            if neutral(y, x):
                continue
            p = pred_rows[y][x] or 0.0
            if p <= 0.0:
                continue
            best_k = 0.0
            for dy, dx, k in offsets:
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w and truth_rows[yy][xx] and not neutral(yy, xx):
                    if k > best_k:
                        best_k = k
            fp_w += p * (1.0 - best_k)

    den = tp_w + alpha * fp_w + beta * fn_w
    return {"dti": (tp_w / den) if den > 0 else 0.0,
            "tp_w": tp_w, "fp_w": fp_w, "fn_w": fn_w,
            "n_truth": float(len(truth_cells))}


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------
def dti(pred, truth, **kw) -> Dict[str, float]:
    """Maximum-fidelity DTI.  Uses numpy when importable, else pure Python."""
    if _np is not None:
        return dti_numpy(pred, truth, **kw)
    return dti_literal(pred, truth, **kw)  # pragma: no cover


def harmonic_form(tp_w: float, fp_w: float, n_truth: float,
                  alpha: float = ALPHA, beta: float = BETA) -> Dict[str, float]:
    """DTI re-expressed as the weighted harmonic mean of recall and precision.

    DTI = TP_w / (a TP_w + a FP_w + b |G|) = 1 / (b / R_w + a / P_w)
    """
    if n_truth <= 0:
        return {"dti": 0.0, "recall_w": 0.0, "precision_w": 0.0, "harmonic": 0.0}
    recall_w = tp_w / n_truth
    denom_p = tp_w + fp_w
    precision_w = (tp_w / denom_p) if denom_p > 0 else 0.0
    if recall_w <= 0.0 or precision_w <= 0.0:
        return {"dti": 0.0, "recall_w": recall_w, "precision_w": precision_w, "harmonic": 0.0}
    harmonic = 1.0 / (beta / recall_w + alpha / precision_w)
    return {"dti": harmonic, "recall_w": recall_w,
            "precision_w": precision_w, "harmonic": harmonic}


def marginal_threshold(current_dti: float, alpha: float = ALPHA) -> float:
    """Minimum weighted precision a new block of predictions needs to pay for itself.

    Adding mass with weighted precision pi changes DTI iff pi > alpha * DTI.
    """
    return alpha * current_dti


def self_financing_distance(current_dti: float, alpha: float = ALPHA,
                            r_metres: float = R_METRES) -> float:
    """Furthest a full-strength pixel may sit from uncovered truth and still pay.

    A single pixel at distance d adds t = k(d) and f = 1 - k(d); it pays iff
    k(d) > alpha * DTI, i.e. d < R (1 - alpha * DTI).
    """
    return r_metres * (1.0 - alpha * current_dti)


def elasticity_ratio(precision_w: float, recall_w: float,
                     alpha: float = ALPHA, beta: float = BETA) -> float:
    """d ln DTI / d ln R  divided by  d ln DTI / d ln P  = (beta/alpha) P/R.

    A relative gain in recall beats the same relative gain in precision iff this
    ratio exceeds 1, i.e. iff P > (alpha/beta) R = R/4.
    """
    if precision_w <= 0.0 or recall_w <= 0.0:
        return 0.0
    return (beta / alpha) * precision_w / recall_w


def _worked_example() -> None:  # pragma: no cover - manual audit entry point
    tp_w, fp_w, fn_w = 3.00, 1.89, 2.00
    den = tp_w + ALPHA * fp_w + BETA * fn_w
    official = tp_w / den
    h = harmonic_form(tp_w, fp_w, tp_w + fn_w)
    print("official page: TP_w=3.00 FP_w=1.89 FN_w=2.00 -> TI_w(0.2,0.8) = %.6f" % official)
    print("transcription denominator = 3.00 + 0.2*1.89 + 0.8*2.00 = %.6f" % den)
    print("page states 0.60 ; ours rounds to %.2f" % round(official, 2))
    print("harmonic form 1/(b/R + a/P) = %.6f  (R=%.6f, P=%.6f)"
          % (h["dti"], h["recall_w"], h["precision_w"]))
    assert round(official, 2) == 0.60
    assert abs(official - h["dti"]) < 1e-12


if __name__ == "__main__":  # pragma: no cover
    _worked_example()


# --------------------------------------------------------------------------
# fast scorer for sweeps: precompute the truth-side kernel field once
# --------------------------------------------------------------------------
class FastDTI:
    """Evaluate DTI for many candidate predictions without recomputing the kernel.

    The expensive, prediction-independent part is `nearest_k[x] = max_g k(d(x,g))`
    over the scored truth set.  It is built once per holdout.  Each evaluation
    then costs O(49 * |G| + emitted pixels) instead of O(49 * raster):

      * TP_w only needs the credit field sampled AT truth pixels;
      * FP_w only needs `nearest_k` sampled AT emitted pixels.

    This is exactly the published definition -- `tests/test_metric.py` asserts
    that it agrees with dti_numpy and with the literal transcription on random
    small rasters.
    """

    def __init__(self, truth, mask=None, valid=None, alpha=ALPHA, beta=BETA,
                 r_metres=R_METRES, pixel_metres=PIXEL_METRES):
        np = _np
        if np is None:
            raise RuntimeError("FastDTI requires numpy")
        self.np = np
        self.alpha, self.beta = alpha, beta
        truth_b = np.asarray(truth).astype(bool)
        if valid is not None:
            truth_b = truth_b & np.asarray(valid).astype(bool)
        if mask is not None:
            truth_b = truth_b & ~np.asarray(mask).astype(bool)
        self.shape = truth_b.shape
        self.eligible = np.ones(self.shape, bool)
        if valid is not None:
            self.eligible &= np.asarray(valid).astype(bool)
        if mask is not None:
            self.eligible &= ~np.asarray(mask).astype(bool)

        nearest = np.zeros(self.shape, np.float32)
        for dy, dx, k in neighbourhood(r_metres, pixel_metres):
            nearest = np.maximum(nearest, k * _shift(truth_b.astype(np.float32), dy, dx, 0.0))
        self.nearest = nearest
        self.ys, self.xs = np.nonzero(truth_b)
        self.n_truth = float(len(self.ys))
        self.offsets = [(dy, dx, k) for dy, dx, k in
                        neighbourhood(r_metres, pixel_metres)]

    def __call__(self, pred):
        np = self.np
        p = np.asarray(pred, dtype=np.float32)
        p = np.nan_to_num(p, nan=0.0, posinf=0.0, neginf=0.0)
        p = np.where(p > 0.0, p, 0.0)
        h, w = self.shape
        ys, xs = self.ys, self.xs
        best = np.zeros(len(ys), np.float32)
        for dy, dx, k in self.offsets:
            yy = ys + dy
            xx = xs + dx
            inb = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
            yy = yy[inb]
            xx = xx[inb]
            src_ok = self.eligible[yy, xx]
            vals = np.where(src_ok, p[yy, xx], 0.0) * k
            cur = best[inb]
            best[inb] = np.maximum(cur, vals)
        tp_w = float(best.sum())
        fn_w = self.n_truth - tp_w

        ke = p > 0.0
        ey, ex = np.nonzero(ke)
        if len(ey):
            ok = self.eligible[ey, ex]
            ey, ex = ey[ok], ex[ok]
            contrib = p[ey, ex] * (1.0 - self.nearest[ey, ex])
            fp_w = float(contrib.sum())
            n_emitted = int(len(ey))
        else:
            fp_w = 0.0
            n_emitted = 0
        den = tp_w + self.alpha * fp_w + self.beta * fn_w
        return {"dti": (tp_w / den) if den > 0 else 0.0, "tp_w": tp_w,
                "fp_w": fp_w, "fn_w": fn_w, "n_truth": self.n_truth,
                "emitted_px": n_emitted}
