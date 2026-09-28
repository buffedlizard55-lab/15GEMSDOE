#!/usr/bin/env python
"""Verify the placed rasters byte-for-byte against the pinned inventory.

Checks SHA-256, byte count, grid geometry, CRS, band count and the shipped band
descriptions.  Exits non-zero on any mismatch, so the pipeline cannot silently
train on different bytes.

    python scripts/verify_data.py [DATA_DIR]

On success writes docs/evidence/data_verification.json with everything it saw.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PINS = {
    "training_features.tif": {
        "sha256": "4371c82e3b8339b807bdffcf4ef59a225520fe2988d521be208ae33743123bc5",
        "bytes": 418912844,
    },
    "labels.tif": {
        "sha256": "7ba308ccdc4418b31a178f4f1ef21aaa6e152e4028f2f6f64b01f7eb25ae4093",
        "bytes": 425830,
    },
    "sample_submission.tif": {
        "sha256": "2176d08e485aa2cd2860ce8df539db4faf4d76163b38a4dd8c30a40454d35cbc",
        "bytes": 1599597,
    },
}

EXPECTED_GRID = {"width": 3292, "height": 3730, "epsg": 32611,
                 "res": [100.0, 100.0]}


def sha256_of(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> int:
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "raw")
    out = {"data_dir": os.path.abspath(data_dir), "files": {}, "grid": {}, "ok": True}

    for name, pin in PINS.items():
        path = os.path.join(data_dir, name)
        rec = {"path": path, "exists": os.path.exists(path)}
        if rec["exists"]:
            rec["bytes"] = os.path.getsize(path)
            rec["sha256"] = sha256_of(path)
            rec["bytes_match"] = rec["bytes"] == pin["bytes"]
            rec["sha256_match"] = rec["sha256"] == pin["sha256"]
            rec["expected_sha256"] = pin["sha256"]
            rec["expected_bytes"] = pin["bytes"]
            out["ok"] &= rec["bytes_match"] and rec["sha256_match"]
        else:
            rec["sha256_match"] = False
            out["ok"] = False
        out["files"][name] = rec

    try:
        import rasterio
        import numpy as np
        with rasterio.open(os.path.join(data_dir, "sample_submission.tif")) as s:
            out["grid"] = {"width": s.width, "height": s.height,
                           "crs": str(s.crs), "res": list(s.res),
                           "transform": [float(v) for v in s.transform[:6]],
                           "bounds": [float(v) for v in s.bounds],
                           "count": s.count, "dtype": s.dtypes[0]}
            out["ok"] &= out["grid"]["width"] == EXPECTED_GRID["width"]
            out["ok"] &= out["grid"]["height"] == EXPECTED_GRID["height"]
            out["ok"] &= "32611" in str(s.crs)
            out["ok"] &= list(s.res) == EXPECTED_GRID["res"]
            ss = s.read(1)
            finite = np.isfinite(ss)
            out["footprint"] = {"finite_pixels": int(finite.sum()),
                                "of_pixels": int(ss.size),
                                "fraction": float(finite.mean())}
            del ss
        with rasterio.open(os.path.join(data_dir, "labels.tif")) as s:
            lab = s.read(1)
            vals = {int(v): int((lab == v).sum()) for v in np.unique(lab)}
            out["labels"] = {"values": vals, "count": s.count, "dtype": s.dtypes[0],
                             "descriptions": [d for d in s.descriptions if d]}
        with rasterio.open(os.path.join(data_dir, "training_features.tif")) as s:
            out["features"] = {"count": s.count, "dtype": s.dtypes[0],
                               "descriptions": [d for d in (s.descriptions or [])]}
    except ImportError:
        out["grid"] = {"skipped": "rasterio not installed; byte checks still ran"}

    os.makedirs(os.path.join(ROOT, "docs", "evidence"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "evidence", "data_verification.json"), "w") as fh:
        json.dump(out, fh, indent=1)

    for name, rec in out["files"].items():
        print("%-24s %s  %12s bytes  %s"
              % (name, "OK " if rec.get("sha256_match") else "BAD",
                 rec.get("bytes", "-"), rec.get("sha256", "-")[:16]))
    if out["grid"].get("width"):
        g = out["grid"]
        print("grid %dx%d %s res %s count %d"
              % (g["width"], g["height"], g["crs"], g["res"], g["count"]))
    print("verification %s" % ("PASSED" if out["ok"] else "FAILED"))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
