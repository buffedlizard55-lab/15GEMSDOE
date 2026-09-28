"""Catalogue geometry: turn the label raster into withholdable fault segments.

The training labels are a 1-pixel-wide raster of USGS/INGENIOUS fault traces on
the 100 m competition grid.  To build a hide-and-recover holdout we need units
that can be withheld whole, at several granularities, so this module derives:

  * connected components of the label raster ("systems");
  * junction-separated chains inside each component ("segments") -- the natural
    unit a mapping geologist would call a strand;
  * per-unit geometry: pixel length, centroid, principal orientation, elongation
    and the distance to the nearest pixel of any *other* segment (isolation).

Everything is vectorised: one `ndimage.label`, one bincount per moment, and one
feature transform for isolation, so the 12.3 Mpixel raster is processed in
seconds rather than minutes.

Nothing here uses attributes the competition does not ship.  The label raster
carries no age or slip-rate field, so attribute-stratified withholding is
recorded as unavailable (docs/HOLDOUT.md) rather than invented.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

EIGHT = np.ones((3, 3), bool)


def label_components(lab: np.ndarray, connectivity: int = 8):
    """Connected components of the fault labels.  Returns (ids, n)."""
    structure = EIGHT if connectivity == 8 else None
    ids, n = ndimage.label(lab > 0, structure=structure)
    return ids, int(n)


def junction_mask(ids: np.ndarray) -> np.ndarray:
    """Occupied pixels with >= 3 occupied 8-neighbours (i.e. branch points)."""
    occ = ids > 0
    deg = ndimage.convolve(occ.astype(np.uint8), np.ones((3, 3), np.uint8), mode="constant")
    deg = deg - occ.astype(np.uint8)
    return occ & (deg >= 3)


def trace_segments(ids: np.ndarray, min_pixels: int = 4) -> Dict[str, object]:
    """Split every component into junction-separated chains.

    Returns `segment_ids` (int32, 0 = background) and per-segment records sorted
    by descending length.  All moments come from single-pass bincounts.
    """
    occ = ids > 0
    junc = junction_mask(ids)
    chains = occ & ~junc
    seg_ids, n = ndimage.label(chains, structure=EIGHT)
    if n == 0:
        return {"segment_ids": seg_ids, "n": 0, "records": []}

    flat = seg_ids.ravel()
    idx = np.arange(1, n + 1)

    pixels = np.bincount(flat, minlength=n + 1)[1:]
    rows, cols = np.nonzero(seg_ids)
    sy = np.bincount(flat[flat > 0], weights=rows, minlength=n + 1)[1:]
    sx = np.bincount(flat[flat > 0], weights=cols, minlength=n + 1)[1:]
    m = pixels > 0
    cy = np.zeros(n)
    cx = np.zeros(n)
    cy[m] = sy[m] / pixels[m]
    cx[m] = sx[m] / pixels[m]

    # second moments about the centroid -> orientation without a per-label PCA
    w = flat[flat > 0]
    dx = cols - cx[w - 1]
    dy = rows - cy[w - 1]
    sxx = np.bincount(w, weights=dx * dx, minlength=n + 1)[1:]
    syy = np.bincount(w, weights=dy * dy, minlength=n + 1)[1:]
    sxy = np.bincount(w, weights=dx * dy, minlength=n + 1)[1:]

    comp_of = ids[rows, cols]
    uniq_w, first_pos = np.unique(w, return_index=True)
    comp_lookup = np.zeros(n + 2, dtype=np.int64)
    comp_lookup[uniq_w] = comp_of[first_pos]

    keep = np.nonzero(pixels >= min_pixels)[0] + 1
    remap = np.zeros(n + 1, dtype=np.int32)
    remap[keep] = np.arange(1, len(keep) + 1, dtype=np.int32)
    seg_ids = remap[seg_ids]

    records: List[Dict[str, object]] = []
    for old in keep:
        i = int(old)
        npx = int(pixels[i - 1])
        sxxi, syyi, sxyi = sxx[i - 1] / npx, syy[i - 1] / npx, sxy[i - 1] / npx
        theta = 0.5 * math.atan2(2.0 * sxyi, (sxxi - syyi))
        ev_max = 0.5 * (sxxi + syyi) + 0.5 * math.hypot(sxxi - syyi, 2.0 * sxyi)
        ev_min = 0.5 * (sxxi + syyi) - 0.5 * math.hypot(sxxi - syyi, 2.0 * sxyi)
        records.append({
            "id": int(remap[i]),
            "source_component": int(comp_lookup[i]),
            "pixels": npx,
            "length_px": float(npx),
            "centroid_row": float(cy[i - 1]),
            "centroid_col": float(cx[i - 1]),
            "orientation_deg": float(math.degrees(-theta) % 180.0),
            "elongation": float(ev_max / ev_min) if ev_min > 1e-9 else 1e6,
        })
    records.sort(key=lambda r: (-r["pixels"], r["id"]))
    return {"segment_ids": seg_ids, "n": len(records), "records": records}


def isolation_distance(seg_ids: np.ndarray, records: Sequence[Dict[str, object]],
                       pixel_metres: float = 100.0, reach_px: int = 25) -> None:
    """Annotate records in place with distance (m) to the nearest *other* segment.

    Exact within `reach_px` (the relevant scale for 'stand-alone strand'), using a
    small per-segment window distance transform; values beyond the window are
    censored at reach_px * pixel_metres and marked with `isolation_censored`.
    """
    from scipy import ndimage as ndi
    h, w = seg_ids.shape
    for rec in records:
        i = int(rec["id"])
        ys, xs = np.nonzero(seg_ids == i)
        if ys.size == 0:
            rec["isolation_m"] = float("inf")
            continue
        y0 = max(0, ys.min() - reach_px); y1 = min(h, ys.max() + reach_px + 1)
        x0 = max(0, xs.min() - reach_px); x1 = min(w, xs.max() + reach_px + 1)
        win = seg_ids[y0:y1, x0:x1]
        mine = (win == i)
        other = (win > 0) & ~mine
        if not other.any():
            rec["isolation_m"] = float(reach_px * pixel_metres)
            rec["isolation_censored"] = True
            continue
        d = ndi.distance_transform_edt(~other, sampling=(pixel_metres, pixel_metres))
        rec["isolation_m"] = float(d[mine].min())
        rec["isolation_censored"] = bool(
            d[mine].min() >= (reach_px - 1) * pixel_metres)


def junction_owners(seg_ids: np.ndarray, junc: np.ndarray) -> np.ndarray:
    """Segment ids adjacent to each junction pixel.  Shape (n_junction, 8), 0 = none."""
    ys, xs = np.nonzero(junc)
    out = np.zeros((len(ys), 8), dtype=seg_ids.dtype)
    k = 0
    h, w = seg_ids.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            sy = np.clip(ys + dy, 0, h - 1)
            sx = np.clip(xs + dx, 0, w - 1)
            out[:, k] = seg_ids[sy, sx]
            k += 1
    return out


def visible_catalogue_distance(visible: np.ndarray, pixel_metres: float = 100.0) -> np.ndarray:
    """Distance (m) from every pixel to the nearest VISIBLE catalogue pixel.

    Anti-leakage: callers must pass the catalogue *after* withholding, so no
    information about the hidden geometry can enter a catalogue-derived feature.
    """
    return ndimage.distance_transform_edt(~(visible > 0), sampling=(pixel_metres, pixel_metres))
