"""Acquisition artifacts: flight-line geometry, block boundaries, orientation histograms.

Why this module exists
----------------------
The USGS GeoDAWN release describes fixed-wing surveys flown in four
north-to-south acquisition blocks with **east-west flight lines**, at 400 m
spacing (200 m in Area 1), at varying flight height, over two overlapping
survey areas with different grid resolutions.  Any derivative computed on the
grid (horizontal gradients, tilt angle, analytic signal, curvature) inherits the
along-line sampling; interpolation between lines manufactures east-west
structure that is sampling, not geology.

Two failure modes are therefore possible in a prediction raster:

1. **E-W lineament manufacture.**  An edge detector driven by the magnetic or
   radiometric grid can emit long, straight east-west segments where the true
   structure is north-south.  Measurable as an excess of azimuth mass near
   grid-east relative to the mapped catalogue.
2. **Block-boundary seam.**  The mosaicked products are cut and resampled at
   survey-area and block edges, so a detector can light up along a straight
   boundary line.  Measurable as a density step across a known boundary, or as
   row/column-wise density spikes.

Nothing in this module is evidence about the hidden labels.  It measures
properties of rasters that are on disk against a published survey geometry, and
it returns the numbers it computed rather than a verdict.

Sources for the survey design (all fetched through the research tool this
session; the exact strings are in ``data/sources.json``):
  * GeoDAWN data release, DOI 10.5066/P93LGLVQ, and the survey grids recorded in
    the transported ``geodawn_rad.json`` / ``geodawn_extensions.json``.
  * 7GEMSDOE session-7 protocol quotes the ScienceBase item's statement of four
    north-to-south blocks (Winnemucca, Fallon, Hawthorne, Tonopah), two
    overlapping survey areas and differing line spacing.  That file is a sibling
    session's note, so it is recorded here as *inherited* and re-measurable only
    where the transported rasters allow it.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

AZ_BINS = np.arange(0.0, 190.0, 10.0)          # azimuth of the lineament, mod 180


def gaussian(a: np.ndarray, sigma: float) -> np.ndarray:
    return ndimage.gaussian_filter(a, sigma=sigma, mode="nearest")


def structure_orientation(mask: np.ndarray, sigma: float = 2.0,
                          tensor_sigma: float = 4.0) -> Tuple[np.ndarray, np.ndarray]:
    """Return (azimuth mod 180 in degrees, coherence) of local lineaments.

    The structure tensor's dominant eigenvector is the *gradient* direction; the
    lineament runs perpendicular to it.  Coherence in [0, 1] is the anisotropy
    measure used as the histogram weight, so a flat area contributes nothing.
    """
    f = gaussian(mask.astype(np.float32), sigma)
    gy, gx = np.gradient(f)
    jxx = gaussian(gx * gx, tensor_sigma)
    jyy = gaussian(gy * gy, tensor_sigma)
    jxy = gaussian(gx * gy, tensor_sigma)
    theta_grad = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy)
    # the lineament runs perpendicular to the gradient; convert to an azimuth
    # measured from grid east, counter-clockwise, modulo 180 degrees:
    #   az ~   0  -> the lineament runs east-west   (gradient is north-south)
    #   az ~  90  -> the lineament runs north-south (gradient is east-west)
    az = np.degrees(theta_grad) + 90.0
    az = np.mod(az, 180.0)
    tr = jxx + jyy
    diff = np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy ** 2)
    coherence = np.where(tr > 0, diff / np.maximum(tr, 1e-12), 0.0)
    return az.astype(np.float32), coherence.astype(np.float32)


def azimuth_histogram(mask: np.ndarray, valid: np.ndarray, weight_by: str = "coherence",
                      sigma: float = 2.0, tensor_sigma: float = 4.0,
                      min_coherence: float = 0.2) -> Dict[str, object]:
    """Weighted azimuth histogram (10 degree bins, azimuth mod 180) of `mask`."""
    az, coh = structure_orientation(mask, sigma, tensor_sigma)
    sel = valid & np.isfinite(az) & (coh >= min_coherence)
    a = az[sel]
    w = coh[sel] if weight_by == "coherence" else np.ones_like(a)
    hist, edges = np.histogram(a, bins=AZ_BINS, weights=w)
    total = float(hist.sum())
    hist_n = hist / total if total else hist
    # east-west-lineament share: azimuth within +-10 deg of grid east
    ew = float(hist_n[((edges[:-1] >= 0.0) & (edges[:-1] < 10.0))
                      | ((edges[:-1] >= 170.0) & (edges[:-1] <= 180.0))].sum())
    # north-south-lineament share: azimuth within +-10 deg of grid north
    ns = float(hist_n[(edges[:-1] >= 80.0) & (edges[:-1] < 100.0)].sum())
    return {
        "bin_edges_deg": AZ_BINS.tolist(),
        "weights": hist_n.tolist(),
        "weighted_pixels": int(sel.sum()),
        "weight_sum": total,
        "east_west_share_0_10_and_170_180deg": ew,
        "north_south_share_80_100deg": ns,
        "ew_over_ns": (ew / ns) if ns else None,
    }


def tile_spread(mask: np.ndarray, valid: np.ndarray, tiles: int = 4,
                min_pixels: int = 2000, **kw) -> Dict[str, object]:
    """Spread of the azimuth statistics across an NxN spatial tiling.

    A single global histogram hides whether a lineament statistic is driven by
    one corner of the map.  Tiling reports it: how many tiles show the pattern,
    the median share and the inter-quartile range across tiles.  Pixel-wise
    bootstrap would understate uncertainty (neighbouring pixels correlate), so
    whole tiles are the resampling unit.
    """
    h, w = mask.shape
    rows = np.array_split(np.arange(h), tiles)
    cols = np.array_split(np.arange(w), tiles)
    ews, nss, npx = [], [], []
    for r in rows:
        for c in cols:
            sub = mask[np.ix_(r, c)]
            subv = valid[np.ix_(r, c)]
            if int(sub.sum()) < 10:
                continue
            rep = azimuth_histogram(sub.astype(np.float32), subv, **kw)
            if rep["weighted_pixels"] < min_pixels:
                continue
            ews.append(rep["east_west_share_0_10_and_170_180deg"])
            nss.append(rep["north_south_share_80_100deg"])
            npx.append(rep["weighted_pixels"])
    ews = np.asarray(ews, float)
    nss = np.asarray(nss, float)
    return {"tiles": tiles, "tiles_used": int(ews.size),
            "east_west_share_median": float(np.median(ews)) if ews.size else None,
            "east_west_share_q1": float(np.percentile(ews, 25)) if ews.size else None,
            "east_west_share_q3": float(np.percentile(ews, 75)) if ews.size else None,
            "north_south_share_median": float(np.median(nss)) if nss.size else None,
            "ew_share_per_tile": [float(v) for v in ews]}


def stripe_spectrum(window: np.ndarray) -> Dict[str, float]:
    """Anisotropy of a 2-D window's power spectrum.

    A grid whose sampling is organised on east-west lines carries more power for
    variation *along north-south* (ky) than along east-west (kx) at the
    line-spacing frequency.  Returned as the share of non-DC power within 15
    degrees of each spectral axis.
    """
    w = np.asarray(window, dtype=np.float64)
    w = np.where(np.isfinite(w), w, np.nanmean(w[np.isfinite(w)]) if np.isfinite(w).any() else 0.0)
    w = w - w.mean()
    W = np.fft.fft2(w)
    P = np.abs(W) ** 2
    ny, nx = P.shape
    ky = np.fft.fftfreq(ny)[:, None] * np.ones((1, nx))
    kx = np.fft.fftfreq(nx)[None, :] * np.ones((ny, 1))
    r = np.hypot(ky, kx)
    ang = np.degrees(np.arctan2(np.abs(ky), np.abs(kx)))     # 0 = kx axis, 90 = ky axis
    keep = r > 0
    tot = P[keep].sum()
    band = (r > 0.02) & (r < 0.5)
    near_ky = band & (ang >= 75.0)          # energy varying north-south
    near_kx = band & (ang <= 15.0)
    return {
        "total_power_nonzero": float(tot),
        "share_within_15deg_of_ky_axis": float(P[keep & near_ky].sum() / tot) if tot else 0.0,
        "share_within_15deg_of_kx_axis": float(P[keep & near_kx].sum() / tot) if tot else 0.0,
    }


def row_col_density_spikes(emitted: np.ndarray, valid: np.ndarray,
                           k: float = 4.0) -> Dict[str, object]:
    """Rows/columns whose emitted density is a spike relative to their neighbours.

    A mosaic seam or an interpolation line shows up as one row (or a few adjacent
    rows) far above the local level, which is not how geology looks at 100 m.
    """
    v = valid.sum(axis=1).astype(np.float64)
    e = emitted.sum(axis=1).astype(np.float64)
    supported = v >= 500            # rows with too little data cannot be judged
    dens = np.where(supported, e / np.maximum(v, 1), 0.0)
    med = ndimage.median_filter(dens, size=31, mode="nearest")
    mad = np.median(np.abs(dens - med)) or 1e-9
    z = (dens - med) / (1.4826 * mad)
    rows = np.flatnonzero((z > k) & supported)
    vc = valid.sum(axis=0).astype(np.float64)
    ec = emitted.sum(axis=0).astype(np.float64)
    supportedc = vc >= 500
    densc = np.where(supportedc, ec / np.maximum(vc, 1), 0.0)
    medc = ndimage.median_filter(densc, size=31, mode="nearest")
    madc = np.median(np.abs(densc - medc)) or 1e-9
    zc = (densc - medc) / (1.4826 * madc)
    cols = np.flatnonzero((zc > k) & supportedc)
    return {
        "row_z_threshold": k,
        "spike_rows": rows.tolist()[:50],
        "n_spike_rows": int(rows.size),
        "spike_cols": cols.tolist()[:50],
        "n_spike_cols": int(cols.size),
        "max_row_z": float(z.max()) if z.size else 0.0,
        "max_col_z": float(zc.max()) if zc.size else 0.0,
    }


def boundary_step(mask: np.ndarray, valid: np.ndarray, axis: str, at: int,
                  collar: int = 5) -> Dict[str, float]:
    """Emitted density inside a collar around a boundary versus matched interior."""
    dens = np.zeros_like(mask, dtype=np.float64)
    both = valid
    if axis == "row":
        sl_collar = slice(max(at - collar, 0), min(at + collar + 1, mask.shape[0]))
        sl_lo = slice(max(at - 10 * collar, 0), max(at - 2 * collar, 0))
        sl_hi = slice(min(at + 2 * collar, mask.shape[0]), min(at + 10 * collar, mask.shape[0]))
        in_c = mask[sl_collar] & valid[sl_collar]
        out = np.concatenate([(mask[sl_lo] & valid[sl_lo]).ravel(),
                              (mask[sl_hi] & valid[sl_hi]).ravel()])
        in_v = valid[sl_collar].sum()
        out_v = (valid[sl_lo].sum() + valid[sl_hi].sum())
    else:
        sl_collar = slice(max(at - collar, 0), min(at + collar + 1, mask.shape[1]))
        sl_lo = slice(max(at - 10 * collar, 0), max(at - 2 * collar, 0))
        sl_hi = slice(min(at + 2 * collar, mask.shape[1]), min(at + 10 * collar, mask.shape[1]))
        in_c = mask[:, sl_collar] & valid[:, sl_collar]
        out = np.concatenate([(mask[:, sl_lo] & valid[:, sl_lo]).ravel(),
                              (mask[:, sl_hi] & valid[:, sl_hi]).ravel()])
        in_v = valid[:, sl_collar].sum()
        out_v = (valid[:, sl_lo].sum() + valid[:, sl_hi].sum())
    d_in = float(in_c.sum()) / max(int(in_v), 1)
    d_out = float(out.sum()) / max(int(out_v), 1)
    return {"at": int(at), "collar_px": collar,
            "density_in_collar": d_in, "density_matched_outside": d_out,
            "ratio": (d_in / d_out) if d_out else None}
