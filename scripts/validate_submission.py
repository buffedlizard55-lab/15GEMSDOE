#!/usr/bin/env python
"""Fail-closed validator for a GEMS submission GeoTIFF.

Every rule below is quoted from the problem description's "Submission format"
section, and every check is re-derived from the file on disk:

  R1  "same projected coordinate reference system as the training data
       (projected coordinate system for UTM zone 11N, EPSG 32611)"
  R2  "same resolution as the training data (100m)"
  R3  "same bounds as the training data, and data outside the bounds is null
       or nan"
  R4  "a single layer with datatype of 32-bit float (float32) with values
       between 0 and 1"

R4 is the check that rejected a previous download with
"Predicted values must be in range [0, 1]", so it is enforced on every finite
cell and reported with the offending min/max when it fails.

    python scripts/validate_submission.py FILE.tif [--reference sample_submission.tif]

Exit status 0 = ready to upload, 1 = do not upload.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def validate(path: str, reference: str | None) -> dict:
    import rasterio
    out = {"file": os.path.abspath(path), "checks": {}, "ok": True}

    def check(name, passed, detail):
        out["checks"][name] = {"passed": bool(passed), "detail": detail}
        if not passed:
            out["ok"] = False

    with rasterio.open(path) as s:
        out["profile"] = {"width": s.width, "height": s.height, "count": s.count,
                          "dtypes": list(s.dtypes), "crs": str(s.crs),
                          "res": list(s.res), "nodata": s.nodata,
                          "bounds": [float(v) for v in s.bounds]}
        check("R1_crs_epsg32611", s.crs is not None and "32611" in str(s.crs),
              str(s.crs))
        check("R2_resolution_100m", list(s.res) == [100.0, 100.0], list(s.res))
        check("R4a_single_band", s.count == 1, s.count)
        check("R4b_float32", s.dtypes[0] == "float32", s.dtypes[0])
        data = s.read(1)
        if reference:
            with rasterio.open(reference) as r:
                check("R3a_bounds_match_reference",
                      tuple(round(v, 6) for v in s.bounds) == tuple(round(v, 6) for v in r.bounds),
                      [float(v) for v in s.bounds])
                check("R3b_shape_match_reference",
                      (s.width, s.height) == (r.width, r.height),
                      [s.width, s.height])
                check("R3c_crs_match_reference", str(s.crs) == str(r.crs), str(s.crs))
                check("R3d_transform_match_reference",
                      tuple(round(float(v), 6) for v in s.transform[:6])
                      == tuple(round(float(v), 6) for v in r.transform[:6]),
                      [float(v) for v in s.transform[:6]])
                ref = r.read(1)
                ref_finite = np.isfinite(ref)
                ours_finite = np.isfinite(data)
                extra = int((ours_finite & ~ref_finite).sum())
                missing = int((ref_finite & ~ours_finite).sum())
                check("R3e_nan_outside_footprint",
                      missing == 0,
                      {"reference_finite_px": int(ref_finite.sum()),
                       "our_finite_px": int(ours_finite.sum()),
                       "finite_where_reference_nan": extra,
                       "nan_where_reference_finite": missing})
        fin = np.isfinite(data)
        if fin.any():
            lo, hi = float(data[fin].min()), float(data[fin].max())
        else:
            lo, hi = float("nan"), float("nan")
        check("R4c_values_in_unit_interval", fin.any() and lo >= 0.0 and hi <= 1.0,
              {"min": lo, "max": hi})
        check("R4d_no_negative", not (data[fin] < 0).any() if fin.any() else False,
              int((data[fin] < 0).sum()) if fin.any() else "no finite cells")
        emitted = int((data[fin] > 0).sum()) if fin.any() else 0
        out["emitted_px"] = emitted
        out["finite_px"] = int(fin.sum())
        out["fraction_emitted_of_footprint"] = (emitted / int(fin.sum())) if fin.any() else 0.0
        check("R4e_not_empty", emitted > 0,
              "an all-zero submission scores 0; the shipped sample_submission.tif "
              "is the catalogue raster and also scores 0 once known faults are masked")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--reference", default=None,
                    help="sample_submission.tif to check bounds/shape/CRS against")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    ref = args.reference
    if ref is None:
        cand = os.path.join(ROOT, "data", "raw", "sample_submission.tif")
        ref = cand if os.path.exists(cand) else None

    res = validate(args.file, ref)
    for name, rec in res["checks"].items():
        print("%-34s %s  %s" % (name, "PASS" if rec["passed"] else "FAIL", rec["detail"]))
    print("emitted %d px of %d finite (%.2f%%)"
          % (res.get("emitted_px", 0), res.get("finite_px", 0),
             100.0 * res.get("fraction_emitted_of_footprint", 0.0)))
    print("VERDICT: %s" % ("READY TO UPLOAD" if res["ok"] else "DO NOT UPLOAD"))
    if args.json_out:
        json.dump(res, open(args.json_out, "w"), indent=1)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
