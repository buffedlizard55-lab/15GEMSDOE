"""Detectors that consume information no previous submission in this group used.

Three new sources, all carried from official releases:

* GeoDAWN contractor **ratio grids** ``ThK``, ``UK``, ``UTh`` and the
  **upward-continued TMI to 150 m** (``TMI_up150``), from the GeoDAWN data
  release DOI 10.5066/P93LGLVQ (public domain, USGS).  The ratio grids cancel
  much of the altitude and drift variation of the raw channels, which is why the
  contractor publishes them; the upward-continued grid suppresses shallow
  sources, so its edges come from deeper structure than the supplied
  ``tmi_hg``/``tmi_vg`` bands.
* The raw **K, Th, U, total count** channels from the same release.

Why this is not the failed radiometric arm (sibling 7GEMSDOE H9, "not promoted"):
that test fed raw K/Th/U/TC *as classifier features* and lost against the
19-band stack.  Here the radiometrics are used two ways it never was:

1. as **ratios** in a spatial-structure detector (alteration proxy), and
2. as one arm of a **multi-sensor conjunction**, where a pixel is only emitted
   when independent sensor families agree (the metric pays for a fault pixel
   once, so a conjunction that raises precision is worth more than a marginal
   rise in recall).

Everything returned is in [0, 1] on the footprint, like ``fields.build_fields``.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import numpy as np

from .fields import _gauss, _grad_mag, _nan_safe_z

AUX_EXTENSIONS = os.path.join("aux", "geodawn_extensions_u8.tif")
AUX_RADIOMETRIC = os.path.join("aux", "geodawn_rad_u8.tif")


def _read(path: str, valid: np.ndarray) -> Dict[str, np.ndarray]:
    import rasterio
    with rasterio.open(path) as s:
        out = {}
        for i, name in enumerate(s.descriptions):
            if not name:
                continue
            a = s.read(i + 1).astype(np.float32)
            a[a <= 0] = np.nan          # 0 is the transported nodata code
            out[name] = a
    return out


def build_aux_fields(aux_dir: str, valid: np.ndarray, sigma: float = 1.0,
                     cache_dir: Optional[str] = None) -> Dict[str, np.ndarray]:
    ext_path = os.path.join(aux_dir, AUX_EXTENSIONS)
    rad_path = os.path.join(aux_dir, AUX_RADIOMETRIC)
    out: Dict[str, np.ndarray] = {}

    def cached(name, fn):
        path = os.path.join(cache_dir, "aux__%s.npy" % name) if cache_dir else None
        if path and os.path.exists(path):
            out[name] = np.load(path)
            return out[name]
        a = fn().astype(np.float32)
        if path:
            os.makedirs(cache_dir, exist_ok=True)
            np.save(path, a)
        out[name] = a
        return a

    ext = _read(ext_path, valid) if os.path.exists(ext_path) else {}
    rad = _read(rad_path, valid) if os.path.exists(rad_path) else {}

    if {"ThK", "UK"} <= set(ext):
        def rad_alteration():
            """K-enrichment relative to Th, plus U mobilisation relative to K.

            Hydrothermal alteration concentrates potassium (illite/sericite) and
            mobilises uranium, so both ratios deviate inside a conduit halo.  The
            zero-sum of two z-scores is a compromise field, not a calibrated
            probability.
            """
            z1 = _nan_safe_z(-np.nan_to_num(ext["ThK"]), valid)     # low Th/K = K rich
            z2 = _nan_safe_z(np.nan_to_num(ext["UK"]), valid)       # high U/K = U rich
            return 0.5 * (z1 + z2)
        cached("rad_alteration", rad_alteration)

    if "UTh" in ext:
        cached("rad_uth_anomaly",
               lambda: _nan_safe_z(np.nan_to_num(ext["UTh"]), valid))

    if "TMI_up150" in ext:
        def tmi150_edge():
            g = _grad_mag(_gauss(np.nan_to_num(ext["TMI_up150"]), sigma))
            return _nan_safe_z(g, valid)
        cached("tmi150_edge", tmi150_edge)

    if "K" in rad:
        def rad_k_edge():
            g = _grad_mag(_gauss(np.nan_to_num(rad["K"]), sigma))
            return _nan_safe_z(g, valid)
        cached("rad_k_edge", rad_k_edge)

    for k in out:
        out[k] = np.where(valid, out[k], 0.0).astype(np.float32)
    return out


def conjunction(base: Dict[str, np.ndarray], aux: Dict[str, np.ndarray],
                parts: tuple, valid: np.ndarray, power: float = 1.0) -> np.ndarray:
    """Geometric mean of several [0, 1] fields: a pixel needs *all* sensors.

    The metric credits each truth pixel once (the 300 m kernel takes a maximum),
    so a prediction that two independent sensor families support is worth more
    than one supported by a single noisy derivative.  The geometric mean is the
    'AND' with the harshest penalty for a single zero.
    """
    fields = {**base, **aux}
    stack = [np.clip(fields[p], 0.0, 1.0) for p in parts]
    m = np.ones_like(stack[0], dtype=np.float64)
    for s in stack:
        m *= np.maximum(s, 1e-6)
    out = np.power(m, power / len(stack))
    return np.where(valid, out, 0.0).astype(np.float32)


CONJUNCTIONS = {
    # two independent sensor families, both edge-like
    "conj_mag_gravity": ("mag_tilt", "grav_grad"),
    # magnetic + gravity + deeper-source magnetic (upward continued)
    "conj_three_edges": ("mag_tilt", "grav_grad", "tmi150_edge"),
    # the alteration proxy must agree with a magnetic edge
    "conj_alteration_mag": ("rad_alteration", "mag_tilt"),
    # alteration + gravity edge: fluids follow density boundaries
    "conj_alteration_gravity": ("rad_alteration", "grav_grad"),
}
