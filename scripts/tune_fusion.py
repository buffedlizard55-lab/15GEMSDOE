#!/usr/bin/env python
"""Choose detector fusion by holdout DTI, not by preference.

The stage-1 run picks the best *single* detector.  This script asks whether
combining detectors beats the best single one, using the same operating-point
grid and the same leakage-controlled holdout, and writes the answer to
docs/evidence/fusion_results.json.

Fusion candidates:
  max_all      elementwise max of all seven fields  (most inclusive)
  max_top3     max of the three best stage-1 fields
  mean_all     elementwise mean of all seven fields (most conservative)
  max_top3_gate  max of the three best, gated by the seismicity prior
                 (a conjunction: emission needs both a structural edge and a
                 seismicity alignment)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.gems import fields as F                                  # noqa: E402
from src.gems import holdout as H                                 # noqa: E402
from src.gems.emit import binarise, budget_thresholds, nms_ridge, orient_ridge  # noqa: E402
from src.gems.metric import FastDTI                               # noqa: E402

AREAS = (100_000, 200_000, 400_000, 800_000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("GEMS_DATA", "data/raw"))
    ap.add_argument("--rule", default="random")
    ap.add_argument("--seed", type=int, default=20260928)
    ap.add_argument("--fraction", type=float, default=0.20)
    ap.add_argument("--segments", default="/tmp/segments.json")
    ap.add_argument("--cache-dir", default="/tmp/gems_fields")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "evidence",
                                                  "fusion_results.json"))
    args = ap.parse_args()

    import rasterio
    lab = rasterio.open(os.path.join(args.data_dir, "labels.tif")).read(1)
    ss = rasterio.open(os.path.join(args.data_dir, "sample_submission.tif")).read(1)
    valid = np.isfinite(ss) & (lab != -1)
    blob = json.load(open(args.segments))
    recs = blob["records"]
    seg_ids = np.load("/tmp/seg_ids.npy")

    withheld = H.choose_withheld(recs, args.rule, fraction=args.fraction, seed=args.seed)
    ho = H.build_holdout(lab, seg_ids, withheld, valid, collar_px=1)
    flds = F.build_fields(os.path.join(args.data_dir, "training_features.tif"),
                          ho["visible"], valid, cache_dir=args.cache_dir,
                          tag=args.rule, sigma=1.0)
    scorer = FastDTI(ho["truth"], mask=ho["mask"], valid=valid)

    order = ["curv_scarp", "mag_tilt", "catalogue_proximity", "seismo_prior",
             "strain_ridge", "grav_grad", "cond_depth"]
    top3 = order[:3]
    stack = np.stack([flds[k] for k in F.FIELDS])
    cands = {
        "max_all": stack.max(axis=0),
        "max_top3": np.stack([flds[k] for k in top3]).max(axis=0),
        "mean_all": stack.mean(axis=0),
        "max_top3_gate": (np.stack([flds[k] for k in top3]).max(axis=0)
                          * flds["seismo_prior"]).astype(np.float32),
    }

    results = {}
    for name, sc in cands.items():
        best = None
        rows = []
        for r in (0, 1, 2):
            thin = nms_ridge(sc, r) if r > 0 else sc
            for wid in (1, 2):
                shaped = orient_ridge(thin, wid) if (r > 0 or wid > 1) else thin
                for area, thr in budget_thresholds(shaped, np.ones_like(shaped, bool), AREAS).items():
                    pred = binarise(shaped, thr)
                    if pred.sum() == 0:
                        continue
                    res = scorer(pred)
                    row = {"nms_radius": r, "ridge_width": wid, "target_area_px": int(area),
                           "emitted_px": res["emitted_px"], "dti": round(res["dti"], 6),
                           "tp_w": round(res["tp_w"], 4), "fp_w": round(res["fp_w"], 4)}
                    rows.append(row)
                    if best is None or row["dti"] > best["dti"]:
                        best = dict(row)
        rows.sort(key=lambda x: -x["dti"])
        results[name] = {"best": best, "top5": rows[:5]}
        print("%-16s best dti %.5f (area %s nms %s width %s)"
              % (name, best["dti"], best["target_area_px"], best["nms_radius"],
                 best["ridge_width"]), flush=True)

    single_best = {"curv_scarp": None, "mag_tilt": None, "catalogue_proximity": None}
    for k in single_best:
        best = None
        sc = flds[k]
        for r in (0, 1, 2):
            thin = nms_ridge(sc, r) if r > 0 else sc
            for wid in (1, 2):
                shaped = orient_ridge(thin, wid) if (r > 0 or wid > 1) else thin
                for area, thr in budget_thresholds(shaped, np.ones_like(shaped, bool), AREAS).items():
                    pred = binarise(shaped, thr)
                    if pred.sum() == 0:
                        continue
                    res = scorer(pred)
                    row = {"nms_radius": r, "ridge_width": wid, "target_area_px": int(area),
                           "emitted_px": res["emitted_px"], "dti": round(res["dti"], 6)}
                    if best is None or row["dti"] > best["dti"]:
                        best = dict(row)
        single_best[k] = best
        print("%-16s best dti %.5f (area %s nms %s width %s)"
              % (k, best["dti"], best["target_area_px"], best["nms_radius"],
                 best["ridge_width"]), flush=True)

    winner = max(results.items(), key=lambda kv: kv[1]["best"]["dti"])
    best_single = max(single_best.items(), key=lambda kv: kv[1]["dti"])
    out = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rule": args.rule, "seed": args.seed, "truth_pixels": ho["truth_pixels"],
        "leakage_probe_dilate1_dti": H.leakage_probe(ho)["dilate1_dti"],
        "fusion": results, "single": single_best,
        "winner_fusion": winner[0], "winner_fusion_dti": winner[1]["best"]["dti"],
        "best_single": best_single[0], "best_single_dti": best_single[1]["dti"],
        "fusion_beats_single": winner[1]["best"]["dti"] > best_single[1]["dti"],
        "areas_swept": list(AREAS),
    }
    json.dump(out, open(args.out, "w"), indent=1)
    print("\nfusion winner %s %.5f vs best single %s %.5f -> fusion beats single: %s"
          % (winner[0], winner[1]["best"]["dti"], best_single[0],
             best_single[1]["dti"], out["fusion_beats_single"]))
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
