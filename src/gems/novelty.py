"""Novelty protocol: prove a candidate is not a resubmission of one we already sent.

The group has three scored submissions at 0.1563 that are the *same bytes*
(``7f00890a...``, committed in six paths across five repositories).  Two more
scored pairs differ only by a rounding-level map change.  Equal scores to four
decimals are therefore treated here as a *symptom to be tested*, not as
evidence: this module measures, for every pair of rasters,

  * the SHA-256 of the file, and the SHA-256 of the ``float32`` array itself
    (so two files that differ only in TIFF tags are still caught),
  * the tie-corrected Spearman rank correlation over a deterministic subsample
    of the common finite support,
  * top-k overlap of the emitted pixels for k in {1e3, 1e4, 5e4} and the full
    Jaccard index of the positive sets,
  * per-file contract facts (finite count, minimum, maximum) so a file that
    would be rejected by the platform's "[0, 1]" check is caught here.

The gate in :func:`gate` refuses a candidate that is a byte-identical copy, an
array-identical copy, or a near-duplicate of a prior submission **unless the
caller states a mechanism** (a documented reason the change should move the
score).  Nothing here scores anything; it only refuses repeats.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

DEFAULT_KS = (1000, 10000, 50000)
# A pair is "near-duplicate" when both the rank correlation and the top-k
# overlap are at or above these levels.  Frozen before any candidate existed.
NEAR_DUP_RHO = 0.99
NEAR_DUP_TOPK = 0.95
CHARGEABLE_JACCARD = 0.95      # two files whose chargeable sets agree to this are the same bet
CHARGEABLE_MIN_PX = 100        # below this the ratio is noise, not identity


def file_sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def array_sha256(a: np.ndarray) -> str:
    """SHA-256 of the array's little-endian float32 bytes, NaN canonicalised.

    Canonicalising NaN matters: two writers can emit different NaN payloads for
    the same map, and the competition contract only cares about the values.
    """
    x = np.asarray(a, dtype=np.float32)
    x = np.where(np.isfinite(x), x, np.float32(np.nan)).astype("<f4", copy=False)
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def contract_facts(a: np.ndarray) -> Dict[str, object]:
    fin = np.isfinite(a)
    v = a[fin]
    return {
        "finite_px": int(fin.sum()),
        "nan_px": int((~fin).sum()),
        "min": float(v.min()) if v.size else None,
        "max": float(v.max()) if v.size else None,
        "out_of_unit_interval_px": int(((v < 0.0) | (v > 1.0)).sum()) if v.size else 0,
        "emitted_px": int((v > 0.0).sum()) if v.size else 0,
        "distinct_values": int(np.unique(v).size) if v.size else 0,
    }


def emitted_mask(a: np.ndarray) -> np.ndarray:
    return np.isfinite(a) & (a > 0.0)


def rank_correlation(a: np.ndarray, b: np.ndarray, max_n: int = 200_000,
                     seed: int = 20260929) -> Optional[float]:
    """Tie-corrected Spearman rho over a deterministic subsample of the overlap."""
    m = np.isfinite(a) & np.isfinite(b)
    n = int(m.sum())
    if n < 10:
        return None
    idx = np.flatnonzero(m.ravel())
    if n > max_n:
        rng = np.random.default_rng(seed)
        idx = np.sort(rng.choice(idx, size=max_n, replace=False))
    x = a.ravel()[idx].astype(np.float64)
    y = b.ravel()[idx].astype(np.float64)
    if x.size > 1 and (np.all(x == x[0]) or np.all(y == y[0])):
        # a constant field has no rank information; fall back to equality
        return 1.0 if np.array_equal(x, y) else 0.0
    rx = _rankdata(x)
    ry = _rankdata(y)
    rx -= rx.mean()
    ry -= ry.mean()
    denom = float(np.sqrt((rx * rx).sum() * (ry * ry).sum()))
    return float((rx * ry).sum() / denom) if denom else None


def _rankdata(x: np.ndarray) -> np.ndarray:
    """Average ranks (ties get the mean rank), numpy-only."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(x.size, dtype=np.float64)
    sx = x[order]
    i = 0
    while i < sx.size:
        j = i
        while j + 1 < sx.size and sx[j + 1] == sx[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def topk_overlap(a: np.ndarray, b: np.ndarray,
                 ks: Sequence[int] = DEFAULT_KS) -> Dict[str, float]:
    """Overlap of the top-k cells of each raster, ranked by value.

    Interpretation: if two maps are the same map, the top-k sets coincide.
    """
    out: Dict[str, float] = {}
    fa = np.where(np.isfinite(a), a, -np.inf).ravel()
    fb = np.where(np.isfinite(b), b, -np.inf).ravel()
    for k in ks:
        if k >= fa.size:
            kk = fa.size
        else:
            kk = int(k)
        ia = set(np.argpartition(fa, -kk)[-kk:].tolist())
        ib = set(np.argpartition(fb, -kk)[-kk:].tolist())
        inter = len(ia & ib)
        out["top%d" % k] = inter / float(kk) if kk else 0.0
    return out


def set_overlap(a: np.ndarray, b: np.ndarray) -> Dict[str, float]:
    ea = emitted_mask(a)
    eb = emitted_mask(b)
    inter = int((ea & eb).sum())
    union = int((ea | eb).sum())
    return {
        "a_px": int(ea.sum()), "b_px": int(eb.sum()), "intersection_px": inter,
        "jaccard": (inter / union) if union else 1.0,
        "share_of_a_in_b": (inter / int(ea.sum())) if ea.sum() else 0.0,
        "share_of_b_in_a": (inter / int(eb.sum())) if eb.sum() else 0.0,
    }


def pair_report(pa: str, pb: str, a: np.ndarray, b: np.ndarray,
                ks: Sequence[int] = DEFAULT_KS) -> Dict[str, object]:
    return {
        "a": pa, "b": pb,
        "file_sha256_equal": file_sha256(pa) == file_sha256(pb),
        "array_sha256_equal": array_sha256(a) == array_sha256(b),
        "spearman_rho": rank_correlation(a, b),
        "topk": topk_overlap(a, b, ks),
        "emitted": set_overlap(a, b),
    }


def footprint_index(shape: Tuple[int, int], n: int = 200_000,
                    seed: int = 20260929) -> np.ndarray:
    """Deterministic flat index set used for every pairwise comparison.

    Using one fixed support for all pairs makes correlations comparable between
    pairs, which a per-pair common support would not be.  The caller passes the
    footprint mask of the shipped template; this function only subsamples it.
    """
    rng = np.random.default_rng(seed)
    idx = rng.choice(shape[0] * shape[1], size=min(n, shape[0] * shape[1]),
                     replace=False)
    return np.sort(idx)


def topk_sets(a: np.ndarray, ks: Sequence[int] = DEFAULT_KS) -> Dict[int, set]:
    """The flat indices of the k largest finite cells, for each k."""
    fa = np.where(np.isfinite(a), a, -np.inf).ravel()
    out: Dict[int, set] = {}
    for k in ks:
        kk = int(min(k, fa.size))
        out[int(k)] = set(np.argpartition(fa, -kk)[-kk:].tolist()) if kk else set()
    return out


def emitted_indices(a: np.ndarray) -> np.ndarray:
    return np.flatnonzero(emitted_mask(a).ravel())


def chargeable_mask(a: np.ndarray, label_free: np.ndarray) -> np.ndarray:
    """Emitted pixels that sit outside the shipped mask's 300 m free zone.

    Credit can only ever be earned here, so two submissions with different
    rasters are still the *same submission* if their chargeable sets agree.
    """
    return emitted_mask(a) & label_free


def chargeable_overlap(candidate: np.ndarray, prior: np.ndarray,
                       label_free: np.ndarray) -> Optional[Dict[str, object]]:
    c = np.flatnonzero(chargeable_mask(candidate, label_free).ravel())
    p = np.flatnonzero(chargeable_mask(prior, label_free).ravel())
    if c.size < CHARGEABLE_MIN_PX or p.size < CHARGEABLE_MIN_PX:
        return None
    inter = int(np.intersect1d(c, p).size)
    union = int(c.size + p.size - inter)
    jac = (inter / union) if union else 0.0
    return {"candidate_px": int(c.size), "prior_px": int(p.size),
            "intersection_px": inter, "jaccard": float(jac),
            "identical": bool(jac >= CHARGEABLE_JACCARD)}


def profile_raster(path: str) -> Dict[str, object]:
    """One-pass profile of a raster for the pairwise novelty table."""
    import rasterio
    with rasterio.open(path) as s:
        arr = s.read(1)
        profile = {"width": s.width, "height": s.height, "crs": str(s.crs),
                   "res": [float(v) for v in s.res], "dtype": s.dtypes[0],
                   "count": s.count,
                   "transform": [float(v) for v in s.transform[:6]]}
    return {
        "path": os.path.abspath(path),
        "file_sha256": file_sha256(path),
        "array_sha256": array_sha256(arr),
        "profile": profile,
        "contract": contract_facts(arr),
        "emitted_idx": emitted_indices(arr),
        "topk": topk_sets(arr),
        "field": arr,
    }


def gate(candidate_path: str, candidate: np.ndarray,
         priors: Sequence[Tuple[str, np.ndarray]],
         mechanism: Optional[str] = None,
         rho_threshold: float = NEAR_DUP_RHO,
         topk_threshold: float = NEAR_DUP_TOPK,
         ks: Sequence[int] = DEFAULT_KS,
         label_free: Optional[np.ndarray] = None) -> Dict[str, object]:
    """Refuse a duplicate; return a verdict record either way.

    ``priors`` is a sequence of (label, array) for every raster the group has
    already submitted.  A candidate that duplicates one of them is refused with
    ``ok=False`` unless ``mechanism`` is a non-empty string naming the change
    that is supposed to move the score.

    Two duplicate mechanisms are checked, because the score cannot tell them
    apart: array/rank identity (rho, top-k) and *chargeable* identity.  The
    second needs ``label_free`` -- the boolean mask of cells more than 300 m from
    any shipped label -- and catches two different rasters that bet on the same
    pixels.  It is the mechanism behind the group's 0.1563 tie.
    """
    ch = array_sha256(candidate)
    verdict: Dict[str, object] = {
        "candidate": os.path.abspath(candidate_path),
        "candidate_array_sha256": ch,
        "mechanism": mechanism,
        "checks": [],
        "ok": True,
    }
    for label, arr in priors:
        if arr is None:
            continue
        dup = array_sha256(arr) == ch
        rho = rank_correlation(candidate, arr)
        tk = topk_overlap(candidate, arr, ks)
        near = (rho is not None and rho >= rho_threshold
                and tk.get("top%d" % ks[1], 0.0) >= topk_threshold)
        rec = {"prior": label, "array_identity": bool(dup), "spearman_rho": rho,
               "topk": tk, "near_duplicate": bool(near)}
        chg = chargeable_overlap(candidate, arr, label_free) if label_free is not None else None
        if chg is not None:
            rec["chargeable"] = chg
            if chg["identical"]:
                near = True
                rec["near_duplicate"] = True
        verdict["checks"].append(rec)
        if dup or near:
            verdict["ok"] = False
            if dup:
                verdict["refused_because"] = "byte/array-identical copy of %s" % label
            elif chg is not None and chg["identical"]:
                verdict["refused_because"] = (
                    "chargeably identical to %s: Jaccard %.4f over %d shared pixels "
                    "outside the 300 m free zone" % (label, chg["jaccard"], chg["intersection_px"]))
            else:
                verdict["refused_because"] = (
                    "near-duplicate of %s (rho=%.6f, top-%d=%.3f)"
                    % (label, rho, ks[1], tk.get("top%d" % ks[1], 0.0)))
    if not verdict["ok"] and mechanism:
        verdict["ok"] = True
        verdict["override"] = (
            "duplicate refused by default; a stated mechanism was supplied, so "
            "this is a declared deliberate repeat: %s" % mechanism)
    return verdict
