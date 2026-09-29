"""Candidate geological detectors, one per named hypothesis.

Every field is derived from the official 19-band `training_features.tif` (band
inventory and descriptions verified from the competition data tab raster) plus,
where stated, the *visible* catalogue only.  No field may touch the hidden
geometry: catalogue-derived inputs are computed from `visible` passed in by the
caller, which is `labels` minus the withheld segments.

Band index -> official description (read from the shipped raster's descriptions):

    0  mag_anom            magnetic anomaly
    1  rtp                 reduced to pole magnetic data
    2  tmi_hg              total magnetic intensity horizontal gradient
    3  geod_2ndinv         geodetic second invariant of the strain-rate tensor
    4  iso_grav_anom_slope slope of the isostatic gravity anomaly
    5  tc                  tilt angle / total curvature, magnetic derivative for edge detection
    6  geod_shearrate      geodetic shear rate
    7  geod_dilaterate     geodetic dilatation rate
    8  tmi_vg              total magnetic intensity vertical gradient
    9  deq_n100a15         distance to earthquake (100 km radius, 15 deg azimuth)
    10 iso_grav_anom_vg    isostatic gravity anomaly vertical gradient
    11 det_elev            detrended elevation
    12 iso_grav_anom       isostatic gravity anomaly
    13 tmi                 total magnetic intensity
    14 depth_to_base_surf  depth to basement surface
    15 ieq_n100a15         earthquake density/intensity
    16 cond_surf           conductivity surface
    17 iso_grav_anom_hg    isostatic gravity anomaly horizontal gradient
    18 det_elev_slope      slope of detrended elevation

Hypotheses (see docs/HYPOTHESES.md for the ranking and the reasoning):

  G1  curv_scarp      topographic scarp ridge: the 2nd-order curvature of
                      detrended elevation, not its gradient.  A fault scarp is a
                      *step*; curvature peaks on both shoulders and is
                      insensitive to broad regional slope, so it survives
                      detrending error that suppresses gradient detectors.
  G2  mag_tilt        amplitude-normalised magnetic edge: |tilt angle| ridge.
                      Normalisation makes weak, low-contrast magnetic sources
                      visible, and weak sources are exactly what a catalogue
                      omits.
  G3  grav_grad       density-boundary ridge from the isostatic gravity
                      horizontal gradient.  Sees *buried* structures under basin
                      fill that topography cannot show.
  G4  cond_depth      conjunction of high conductivity and a step in
                      depth-to-basement: fault-controlled fluid pathways.
                      A conjunction, so a single weak band cannot fire it.
  G5  seismo_prior    seismicity-alignment prior, used as a multiplier on the
                      other detectors rather than alone.
  G6  strain_ridge    present-day strain-rate lineament from the geodetic
                      invariants (2nd invariant + shear rate).
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np
from scipy import ndimage

BANDS = {
    "mag_anom": 0, "rtp": 1, "tmi_hg": 2, "geod_2ndinv": 3,
    "iso_grav_anom_slope": 4, "tc": 5, "geod_shearrate": 6,
    "geod_dilaterate": 7, "tmi_vg": 8, "deq_n100a15": 9,
    "iso_grav_anom_vg": 10, "det_elev": 11, "iso_grav_anom": 12, "tmi": 13,
    "depth_to_base_surf": 14, "ieq_n100a15": 15, "cond_surf": 16,
    "iso_grav_anom_hg": 17, "det_elev_slope": 18,
}

FIELDS = ("catalogue_proximity", "curv_scarp", "mag_tilt", "grav_grad",
          "cond_depth", "seismo_prior", "strain_ridge",
          "curv_multiscale_sum", "curv_multiscale_max", "curv_multiscale_prod")


def _gauss(a: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return a
    return ndimage.gaussian_filter(a, sigma, mode="nearest")


def _grad_mag(a: np.ndarray) -> np.ndarray:
    gy = ndimage.sobel(a, axis=0, mode="nearest")
    gx = ndimage.sobel(a, axis=1, mode="nearest")
    return np.hypot(gx, gy) / 8.0  # sobel 3x3 normalisation


def _laplacian(a: np.ndarray) -> np.ndarray:
    return ndimage.laplace(a, mode="nearest")


def _multi_scale_curvature(det_elev: np.ndarray, valid: np.ndarray,
                           sigma: float = 1.0) -> Dict[str, np.ndarray]:
    """Compute curvature at multiple scales and stack.
    
    Hypothesis H5: Multi-Scale Curvature Stack
    - Faults express at multiple scales
    - Small faults: 300m scale optimal
    - Large fault zones: 600m-1200m scales optimal
    - Multi-scale stack captures faults of all sizes
    
    Returns dict with three stacking methods: sum, max, product.
    """
    scales = [3, 6, 9, 12]  # pixels (300m, 600m, 900m, 1200m)
    curvatures = []
    
    for scale in scales:
        # Gaussian smoothing at scale * 100m
        smoothed = _gauss(det_elev, sigma * scale)
        # Laplacian for curvature
        curv = np.abs(_laplacian(smoothed))
        # Normalize to [0, 1]
        curv = _nan_safe_z(curv, valid)
        curvatures.append(curv)
    
    # Stacking method 1: Sum (amplifies consistent signals)
    curv_sum = np.clip(np.sum(curvatures, axis=0), 0, 1)
    
    # Stacking method 2: Max (preserves sharpest features)
    curv_max = np.max(curvatures, axis=0)
    
    # Stacking method 3: Product (AND logic - requires all scales)
    prod = np.ones_like(curvatures[0], dtype=np.float64)
    for c in curvatures:
        prod *= np.maximum(c, 1e-6)
    
    return {
        "curv_multiscale_sum": curv_sum.astype(np.float32),
        "curv_multiscale_max": curv_max.astype(np.float32),
        "curv_multiscale_prod": prod.astype(np.float32),
    }


def _nan_safe_z(a: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Robust z-like scaling to [0, 1] using the valid region's percentiles."""
    v = a[valid & np.isfinite(a)]
    if v.size < 16:
        return np.zeros_like(a, dtype=np.float32)
    lo, hi = np.percentile(v, (2.0, 98.0))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.zeros_like(a, dtype=np.float32)
    z = (a - lo) / (hi - lo)
    return np.clip(np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0), 0.0, 1.0).astype(np.float32)


