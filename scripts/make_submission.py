#!/usr/bin/env python
"""Emit a competition-ready GeoTIFF from the holdout-selected policy.

The policy (detector field, emitted area, thinning radius, ridge width) is read
from docs/evidence/holdout_results.json -- it is *selected on the holdout*, never
eyeballed, and the file name records the evidence that produced it.

Output contract, from the problem description's "Submission format" section:

  * EPSG:32611, 100 m, same bounds as the training data
  * single band, float32
  * every value in [0, 1]
  * NaN outside the data footprint

    python scripts/make_submission.py --data-dir /tmp/gemsdata \
        --out docs/downloads/<name>.tif
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.gems import fields as F                      # noqa: E402
from src.gems.emit import binarise, nms_ridge, orient_ridge  # noqa: E402
from src.gems.geotiff import write_float32_geotiff    # noqa: E402

GRID = {"origin_x": 243350.0, "origin_y": 4508550.0,
        "pixel_x": 100.0, "pixel_y": 100.0, "epsg": 32611}


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("GEMS_DATA", "data/raw"))
    ap.add_argument("--evidence", default=os.path.join(ROOT, "docs", "evidence",
                                                       "holdout_results.json"))
    ap.add_argument("--field", default=None, help="override the selected detector")
    ap.add_argument("--area", type=int, default=None, help="override emitted pixels")
    ap.add_argument("--out", default=None)
    ap.add_argument("--tag", default="a")
    args = ap.parse_args()

    ev = json.load(open(args.evidence)) if os.path.exists(args.evidence) else {}
    pol = ev.get("selected_policy", {})
    field = args.field or pol.get("field", "mag_tilt")
    area = args.area or pol.get("target_area_px", 400_000)
    nms = int(pol.get("nms_radius", 1))
    width = int(pol.get("ridge_width", 1))
    stage1_dti = pol.get("stage1_dti")

    import rasterio
    with rasterio.open(os.path.join(args.data_dir, "labels.tif")) as s:
        labels = s.read(1)
        transform = s.transform
        shape = (s.height, s.width)
    with rasterio.open(os.path.join(args.data_dir, "sample_submission.tif")) as s:
        valid = np.isfinite(s.read(1))
        assert (s.height, s.width) == shape, "grid mismatch between rasters"
        bounds = s.bounds

    # On the real task the whole training catalogue is the mask, so the visible
    # catalogue is simply `labels`; fields are built with visible=labels.
    visible = labels > 0
    print("building detector fields (full catalogue visible) ...", flush=True)
    t0 = time.time()
    flds = F.build_fields(os.path.join(args.data_dir, "training_features.tif"),
                          visible, valid, cache_dir="/tmp/gems_fields",
                          tag="submission", sigma=1.0)
    score = flds[field]
    shaped = nms_ridge(score, nms) if nms > 0 else score
    shaped = orient_ridge(shaped, width) if (nms > 0 or width > 1) else shaped

    flat = shaped[valid & (shaped > 0)]
    k = int(np.clip(flat.size - area, 0, flat.size - 1))
    thr = float(np.partition(flat, k)[k]) if flat.size else 1.0
    emitted = binarise(shaped, thr) * valid.astype(np.float32)

    # contract: [0,1] finite inside the footprint, NaN outside
    out = np.full(shape, np.nan, dtype=np.float64)
    out[valid] = emitted[valid].astype(np.float64)
    finite = np.isfinite(out)
    assert finite.sum() == int(valid.sum())
    assert out[finite].min() >= 0.0 and out[finite].max() <= 1.0

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = args.out or os.path.join(
        ROOT, "docs", "downloads",
        "gems-cleanup-%s-%s-%s.tif" % (args.tag, stamp, field))
    os.makedirs(os.path.dirname(name), exist_ok=True)
    rows = out.tolist()
    man = write_float32_geotiff(name, rows, **GRID)

    digest = sha256_file(name)
    note = ("15GEMSDOE clean-up %s | %s ridge | area %.1e px (%.2f%% of footprint) | "
            "nms %d width %d | holdout DTI %s | %s"
            % (args.tag.upper(), field, area, 100.0 * emitted.sum() / valid.sum(),
               nms, width, ("%.5f" % stage1_dti) if stage1_dti else "n/a", digest[:8]))

    manifest = {
        "file": os.path.relpath(name, ROOT),
        "sha256": digest,
        "bytes": man["bytes"],
        "generated_utc": stamp,
        "grid": GRID,
        "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
        "shape": list(shape),
        "policy": {"field": field, "area_px": area, "nms_radius": nms,
                   "ridge_width": width, "threshold": thr,
                   "stage1_holdout_dti": stage1_dti,
                   "evidence": os.path.relpath(args.evidence, ROOT)},
        "emitted_px": int(emitted.sum()),
        "emitted_fraction_of_footprint": float(emitted.sum() / valid.sum()),
        "finite_px": int(finite.sum()),
        "min": float(out[finite].min()), "max": float(out[finite].max()),
        "nan_outside_footprint": True,
        "suggested_note": note,
        "suggested_name": os.path.basename(name),
    }
    with open(name + ".manifest.json", "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(json.dumps(manifest, indent=1))
    print("\nnote to paste into the submission form:\n  %s" % note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
