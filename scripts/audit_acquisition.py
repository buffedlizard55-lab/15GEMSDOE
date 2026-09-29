#!/usr/bin/env python
"""Acquisition-artifact audit: flight-line orientation, seams, blocks, strata.

Measured, per raster:
  1. weighted azimuth histogram of local lineaments (structure tensor),
     with the east-west share over a 4x4 spatial tiling;
  2. spectral anisotropy of the magnetic and radiometric grids (striping);
  3. row/column density spikes in an emitted map (mosaic seams);
  4. density step across the GeoDAWN Area 1 boundary.

    python scripts/audit_acquisition.py [--out docs/evidence/acquisition_audit.json]

Everything is measured on files that are on disk.  The survey geometry comes
from the transported GeoDAWN provenance JSON (published DOI recorded there) and
from the shipped rasters themselves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.gems import acquisition as AQ  # noqa: E402

REPOS = "/home/user/work/repos"
MAPS = {
    "catalogue_labels": None,                      # filled from labels.tif
    "anchor_ens12_01563": os.path.join(REPOS, "GEMSDOE/data/evidence/runs/ens12-adopted-floor0.1-w0/submission.tif"),
    "anchor_hedge_01563": os.path.join(REPOS, "8GEMSDOE/downloads/8GEMSDOE_Hedge-v2_submission.tif"),
    "anchor_apex_01563": os.path.join(REPOS, "8GEMSDOE/downloads/8GEMSDOE-Apex-Geothermal-V1.tif"),
    "anchor_pindrop_nodes_01193": os.path.join(REPOS, "5GEMSDOE/data/evidence/leaderboard_anchor/pindrop-v4-nodes-f347b70daa.tif"),
    "anchor_halo15_01461": os.path.join(REPOS, "7GEMSDOE/downloads/gems7-halo15-gbt-v1-90fb7dc0fc1f.tif"),
    "candidate_12gemsdoe_r7": os.path.join(REPOS, "12GEMSDOE/docs/downloads/12GEMSDOE_r7-nms3-dem10-scarp_0c9199f14e62.tif"),
    "candidate_15gemsdoe_tso1": os.path.join(ROOT, "docs/downloads/gems-tso1-20260929T005627Z-conj_alteration_mag.tif"),
    "prior_15gemsdoe_curv_scarp": os.path.join(ROOT, "docs/downloads/gems-cleanup-a-20260928T195952Z-curv_scarp.tif"),
}

# GeoDAWN Area 1 block, from the transported provenance JSON (50 m grid).
AREA1 = {"transform": [50.0, 0.0, 406575.0, 0.0, -50.0, 4202725.0],
         "width": 1338, "height": 979}


def area1_window(shape, transform) -> Dict[str, int]:
    """Row/column window of the Area 1 block inside the competition grid."""
    x0, y0 = transform[2], transform[5]
    px, py = abs(transform[0]), abs(transform[4])
    ax0, ay0 = AREA1["transform"][2], AREA1["transform"][5]
    ax1 = ax0 + AREA1["width"] * 50.0
    ay1 = ay0 - AREA1["height"] * 50.0
    c0 = int(round((ax0 - x0) / px))
    c1 = int(round((ax1 - x0) / px))
    # row index grows southward, y grows northward: the block top (larger y)
    # is the smaller row index.
    r0 = int(round((y0 - ay0) / py))
    r1 = int(round((y0 - ay1) / py))
    return {"row0": max(r0, 0), "row1": min(r1, shape[0]),
            "col0": max(c0, 0), "col1": min(c1, shape[1])}


def main() -> int:
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data", "raw"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "evidence",
                                                  "acquisition_audit.json"))
    args = ap.parse_args()

    with rasterio.open(os.path.join(args.data_dir, "labels.tif")) as s:
        labels = s.read(1)
        transform = list(s.transform)[:6]
        shape = (s.height, s.width)
    with rasterio.open(os.path.join(args.data_dir, "sample_submission.tif")) as s:
        valid = np.isfinite(s.read(1))

    out: Dict[str, object] = {
        "grid": {"shape": list(shape), "transform": transform},
        "survey_geometry": {
            "area1_block_from_transported_provenance": AREA1,
            "area1_window_in_grid": area1_window(shape, transform),
            "line_spacing_m": {"area1": 200, "area2": 400},
            "flight_line_direction": "east-west (survey design, GeoDAWN ReadMe as recorded in the sibling provenance JSON)",
            "inherited_not_reverified": (
                "The line spacing, four-block division and flight height variation are "
                "recorded in the GeoDAWN ReadMe. This sandbox cannot download "
                "sciencebase.gov (measured: curl exit 000), so those parameters are "
                "taken from the transported provenance JSON and are labelled inherited."),
        },
        "maps": {},
    }

    for name, path in MAPS.items():
        if name == "catalogue_labels":
            arr = (labels > 0)
        else:
            if not os.path.isfile(path):
                out["maps"][name] = {"missing": path}
                continue
            with rasterio.open(path) as s:
                a = s.read(1)
            arr = np.isfinite(a) & (a > 0)
        hist = AQ.azimuth_histogram(arr.astype(np.float32), valid)
        rec: Dict[str, object] = {"source": path or "data/raw/labels.tif",
                                  "emitted_px": int(arr.sum()),
                                  "azimuth": hist}
        rec["spikes"] = AQ.row_col_density_spikes(arr, valid)
        a1 = out["survey_geometry"]["area1_window_in_grid"]
        rec["area1_boundary"] = {
            "left": AQ.boundary_step(arr, valid, "col", a1["col0"]),
            "right": AQ.boundary_step(arr, valid, "col", a1["col1"]),
            "top": AQ.boundary_step(arr, valid, "row", a1["row0"]),
            "bottom": AQ.boundary_step(arr, valid, "row", a1["row1"]),
        }
        dense = arr & valid
        inside = np.zeros(shape, bool)
        inside[a1["row0"]:a1["row1"], a1["col0"]:a1["col1"]] = True
        sub = dense[a1["row0"]:a1["row1"], a1["col0"]:a1["col1"]]
        rec["area1_share"] = {
            "area1_valid_px": int(valid[a1["row0"]:a1["row1"], a1["col0"]:a1["col1"]].sum()),
            "emitted_in_area1_px": int(sub.sum()),
            "density_in_area1": float(sub.sum() / max(int(valid[a1["row0"]:a1["row1"], a1["col0"]:a1["col1"]].sum()), 1)),
            "density_outside_area1": float((dense & ~inside).sum()
                                           / max(int((valid & ~inside).sum()), 1)),
        }
        out["maps"][name] = rec
        print("%-28s emitted %9d  EW share %.4f  NS share %.4f  spike rows %d cols %d"
              % (name, rec["emitted_px"], hist["east_west_share_0_10_and_170_180deg"],
                 hist["north_south_share_80_100deg"],
                 rec["spikes"]["n_spike_rows"], rec["spikes"]["n_spike_cols"]), flush=True)

    # ---- tiled spread of the E-W share for three contrasting maps -------------
    boot: Dict[str, object] = {}
    for name in ("catalogue_labels", "anchor_ens12_01563", "candidate_12gemsdoe_r7"):
        rec = out["maps"].get(name)
        if not rec or "missing" in rec:
            continue
        if name == "catalogue_labels":
            arr = (labels > 0)
        else:
            with rasterio.open(rec["source"]) as s:
                a = s.read(1)
            arr = np.isfinite(a) & (a > 0)
        boot[name] = AQ.tile_spread(arr.astype(np.float32), valid, tiles=4)
        print("tiles %-30s EW share median %.4f  NS share median %.4f  tiles %d"
              % (name, boot[name]["east_west_share_median"],
                 boot[name]["north_south_share_median"], boot[name]["tiles_used"]), flush=True)
    out["tile_spread"] = boot

    # ---- spectral striping of the survey grids ------------------------------
    spec: Dict[str, object] = {}
    windows = [(200, 200), (1200, 900), (2400, 2000), (3000, 2600)]
    with rasterio.open(os.path.join(args.data_dir, "training_features.tif")) as s:
        desc = list(s.descriptions)
        for want in ("tmi", "mag_anom", "tmi_hg"):
            if want not in desc:
                continue
            bi = desc.index(want) + 1
            per_window = []
            for (r, c) in windows:
                if r + 512 > s.height or c + 512 > s.width:
                    continue
                w = s.read(bi, window=((r, r + 512), (c, c + 512)))
                per_window.append(AQ.stripe_spectrum(w))
            if per_window:
                spec[want] = {
                    "band_index": bi,
                    "windows": per_window,
                    "median_share_near_ky_axis": float(np.median([w["share_within_15deg_of_ky_axis"] for w in per_window])),
                    "median_share_near_kx_axis": float(np.median([w["share_within_15deg_of_kx_axis"] for w in per_window])),
                }
    rad = os.path.join(ROOT, "data", "aux", "geodawn_rad_u8.tif")
    if os.path.isfile(rad):
        with rasterio.open(rad) as s:
            per_window = []
            for (r, c) in windows:
                if r + 512 > s.height or c + 512 > s.width:
                    continue
                w = s.read(1, window=((r, r + 512), (c, c + 512))).astype(np.float64)
                w = np.where(w > 0, w, np.nan)
                per_window.append(AQ.stripe_spectrum(w))
            if per_window:
                spec["geodawn_K_radiometric_u8"] = {
                    "source": rad,
                    "windows": per_window,
                    "median_share_near_ky_axis": float(np.median([w["share_within_15deg_of_ky_axis"] for w in per_window])),
                    "median_share_near_kx_axis": float(np.median([w["share_within_15deg_of_kx_axis"] for w in per_window])),
                }
    out["spectral_striping"] = spec
    for k, v in spec.items():
        print("spectrum %-26s median ky-axis %.4f  kx-axis %.4f"
              % (k, v["median_share_near_ky_axis"], v["median_share_near_kx_axis"]))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, allow_nan=False)
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
