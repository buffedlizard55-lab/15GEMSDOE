#!/usr/bin/env python
"""Pre-registered evaluation of detector fields that use new information.

Registered before the numbers were looked at:

  * Same hide-and-recover protocol as ``scripts/run_holdout.py``: withhold whole
    fault segments, rebuild every catalogue-derived feature from what stays
    visible, score ``dti(pred, truth=hidden, mask=visible, valid=footprint)``.
  * Stage 1 tunes the operating point (emitted area x thinning x ridge width) per
    field on one withholding draw (rule ``random``, seed 0).
  * Stage 2 re-runs the frozen winner on all four withholding rules.
  * Decision rule: a *new-information* field is promoted to a submission
    candidate only if it beats the best field in the incumbent set on stage 1
    **and** on at least three of the four stage-2 rules, with the leakage probe
    below 0.02 on every rule.  Otherwise the honest outcome is "not promoted",
    which is recorded rather than buried.
  * ``catalogue_proximity`` is kept in the table as the reference arm.  It is a
    leakage-controlled control, not a candidate: it knows where the catalogue is.

Writes ``docs/evidence/holdout_new_fields.json``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import sys
import time
from typing import Dict, List

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.gems import fields as F              # noqa: E402
from src.gems import fields_ext as FX         # noqa: E402
from src.gems import holdout as H             # noqa: E402
from src.gems.metric import FastDTI           # noqa: E402

_spec = importlib.util.spec_from_file_location("run_holdout", os.path.join(HERE, "run_holdout.py"))
RH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RH)                   # type: ignore[union-attr]

NEW_FIELDS = ("conj_mag_gravity",
              # NEW: Multi-scale curvature (Hypothesis 5)
              "curv_multiscale_sum", "curv_multiscale_max", "curv_multiscale_prod",
              # NEW: Magnetic ASA (Hypothesis 6)
              "mag_asa", "mag_asa_edge", "conj_mag_asa_edge",
              # NEW: Gravity terrain correction (Hypothesis 7)
              "grav_tc_edge", "conj_grav_tc_edge")
STAGE1_AREAS = (50_000, 100_000, 200_000, 400_000, 800_000)
RULES = ("random", "short", "isolated", "long")


def build_all(data_dir: str, visible: np.ndarray, valid: np.ndarray, aux_dir: str,
              cache_dir: str, tag: str, sigma: float = 1.0) -> Dict[str, np.ndarray]:
    base = F.build_fields(os.path.join(data_dir, "training_features.tif"), visible,
                          valid, cache_dir=cache_dir, tag=tag, sigma=sigma)
    aux = FX.build_aux_fields(aux_dir, valid, sigma=sigma, cache_dir=cache_dir)
    out: Dict[str, np.ndarray] = {**base, **aux}
    for name, parts in FX.CONJUNCTIONS.items():
        missing = [p for p in parts if p not in out]
        if missing:
            continue
        out[name] = FX.conjunction(base, aux, parts, valid)
    for k in list(out):
        out[k] = np.where(valid, out[k], 0.0).astype(np.float32)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data", "raw"))
    ap.add_argument("--aux-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--cache-dir", default="/tmp/gems_fields")
    ap.add_argument("--segments", default="/tmp/segments.json")
    ap.add_argument("--fraction", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--collar-px", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "evidence",
                                                  "holdout_new_fields.json"))
    args = ap.parse_args()

    t0 = time.time()
    lab, valid = RH.load_inputs(args.data_dir)
    recs, seg_ids, n_comp = RH.get_segments(lab, args.segments)
    print("catalogue: %d components, %d segments" % (n_comp, len(recs)), flush=True)

    ev: Dict[str, object] = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "protocol": {
            "withhold_fraction": args.fraction, "seed": args.seed,
            "collar_px": args.collar_px, "stage1_areas_px": list(STAGE1_AREAS),
            "scoring": "dti(pred, truth=hidden segments, mask=visible catalogue, valid=footprint)",
            "promotion_rule": ("beat the incumbent best on stage 1 and on >=3 of the 4 "
                              "stage-2 rules, leakage probe < 0.02 everywhere"),
            "new_information": {
                "rad_alteration": "GeoDAWN contractor ratio grids Th/K and U/K (K enrichment plus U mobilisation)",
                "rad_uth_anomaly": "GeoDAWN contractor U/Th ratio grid",
                "tmi150_edge": "edge magnitude of the upward-continued TMI (150 m)",
                "rad_k_edge": "edge magnitude of the potassium channel",
                "conj_*": "geometric-mean conjunction (>=2 independent sensor families must agree)",
            },
        },
        "catalogue": {"n_components": n_comp, "n_segments": len(recs),
                      "label_pixels": int((lab > 0).sum()), "valid_pixels": int(valid.sum())},
        "stage1": {}, "stage2": {},
    }

    tune_rule, tune_seed = "random", args.seed
    withheld = H.choose_withheld(recs, tune_rule, fraction=args.fraction, seed=tune_seed)
    ho = H.build_holdout(lab, seg_ids, withheld, valid, collar_px=args.collar_px)
    probe = H.leakage_probe(ho)
    fields = build_all(args.data_dir, ho["visible"], valid, args.aux_dir,
                       args.cache_dir, tag=tune_rule)
    scorer = FastDTI(ho["truth"], mask=ho["mask"], valid=valid)
    print("[stage1] truth %d px, mask %d px, leakage %.4f, fields %d (%.0fs)"
          % (ho["truth_pixels"], ho["mask_pixels"], probe["dilate1_dti"],
             len(fields), time.time() - t0), flush=True)

    best: Dict[str, Dict[str, object]] = {}
    for fname in sorted(fields):
        rows = RH.evaluate_policy(fields[fname], scorer, STAGE1_AREAS,
                                  nms_grid=(0, 1), width_grid=(1,))
        best[fname] = rows[0] if rows else {"dti": 0.0}
        ev["stage1"][fname] = best[fname]
        print("   %-24s best %.5f  area %-8s nms %s  (%.0fs)"
              % (fname, best[fname].get("dti", 0.0), best[fname].get("target_area_px"),
                 best[fname].get("nms_radius"), time.time() - t0), flush=True)
    ev["stage1"]["_leakage_probe_dilate1_dti"] = probe["dilate1_dti"]

    incumbents = [f for f in F.FIELDS if f != "catalogue_proximity"]
    inc_best = max(incumbents, key=lambda f: best[f].get("dti", 0.0))
    new_best = max(NEW_FIELDS, key=lambda f: best[f].get("dti", 0.0))
    ev["stage1_summary"] = {
        "incumbent_best_field": inc_best, "incumbent_best_dti": best[inc_best].get("dti", 0.0),
        "new_best_field": new_best, "new_best_dti": best[new_best].get("dti", 0.0),
        "reference_control_catalogue_proximity_dti": best["catalogue_proximity"].get("dti", 0.0),
    }
    print("[stage1] incumbent %s %.5f ; new %s %.5f ; control %.5f"
          % (inc_best, best[inc_best].get("dti", 0.0), new_best,
             best[new_best].get("dti", 0.0),
             best["catalogue_proximity"].get("dti", 0.0)), flush=True)

    # ---- stage 2: the frozen winner on all four rules ----------------------
    winners = {"incumbent": inc_best, "new": new_best}
    stage2: Dict[str, object] = {}
    for label, fname in winners.items():
        per_rule = {}
        for rule in RULES:
            wh = H.choose_withheld(recs, rule, fraction=args.fraction, seed=tune_seed)
            ho_r = H.build_holdout(lab, seg_ids, wh, valid, collar_px=args.collar_px)
            probe_r = H.leakage_probe(ho_r)
            f_r = build_all(args.data_dir, ho_r["visible"], valid, args.aux_dir,
                            args.cache_dir, tag=rule)
            sc_r = FastDTI(ho_r["truth"], mask=ho_r["mask"], valid=valid)
            rows = RH.evaluate_policy(f_r[fname], sc_r, STAGE1_AREAS,
                                      nms_grid=(0, 1), width_grid=(1,))
            top = rows[0] if rows else {"dti": 0.0}
            per_rule[rule] = {"field": fname, "dti": top.get("dti", 0.0),
                              "emitted_px": top.get("emitted_px"),
                              "target_area_px": top.get("target_area_px"),
                              "truth_pixels": ho_r["truth_pixels"],
                              "leakage_probe_dilate1_dti": probe_r["dilate1_dti"]}
            print("[stage2 %-9s %-22s] truth %5d  leakage %.4f  dti %.5f (%.0fs)"
                  % (label, fname, ho_r["truth_pixels"], probe_r["dilate1_dti"],
                     top.get("dti", 0.0), time.time() - t0), flush=True)
        stage2[label] = per_rule
    ev["stage2"] = stage2

    inc = stage2["incumbent"]
    new = stage2["new"]
    wins = sum(1 for r in RULES if new[r]["dti"] > inc[r]["dti"])
    leak_ok = all(new[r]["leakage_probe_dilate1_dti"] < 0.02 for r in RULES)
    promoted = bool(best[new_best].get("dti", 0.0) > best[inc_best].get("dti", 0.0)
                    and wins >= 3 and leak_ok)
    ev["verdict"] = {
        "new_field": new_best, "incumbent_field": inc_best,
        "rules_won_by_new": wins, "rules_tested": len(RULES),
        "leakage_ok": leak_ok,
        "promoted": promoted,
        "reason": ("new-information field beat the incumbent on stage 1 and on %d/%d "
                   "stage-2 rules with the leakage probe below 0.02" % (wins, len(RULES)))
                  if promoted else
                  ("not promoted: stage-1 incumbent best %.5f vs new best %.5f, "
                   "stage-2 wins %d/%d, leakage_ok=%s"
                   % (best[inc_best].get("dti", 0.0), best[new_best].get("dti", 0.0),
                      wins, len(RULES), leak_ok)),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(ev, fh, indent=1, allow_nan=False)
    print("verdict: %s" % ev["verdict"]["reason"])
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
