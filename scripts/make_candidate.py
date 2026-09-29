#!/usr/bin/env python
"""Emit the promoted new-information candidate, validate it, and gate it.

Policy (frozen by ``docs/evidence/holdout_new_fields_collar3.json`` before this
script ran):

    field          conj_alteration_mag
                   = geometric mean of
                     (a) the GeoDAWN contractor ratio anomaly
                         z(-Th/K) + z(U/K)   (K enrichment, U mobilisation)
                     (b) the magnetic tilt-angle edge magnitude (supplied band)
    thinning       nms_ridge radius 1
    emitted area   100,000 px of the 5,167,373-pixel footprint (1.94 %)

Evidence: stage 1 holdout DTI 0.05302 against the incumbent ``curv_scarp``
0.04015, and 4/4 withholding rules won under a 300 m collar with a leakage
probe of 0.0000.

The file is then run through
  * the contract validator (the checks that produced the platform's
    "Predicted values must be in range [0, 1]" rejection), and
  * the novelty gate against every raster in ``docs/evidence/novelty_audit.json``.

    python scripts/make_candidate.py
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.gems import fields as F          # noqa: E402
from src.gems import fields_ext as FX     # noqa: E402
from src.gems import labeldiff as LD      # noqa: E402
from src.gems import novelty as NV        # noqa: E402
from src.gems.emit import binarise, nms_ridge   # noqa: E402
from src.gems.geotiff import write_float32_geotiff  # noqa: E402

GRID = {"origin_x": 243350.0, "origin_y": 4508550.0,
        "pixel_x": 100.0, "pixel_y": 100.0, "epsg": 32611}

_spec = importlib.util.spec_from_file_location("validate_submission",
                                               os.path.join(HERE, "validate_submission.py"))
VS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VS)              # type: ignore[union-attr]


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data", "raw"))
    ap.add_argument("--aux-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--cache-dir", default="/tmp/gems_fields")
    ap.add_argument("--field", default="conj_alteration_mag")
    ap.add_argument("--area", type=int, default=100_000)
    ap.add_argument("--nms", type=int, default=1)
    ap.add_argument("--tag", default="tso1")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with rasterio.open(os.path.join(args.data_dir, "labels.tif")) as s:
        labels = s.read(1)
        shape = (s.height, s.width)
    with rasterio.open(os.path.join(args.data_dir, "sample_submission.tif")) as s:
        valid = np.isfinite(s.read(1))

    visible = labels > 0
    label_free = valid & (LD.distance_to_labels(visible) > 3.0)   # outside the 300 m free zone
    print("chargeable zone %d px of %d footprint" % (label_free.sum(), valid.sum()), flush=True)
    print("building fields (full catalogue visible) ...", flush=True)
    t0 = time.time()
    base = F.build_fields(os.path.join(args.data_dir, "training_features.tif"),
                          visible, valid, cache_dir=args.cache_dir,
                          tag="candidate", sigma=1.0)
    aux = FX.build_aux_fields(args.aux_dir, valid, cache_dir=args.cache_dir)
    if args.field.startswith("conj_"):
        parts = FX.CONJUNCTIONS[args.field]
        missing = [p for p in parts if p not in base and p not in aux]
        if missing:
            print("missing parts for %s: %s" % (args.field, missing))
            return 1
        score = FX.conjunction(base, aux, parts, valid)
    else:
        score = {**base, **aux}[args.field]
    print("field %s ready (%.0fs)" % (args.field, time.time() - t0), flush=True)

    shaped = nms_ridge(score, args.nms) if args.nms > 0 else score
    flat = shaped[valid & (shaped > 0)]
    k = int(np.clip(flat.size - args.area, 0, flat.size - 1))
    thr = float(np.partition(flat, k)[k]) if flat.size else 1.0
    emitted = binarise(shaped, thr) * valid.astype(np.float32)

    out = np.full(shape, np.nan, dtype=np.float64)
    out[valid] = emitted[valid].astype(np.float64)
    fin = np.isfinite(out)
    assert fin.sum() == int(valid.sum())
    assert out[fin].min() >= 0.0 and out[fin].max() <= 1.0

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = args.out or os.path.join(
        ROOT, "docs", "downloads",
        "gems-%s-%s-%s.tif" % (args.tag, stamp, args.field))
    os.makedirs(os.path.dirname(name), exist_ok=True)
    man = write_float32_geotiff(name, out.tolist(), **GRID)
    digest = sha256_file(name)

    # ---- contract validation (includes the [0, 1] check) -------------------
    res = VS.validate(name, os.path.join(args.data_dir, "sample_submission.tif"))
    ok_contract = bool(res["ok"])

    # ---- novelty gate against every prior raster ---------------------------
    audit = json.load(open(os.path.join(ROOT, "docs", "evidence", "novelty_audit.json")))
    # Stream the priors one at a time: holding 62 x 49 MB arrays at once is what
    # killed the first version of this gate on a 4 GB sandbox.
    with rasterio.open(name) as s:
        cand_arr = s.read(1)
    ch = NV.array_sha256(cand_arr)
    idx = NV.footprint_index(cand_arr.shape, n=200_000)
    cv = cand_arr.ravel()[idx]
    ctop = NV.topk_sets(cand_arr, (10000,))
    cemit = NV.emitted_mask(cand_arr)
    cchg = int((cemit & label_free).sum())
    checks = []
    n = 0
    for rec in audit["files"]:
        p = rec["path"]
        if not os.path.isfile(p) or os.path.realpath(p) == os.path.realpath(name):
            continue
        try:
            with rasterio.open(p) as s:
                a = s.read(1)
        except Exception:                       # noqa: BLE001
            continue
        av = a.ravel()[idx]
        m = np.isfinite(cv) & np.isfinite(av)
        rho = NV.rank_correlation(cv[m], av[m]) if int(m.sum()) > 10 else None
        if rho is not None and not np.isfinite(rho):
            rho = 1.0 if np.array_equal(cv[m], av[m]) else 0.0
        tk = len(ctop[10000] & NV.topk_sets(a, (10000,))[10000]) / 10000.0
        dup = (NV.array_sha256(a) == ch)
        chg = NV.chargeable_overlap(cand_arr, a, label_free)
        near = bool(dup or (rho is not None and rho >= NV.NEAR_DUP_RHO
                            and tk >= NV.NEAR_DUP_TOPK)
                    or (chg is not None and chg["identical"]))
        checks.append({"prior": rec["label"], "array_identity": bool(dup),
                       "spearman_rho": rho, "topk": {"top10000": tk},
                       "chargeable": chg, "near_duplicate": near})
        del a, av
        n += 1
        if n % 10 == 0:
            print("  gated against %d priors ..." % n, flush=True)

    verdict = {"candidate": os.path.abspath(name), "candidate_array_sha256": ch,
               "mechanism": None, "checks": checks,
               "ok": not any(c["array_identity"] or c["near_duplicate"] for c in checks)}
    if not verdict["ok"]:
        first = next(c for c in checks if c["array_identity"] or c["near_duplicate"])
        verdict["refused_because"] = ("duplicate of %s (array_identity=%s, rho=%s, top10k=%.3f)"
                                     % (first["prior"], first["array_identity"],
                                        first["spearman_rho"], first["topk"]["top10000"]))
    dupes = [c for c in verdict["checks"]
             if c["array_identity"] or c["near_duplicate"]]
    chargeable_max = max([c["chargeable"]["jaccard"] for c in verdict["checks"]
                          if c.get("chargeable")] or [0.0])
    closest = sorted([c for c in verdict["checks"] if c["spearman_rho"] is not None],
                     key=lambda c: -c["spearman_rho"])[:3]

    note = ("15GEMSDOE TSO-1: conjunction of GeoDAWN contractor Th/K and U/K "
            "radiometric alteration with the magnetic tilt-angle edge; 100k px, nms 1. "
            "Holdout DTI 0.05302 vs 0.04015 for the previous best, 4/4 withholding rules. "
            "Uses public-domain GeoDAWN data (USGS data release DOI 10.5066/P93LGLVQ, "
            "CC0). Known artefact: the thin emitted lines carry a 2-row survey-fabric "
            "periodicity, measured and published in the repository. SHA-256 %s" % digest[:8])
    manifest = {
        "file": os.path.relpath(name, ROOT),
        "sha256": digest,
        "bytes": man["bytes"],
        "generated_utc": stamp,
        "grid": GRID,
        "shape": list(shape),
        "field": args.field,
        "parts": list(FX.CONJUNCTIONS.get(args.field, ())),
        "area_px": args.area,
        "nms_radius": args.nms,
        "threshold": thr,
        "emitted_px": int(emitted.sum()),
        "chargeable_px": cchg,
        "chargeable_share_of_emitted": (float(cchg / emitted.sum())
                                        if emitted.sum() else None),
        "finite_px": int(fin.sum()),
        "bounds": [243350.0, 4135550.0, 572550.0, 4508550.0],
        "min": float(out[fin].min()),
        "max": float(out[fin].max()),
        "emitted_fraction_of_footprint": float(emitted.sum() / valid.sum()),
        "evidence": "docs/evidence/holdout_new_fields_collar3.json",
        "new_information": ("GeoDAWN contractor Th/K and U/K ratio grids "
                            "(DOI 10.5066/P93LGLVQ, USGS public domain); no earlier "
                            "group submission used the ratios or a multi-sensor "
                            "conjunction"),
        "contract_ok": ok_contract,
        "contract_checks": {k: v["passed"] for k, v in res["checks"].items()},
        "novelty_gate_ok": bool(verdict["ok"]),
        "chargeable_jaccard_max_vs_priors": float(chargeable_max),
        "novelty_closest_priors": closest,
        "novelty_duplicates": dupes,
        "suggested_name": os.path.basename(name),
        "suggested_note": note,
    }
    with open(name + ".manifest.json", "w") as fh:
        json.dump(manifest, fh, indent=1)
    json.dump(res, open(os.path.join(ROOT, "docs", "evidence", "submission_validation.json"), "w"), indent=1)

    print("\nfile      %s" % name)
    print("sha256    %s" % digest)
    print("emitted   %d px (%.3f%% of footprint)" % (manifest["emitted_px"],
                                                     100 * manifest["emitted_fraction_of_footprint"]))
    print("contract  %s" % ("PASS" if ok_contract else "FAIL"))
    print("chargeable %d px (%.3f of emitted); max chargeable Jaccard vs any prior %.4f"
          % (cchg, cchg / max(1, manifest["emitted_px"]), chargeable_max))
    print("novelty   %s" % ("PASS (no duplicate or near-duplicate)" if verdict["ok"]
                            else "REFUSED: %s" % verdict.get("refused_because")))
    for c in closest:
        print("  closest prior %-58s rho %.5f top10k %.3f"
              % (c["prior"][-58:], c["spearman_rho"], c["topk"]["top10000"]))
    print("note      %s" % note)
    return 0 if (ok_contract and verdict["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
