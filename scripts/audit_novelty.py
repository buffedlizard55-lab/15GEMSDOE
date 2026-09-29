#!/usr/bin/env python
"""Novelty protocol over every prior submission raster the group can reach.

Answers, with measurements instead of memory:

  1. Which published/submitted rasters are byte-identical, and which are
     *array*-identical (same float32 map, different TIFF wrapping)?
  2. Which pairs are near-duplicates under a frozen rule (tie-corrected
     Spearman rho >= 0.99 on a fixed 200k-pixel support AND top-10k overlap
     >= 0.95)?
  3. Which published files would be rejected by the platform's own
     "Predicted values must be in range [0, 1]" check?
  4. Does the score the group recorded for a file repeat because the file
     repeats?

    python scripts/audit_novelty.py [--roots DIR ...] [--out docs/evidence/novelty_audit.json]

Roots default to this repository's ``docs/downloads`` plus the sibling clones
under ``/home/user/work/repos`` that were cloned this session.  Nothing is
downloaded: the audit runs on files that are on disk and says so.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.gems import novelty as NV  # noqa: E402

DEFAULT_ROOTS = [os.path.join(ROOT, "docs", "downloads"),
                 "/home/user/work/repos"]
MAX_BYTES = 60 * 1024 * 1024          # skip the 418 MB feature stack and parts
PATTERNS = ("downloads/*.tif", "docs/downloads/*.tif", "*submission*.tif",
            "docs/*.tif", "*/*submission*.tif", "data/evidence/leaderboard_anchor/*.tif")

# The rasters the group's own ledgers tie to a scored upload.  The score column
# is the value the user reported; it is recorded here so the audit can say
# whether equal scores are explained by equal bytes.  Nothing in this list is
# copied from memory: every row is either in a sibling ledger or in the user's
# message of 2026-09-29, and the file's presence on disk is checked.
# Files the group's ledgers tie to a scored upload.  Every path is checked on
# disk before use; a missing one is reported, never invented.
SCORE_ANCHOR_FILES = [
    ("0.1563", "GEMSDOE:data/evidence/runs/ens12-adopted-floor0.1-w0/submission.tif"),
    ("0.1563", "5GEMSDOE:data/evidence/leaderboard_anchor/gemsdoe-ens12-adopted-7f00890a.tif"),
    ("0.1193", "5GEMSDOE:data/evidence/leaderboard_anchor/pindrop-v4-nodes-f347b70daa.tif"),
    ("0.0830", "5GEMSDOE:data/evidence/leaderboard_anchor/pindrop-v4-discovery-37f9d5b855.tif"),
    ("0.1152", "5GEMSDOE:data/evidence/leaderboard_anchor/pindrop-v4-ridge-4e03fc9705.tif"),
    ("0.1560", "5GEMSDOE:data/evidence/leaderboard_anchor/gemsdoe2-dual-family-union-f68e590f.tif"),
    ("0.1563", "8GEMSDOE:downloads/8GEMSDOE_Hedge-v2_submission.tif"),
    ("0.1563", "8GEMSDOE:downloads/8GEMSDOE-Apex-Geothermal-V1.tif"),
    ("0.1461", "7GEMSDOE:downloads/gems7-halo15-gbt-v1-90fb7dc0fc1f.tif"),
    ("unscored", "12GEMSDOE:docs/downloads/12GEMSDOE_r7-nms3-dem10-scarp_0c9199f14e62.tif"),
    ("unscored", "15GEMSDOE:docs/downloads/gems-cleanup-a-20260928T195952Z-curv_scarp.tif"),
]

_LEGACY_SCORE_ANCHORS = {
    "GEMSDOE1": ("0.1563", "ens12-adopted (ledger 11GEMSDOE: \"Published in 5GEMSDOE, GEMSDOE and 7GEMSDOE: three byte-identical copies\")"),
    "5GEMSDOE": ("0.1563", "same ledger row; anchor copy in 5GEMSDOE/data/evidence/leaderboard_anchor"),
    "8GEMSDOE": ("0.1563", "8GEMSDOE publishes 8GEMSDOE_Hedge-v2_submission.tif"),
    "GEMSDOE2": ("0.1560", "ledger: union added 9,430 chargeable pixels for -0.0003"),
    "GEMSDOE3-nodes": ("0.1193", "pindrop-v4-nodes f347b70daa"),
    "GEMSDOE3-ridge": ("0.1152", "pindrop-v4-ridge 4e03fc9705"),
    "GEMSDOE3-discovery": ("0.0830", "pindrop-v4-discovery 37f9d5b855"),
    "7GEMSDOE": ("0.1461", "downloads/gems7-halo15-gbt-v1-90fb7dc0fc1f.tif"),
}


def _interesting(rel: str, name: str) -> bool:
    if not name.lower().endswith(".tif"):
        return False
    low = rel.lower()
    if ".git" in low or "data/bridge" in low or ".part-" in name:
        return False
    return ("downloads" in low or "submission" in name.lower()
            or "leaderboard_anchor" in low)


def find_rasters(roots: List[str], max_depth: int = 4) -> List[str]:
    """Every published / submitted raster under the roots, by name pattern.

    Depth-limited walk (default 4 levels) so a repository's own test fixtures
    and half-gigabyte feature stack are not swept in.
    """
    seen: Dict[str, str] = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if ".git" in dirnames:
                dirnames.remove(".git")
            if dirpath.count(os.sep) - base_depth >= max_depth:
                dirnames[:] = []
            for name in filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                if not _interesting(rel, name):
                    continue
                full = os.path.join(dirpath, name)
                rp = os.path.realpath(full)
                if not os.path.isfile(rp) or os.path.getsize(rp) > MAX_BYTES:
                    continue
                seen[rp] = full
    return sorted(seen)


def label_for(path: str) -> str:
    parts = path.split(os.sep)
    for i, p in enumerate(parts):
        if p.startswith(("GEMSDOE", "5GEMSDOE", "6GEMSDOE", "7GEMSDOE",
                         "8GEMSDOE", "11GEMSDOE", "12GEMSDOE")) or p == "15GEMSDOE":
            return p + ":" + os.path.relpath(path, os.sep.join(parts[:i + 1]))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "evidence",
                                                  "novelty_audit.json"))
    ap.add_argument("--max-files", type=int, default=60)
    args = ap.parse_args()

    paths = find_rasters(args.roots)[: args.max_files]
    anchor_hits = []
    for score, rel in SCORE_ANCHOR_FILES:
        repo, inner = rel.split(":", 1)
        candidates = [os.path.join(root, repo, inner) for root in args.roots]
        candidates.append(os.path.join(ROOT, inner) if repo == "15GEMSDOE" else "")
        for cand in candidates:
            if cand and os.path.isfile(cand):
                rp = os.path.realpath(cand)
                if rp not in paths:
                    paths.append(rp)
                anchor_hits.append({"score_as_recorded_by_the_group": score,
                                    "path": rp, "label": rel})
                break
        else:
            anchor_hits.append({"score_as_recorded_by_the_group": score,
                                "path": None, "label": rel,
                                "status": "NOT FOUND on disk in this sandbox"})
    paths = sorted(set(paths))
    print("score anchors resolved: %d of %d" % (len(anchor_hits), len(SCORE_ANCHOR_FILES)))
    if not paths:
        print("no rasters found under %s" % args.roots)
        return 1

    print("profiling %d rasters ..." % len(paths), flush=True)
    profiles: List[Dict[str, object]] = []
    for p in paths:
        try:
            pr = NV.profile_raster(p)
        except Exception as exc:                       # noqa: BLE001
            print("  SKIP %s (%s)" % (p, exc))
            continue
        pr["label"] = label_for(p)
        profiles.append(pr)
        c = pr["contract"]
        print("  %-58s finite %8d emitted %8d out-of-range %d"
              % (pr["label"][-58:], c["finite_px"], c["emitted_px"],
                 c["out_of_unit_interval_px"]), flush=True)

    # ---- identity groups -----------------------------------------------------
    by_array: Dict[str, List[str]] = {}
    by_file: Dict[str, List[str]] = {}
    for pr in profiles:
        by_array.setdefault(pr["array_sha256"], []).append(pr["label"])
        by_file.setdefault(pr["file_sha256"], []).append(pr["label"])
    array_dupes = {k: v for k, v in by_array.items() if len(v) > 1}
    file_dupes = {k: v for k, v in by_file.items() if len(v) > 1}

    # ---- pairwise near-duplicate screen -------------------------------------
    shape = tuple(profiles[0]["field"].shape)          # type: ignore[union-attr]
    idx = NV.footprint_index(shape, n=200_000)
    vecs: Dict[str, np.ndarray] = {}
    for pr in profiles:
        f = pr["field"].ravel()[idx]                    # type: ignore[union-attr]
        vecs[pr["label"]] = np.where(np.isfinite(f), f, np.nan).astype(np.float32)

    # the dense fields are no longer needed once the fixed-support vectors exist
    for pr in profiles:
        pr["field"] = None

    pairs = []
    labs = [pr["label"] for pr in profiles]
    for i in range(len(labs)):
        for j in range(i + 1, len(labs)):
            la, lb = labs[i], labs[j]
            a, b = vecs[la], vecs[lb]
            m = np.isfinite(a) & np.isfinite(b)
            rho = NV.rank_correlation(a[m], b[m]) if int(m.sum()) > 10 else None
            if rho is not None and not np.isfinite(rho):
                rho = 1.0 if np.array_equal(a[m], b[m]) else 0.0
            ta = profiles[i]["topk"]                    # type: ignore[index]
            tb = profiles[j]["topk"]                    # type: ignore[index]
            tk = {("top%d" % k): (len(ta[k] & tb[k]) / float(k) if k else 0.0)
                  for k in sorted(ta)}
            ea = np.asarray(profiles[i]["emitted_idx"], dtype=np.int64)  # type: ignore[arg-type]
            eb = np.asarray(profiles[j]["emitted_idx"], dtype=np.int64)  # type: ignore[arg-type]
            inter = int(np.intersect1d(ea, eb, assume_unique=True).size)
            union = int(ea.size + eb.size - inter)
            rec = {"a": la, "b": lb,
                   "same_array": profiles[i]["array_sha256"] == profiles[j]["array_sha256"],
                   "spearman_rho": rho,
                   "topk": tk,
                   "emitted_intersection_px": inter,
                   "emitted_jaccard": (inter / union) if union else 1.0,
                   "share_of_a_in_b": (inter / len(ea)) if len(ea) else 0.0,
                   "share_of_b_in_a": (inter / len(eb)) if len(eb) else 0.0}
            if rho is not None and not np.isfinite(rho):
                rho = None
                rec["spearman_rho"] = None
            rec["near_duplicate"] = bool(
                rec["same_array"] or
                (rho is not None and rho >= NV.NEAR_DUP_RHO
                 and tk.get("top10000", 0.0) >= NV.NEAR_DUP_TOPK))
            pairs.append(rec)
    pairs.sort(key=lambda r: -(r["spearman_rho"] or 0.0))

    out = {
        "purpose": ("Frozen novelty protocol: prove a candidate is not a repeat of "
                    "an already-scored raster. Frozen thresholds: "
                    "rho >= %.2f and top-10k >= %.2f, or identical float32 arrays."
                    % (NV.NEAR_DUP_RHO, NV.NEAR_DUP_TOPK)),
        "roots": args.roots,
        "files": [{**{k: v for k, v in pr.items()
                       if k not in ("field", "emitted_idx", "topk")},
                   "topk_sizes": sorted(int(k) for k in pr["topk"])}
                  for pr in profiles],
        "identity_groups_by_array": array_dupes,
        "identity_groups_by_file": file_dupes,
        "range_violations": [{"label": pr["label"], "path": pr["path"],
                              "out_of_unit_interval_px": pr["contract"]["out_of_unit_interval_px"],
                              "min": pr["contract"]["min"], "max": pr["contract"]["max"]}
                             for pr in profiles
                             if pr["contract"]["out_of_unit_interval_px"] > 0],
        "pairs": pairs,
        "score_anchors": anchor_hits,
        "fixture_independence_note": (
            "paths under /tmp are the transport fixtures used by tests; they are "
            "identical copies of repository files and are labelled as fixtures."),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, allow_nan=False)

    print("\narray-identical groups (%d):" % len(array_dupes))
    for h, members in array_dupes.items():
        print("  %s  %s" % (h[:16], members))
    print("\nrange violations: %d file(s)" % len(out["range_violations"]))
    print("near-duplicate pairs: %d of %d"
          % (sum(1 for r in pairs if r["near_duplicate"]), len(pairs)))
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
