"""Label diff: shipped mask versus the public fault catalogues it was built from.

Why this module exists
----------------------
The organisers state (topic 11516 post 2, quoted in ``data/sources.json``) that
pixels of *known* USGS/INGENIOUS faults are **masked**: they are free — neither
credit nor penalty.  The mask is "pixel-exact - it is identical to the provided
set of training fault labels" (topic 11516 post 4).

The public catalogues that the labels were drawn from are bigger than the
rasterised mask.  Two independent official sources are involved:

* USGS Quaternary Fault and Fold Database (QFFDB) - ``Qfaults_GIS.zip`` from
  https://earthquake.usgs.gov/static/lfs/nshm/qfaults/Qfaults_GIS.zip
* INGENIOUS Great Basin Regional Dataset Compilation (GDR 1391, CC BY 4.0),
  "Quaternary Faults v2.zip", which its own page says "supersedes" v1.

Any trace that exists in a public catalogue but **not** in the shipped mask is a
pixel that is *unmasked yet not new* under the sponsor's definition of "new
fault" ("any fault pixel not already captured by USGS/INGENIOUS", topic 11536).
Such a pixel is therefore a **probable false-positive trap**: in a dense
emission it is charged ``alpha`` false-positive weight and earns credit only if
a genuine new-fault pixel happens to lie within the 300 m kernel.

This module measures that gap; it does not decide whether the trap hypothesis is
true.  Two opposing readings are both reported, because the local data cannot
settle it:

  (a) *trap*: the private truth is the expert-labelled set only, so a prediction
      on unmasked catalogue geometry is billed as a false positive;
  (b) *new*: the private truth includes catalogued-but-unshipped geometry, so
      predicting there earns credit.

Everything here is a measurement on rasters that are on disk.  Nothing is
inferred about the hidden truth.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

PIXEL_M = 100.0
KERNEL_R_M = 300.0            # published kernel range R
KERNEL_R_PX = KERNEL_R_M / PIXEL_M


def distance_to_labels(labels: np.ndarray) -> np.ndarray:
    """Euclidean distance, in pixels, from every cell to the nearest label cell.

    The metric's kernel credits a truth pixel from a prediction within 300 m =
    3 px.  A cell whose distance to the nearest *mask* pixel is greater than
    3 px is therefore outside the free zone of the published mask.
    """
    return ndimage.distance_transform_edt(labels == 0)


def zone_masks(labels: np.ndarray, catalogue: np.ndarray,
               valid: np.ndarray, radius_px: float = KERNEL_R_PX) -> Dict[str, np.ndarray]:
    """Return the boolean zones the audit reports on.

    labels    : shipped training labels (the pixel-exact official mask)
    catalogue : union of public catalogue traces rasterised on the same grid
    valid     : the competition footprint
    """
    lab = (labels > 0) & valid
    cat = (catalogue > 0) & valid
    dist_lab = distance_to_labels(lab)
    dist_cat = distance_to_labels(cat)
    return {
        "labels": lab,
        "catalogue": cat,
        # catalogue present, mask absent, and outside the mask's 300 m free zone
        "trap_far": cat & ~lab & (dist_lab > radius_px),
        # catalogue present, mask absent, inside the free zone (harmless in phase 1)
        "trap_near": cat & ~lab & (dist_lab <= radius_px),
        "catalogue_only": cat & ~lab,
        "labels_only": lab & ~cat,
        "labels_matched_1px": lab & ndimage.binary_dilation(cat, np.ones((3, 3), bool)),
        "dist_to_labels": dist_lab,
        "dist_to_catalogue": dist_cat,
    }


def _summarise(mask: np.ndarray, valid: np.ndarray) -> Dict[str, float]:
    n = int(mask.sum())
    f = float(valid.sum())
    return {"pixels": n, "fraction_of_footprint": (n / f) if f else 0.0,
            "square_km": n * (PIXEL_M ** 2) / 1e6}


def analyse(labels: np.ndarray, catalogue: np.ndarray, valid: np.ndarray,
            radius_px: float = KERNEL_R_PX,
            qfaults_bands: Optional[Dict[str, np.ndarray]] = None) -> Dict[str, object]:
    """Full label-diff report for one footprint."""
    zones = zone_masks(labels, catalogue, valid, radius_px)
    lab = zones["labels"]
    dist_lab = zones["dist_to_labels"]
    cat_only = zones["catalogue_only"]

    d = dist_lab[cat_only]
    rep: Dict[str, object] = {
        "pixel_m": PIXEL_M,
        "kernel_radius_px": radius_px,
        "footprint_px": int(valid.sum()),
        "labels_px": int(lab.sum()),
        "catalogue_px": int((catalogue > 0).sum()),
        "catalogue_overlap_with_labels_px": int((zones["catalogue"] & lab).sum()),
        "zones": {k: _summarise(zones[k], valid)
                  for k in ("trap_far", "trap_near", "catalogue_only",
                            "labels_only")},
        "catalogue_only_distance_px": {
            "min": float(d.min()) if d.size else None,
            "median": float(np.median(d)) if d.size else None,
            "p90": float(np.percentile(d, 90)) if d.size else None,
            "max": float(d.max()) if d.size else None,
        },
    }
    if qfaults_bands:
        rep["by_catalogue_band"] = {
            name: {
                "pixels": int(((b > 0) & valid).sum()),
                "outside_mask_free_zone_px": int(((b > 0) & zones["trap_far"]).sum()),
                "fraction_outside_free_zone": float(
                    ((b > 0) & zones["trap_far"]).sum() / max(int(((b > 0) & valid).sum()), 1)),
            }
            for name, b in qfaults_bands.items()
        }
    return rep


def emission_overlap(emitted: np.ndarray, zones: Dict[str, np.ndarray]) -> Dict[str, object]:
    """How much of an already-emitted prediction mass sits in each zone."""
    e = emitted > 0
    n = int(e.sum())
    out: Dict[str, object] = {"emitted_px": n}
    for k in ("labels", "trap_far", "trap_near", "labels_only"):
        z = zones[k]
        m = int((e & z).sum())
        out[k] = {"pixels": m,
                  "share_of_emitted": (m / n) if n else 0.0}
    return out


def bet_size(emitted: np.ndarray, truth_assumption_dti: float,
             weights: Tuple[float, float] = (0.2, 0.8)) -> Dict[str, float]:
    """Size of the trap bet in metric units, under the two readings.

    This is an *arithmetic* conversion, not a prediction: it says how much
    weighted mass the trap-zone pixels carry if they are billed as false
    positives (0.2 each) versus if they are credited as true positives
    (max-kernel credit 1.0 each, assuming a distinct truth pixel each).

    ``truth_assumption_dti`` only appears to express the cost in units of the
    score the map currently holds; the caller supplies it and it is echoed back.
    """
    alpha, beta = weights
    return {
        "assumption_dti_echo": truth_assumption_dti,
        "alpha": alpha, "beta": beta,
        "note": ("if the trap reading holds, each emitted trap pixel beyond the "
                 "300 m free zone adds alpha false-positive weight; if the new "
                 "reading holds it adds up to one unit of TP_w"),
    }