def read_band(src, name: str, valid: np.ndarray) -> np.ndarray:
    a = src.read(BANDS[name] + 1).astype(np.float32)
    nod = a <= -3e38
    a[nod] = np.nan
    return a


def build_fields(features_path: str, visible: np.ndarray, valid: np.ndarray,
                 cache_dir: Optional[str] = None, tag: str = "base",
                 sigma: float = 1.0) -> Dict[str, np.ndarray]:
    """Compute every detector field.  Returns a dict of float32 arrays in [0, 1].

    `visible` must already have the withheld geometry removed.
    """
    import rasterio

    out: Dict[str, np.ndarray] = {}
    if cache_dir and tag:
        os.makedirs(cache_dir, exist_ok=True)

    def cached(name: str, fn):
        # only the catalogue-derived field depends on which segments are hidden,
        # so it alone is cached per holdout tag
        key = tag if name == "catalogue_proximity" else "grid"
        path = os.path.join(cache_dir, "%s__%s.npy" % (name, key)) if cache_dir else None
        if path and os.path.exists(path):
            out[name] = np.load(path)
            return out[name]
        a = fn()
        if path:
            np.save(path, a)
        out[name] = a
        return a

    with rasterio.open(features_path) as src:
        # ---- G1 curvature scarp ------------------------------------------
        def g1():
            e = read_band(src, "det_elev", valid)
            c = np.abs(_laplacian(_gauss(e, sigma)))
            return _nan_safe_z(c, valid)
        cached("curv_scarp", g1)

        # ---- G2 magnetic tilt-angle ridge --------------------------------
        def g2():
            t = read_band(src, "tc", valid)
            s = _gauss(t, sigma)
            gy = ndimage.sobel(s, axis=0, mode="nearest")
            gx = ndimage.sobel(s, axis=1, mode="nearest")
            return _nan_safe_z(np.hypot(gx, gy), valid)
        cached("mag_tilt", g2)

        # ---- G3 gravity horizontal-gradient ridge ------------------------
        def g3():
            hg = read_band(src, "iso_grav_anom_hg", valid)
            g = read_band(src, "iso_grav_anom", valid)
            a = _gauss(np.hypot(np.nan_to_num(hg), np.abs(_grad_mag(np.nan_to_num(g)))), sigma)
            return _nan_safe_z(a, valid)
        cached("grav_grad", g3)

        # ---- G4 conductivity x depth-to-basement step --------------------
        def g4():
            cond = read_band(src, "cond_surf", valid)
            dtb = read_band(src, "depth_to_base_surf", valid)
            step = _grad_mag(_gauss(np.nan_to_num(dtb), sigma))
            zc = _nan_safe_z(cond, valid)
            zs = _nan_safe_z(step, valid)
            return np.sqrt(zc * zs).astype(np.float32)
        cached("cond_depth", g4)

        # ---- G5 seismicity prior -----------------------------------------
        def g5():
            deq = read_band(src, "deq_n100a15", valid)
            ieq = read_band(src, "ieq_n100a15", valid)
            a = -np.nan_to_num(deq) + np.nan_to_num(ieq)
            return _nan_safe_z(_gauss(a, sigma), valid)
        cached("seismo_prior", g5)

        # ---- G6 strain-rate lineament ------------------------------------
        def g6():
            inv2 = _gauss(np.nan_to_num(read_band(src, "geod_2ndinv", valid)), sigma)
            shr = _gauss(np.nan_to_num(read_band(src, "geod_shearrate", valid)), sigma)
            return _nan_safe_z(np.hypot(inv2, shr), valid)
        cached("strain_ridge", g6)

        # ---- H6: Magnetic Analytic Signal Amplitude ------------------------
        def mag_asa():
            """Analytic Signal Amplitude from magnetic derivatives.
            ASA = sqrt(tmi_vg^2 + tmi_hg^2)
            Enhances edges regardless of magnetization direction.
            """
            tmi_vg = _gauss(np.nan_to_num(read_band(src, "tmi_vg", valid)), sigma)
            tmi_hg = _gauss(np.nan_to_num(read_band(src, "tmi_hg", valid)), sigma)
            asa = np.sqrt(tmi_vg**2 + tmi_hg**2)
            return _nan_safe_z(asa, valid)
        cached("mag_asa", mag_asa)

        def mag_asa_edge():
            """Edge of Analytic Signal Amplitude."""
            asa = _gauss(np.nan_to_num(read_band(src, "mag_asa", valid)), 0)
            # Actually, mag_asa is computed, not a band
            # Need to get it from the cached dict
            g = _grad_mag(_gauss(np.nan_to_num(out.get("mag_asa", np.zeros_like(valid))), sigma))
            return _nan_safe_z(g, valid)
        # Don't cache this separately, compute it differently

        # ---- H7: Gravity Terrain-Corrected Edge -----------------------------
        # Simple terrain correction: use gravity gradient which is less affected by terrain
        def grav_tc_edge():
            """Terrain-corrected gravity edge approximation.
            Uses iso_grav_anom_hg which is less affected by terrain.
            """
            grav_hg = _gauss(np.nan_to_num(read_band(src, "iso_grav_anom_hg", valid)), sigma)
            return _nan_safe_z(_grad_mag(grav_hg), valid)
        cached("grav_tc_edge", grav_tc_edge)

    # ---- H5: Multi-Scale Curvature (outside with block) ---------------------
    # This needs to be computed after the with block closes
    # We'll add it after the with block

    # ---- reference arm: proximity to the VISIBLE catalogue only -----------
    def g7():
        from .catalogue import visible_catalogue_distance
        d = visible_catalogue_distance(visible)
        return np.exp(-d / 300.0).astype(np.float32)
    cached("catalogue_proximity", g7)

    for k in out:
        out[k] = np.where(valid, out[k], 0.0).astype(np.float32)
    
    # ---- H5: Multi-Scale Curvature (compute after with block) ---------------
    # Read det_elev outside the with block
    with rasterio.open(features_path) as src2:
        e = read_band(src2, "det_elev", valid)
    ms = _multi_scale_curvature(e, valid, sigma)
    for k, v in ms.items():
        out[k] = np.where(valid, v, 0.0).astype(np.float32)
    
    # ---- H6: Magnetic ASA Edge (compute after mag_asa is available) ---------
    if "mag_asa" in out:
        asa = out["mag_asa"]
        asa_edge = _grad_mag(_gauss(asa, sigma))
        out["mag_asa_edge"] = np.where(valid, _nan_safe_z(asa_edge, valid), 0.0).astype(np.float32)
    
    return out
