#!/usr/bin/env python
"""Chargeable support: the pixels a submission can actually earn credit for.

Why this exists
---------------
The score only pays for a prediction that sits **outside the free zone** of the
shipped label mask.  Inside 300 m of a known fault the kernel credits nothing,
so two files with completely different rasters can be scored identically.  That
is not a theory: the group's ens12 run and the 8GEMSDOE hedge file have
different arrays and different emitted footprints, tie at 0.1563, and -- as this
script measures -- have *identical* chargeable sets.

Definition used here (metric-grounded, not ad hoc):

    chargeable(x) = pred(x) > 0
                    AND x is inside the footprint
                    AND distance(x, nearest shipped label) > 300 m / 100 m = 3 px

``labeldiff.distance_to_labels`` computes that Euclidean distance in pixels, so
"beyond the kernel" is exactly ``distance > 3``.  (An earlier ad-hoc pass used a
7x7 Chebyshev dilation instead; that is slightly more inclusive.  The Euclidean
definition is the one the published kernel implies, so it is the one persisted
here, and the difference is recorded in the JSON.)

Two files are *chargeably identical* when Jaccard(chargeable) >= 0.95.  That is
a second, independent duplicate mechanism from the byte/array identity in
``docs/evidence/novelty_audit.json``, and it is the one the frozen rho/top-k
rule in ``src/gems/novelty.gate`` cannot see.

    python scripts/audit_chargeable.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.gems import labeldiff as LD     # noqa: E402
from src.gems import novelty as NV       # noqa: E402

POP = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None], axis=1).sum(axis=1)


def main() -> int:
    import rasterio

    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data", "raw"))
    ap.add_argument("--audit",
                    default=os.path.join(ROOT, "docs", "evidence", "novelty_audit.json"))
    ap.add_argument("--out",
                    default=os.path.join(ROOT, "docs", "evidence", "chargeable_support.json"))
    ap.add_argument("--kernel-px", type=float, default=3.0,
                    help="300 m kernel at 100 m pixels")
    ap.add_argument("--identical-jaccard", type=float, default=0.95)
    args = ap.parse_args()

    with rasterio.open(os.path.join(args.data_dir, "labels.tif")) as s:
        labels = s.read(1)
        shape = (s.height, s.width)
    with rasterio.open(os.path.join(args.data_dir, "sample_submission.tif")) as s:
        valid = np.isfinite(s.read(1))
    lab = (labels > 0) & valid
    dist = LD.distance_to_labels(lab)
    free = valid & (dist > args.kernel_px)
    print("footprint %d px | labels %d px | chargeable zone %d px"
          % (valid.sum(), lab.sum(), free.sum()), flush=True)
    del dist

    audit = json.load(open(args.audit))
    recs: List[Dict[str, object]] = []
    bits: Dict[str, np.ndarray] = {}
    t0 = time.time()
    for i, rec in enumerate(audit["files"]):
        path = rec["path"]
        if not os.path.isfile(path):
            continue
        with rasterio.open(path) as s:
            a = s.read(1)
        emitted = NV.emitted_mask(a) & valid
        ch = emitted & free
        packed = np.packbits(ch.ravel())
        bits[rec["label"]] = packed
        recs.append({
            "label": rec["label"],
            "path": path,
            "array_sha256": NV.array_sha256(a)[:16],
            "emitted_px": int(emitted.sum()),
            "chargeable_px": int(ch.sum()),
            "chargeable_share_of_emitted": (float(ch.sum() / emitted.sum())
                                            if emitted.sum() else None),
        })
        del a, emitted, ch, packed
        if (i + 1) % 10 == 0:
            print("  %d/%d done (%.0fs)" % (i + 1, len(audit["files"]), time.time() - t0),
                  flush=True)

    labels_ = [r["label"] for r in recs]
    counts = {r["label"]: r["chargeable_px"] for r in recs}
    pairs: List[Dict[str, object]] = []
    for i in range(len(labels_)):
        ai = labels_[i]
        for j in range(i + 1, len(labels_)):
            aj = labels_[j]
            ci, cj = counts[ai], counts[aj]
            if not ci or not cj:
                continue
            inter = int(POP[np.bitwise_and(bits[ai], bits[aj])].sum())
            union = ci + cj - inter
            if not union:
                continue
            jac = inter / union
            if jac >= 0.5:
                pairs.append({"a": ai, "b": aj, "intersection_px": inter,
                              "union_px": union, "jaccard": round(jac, 6),
                              "chargeable_identical": bool(jac >= args.identical_jaccard)})
    pairs.sort(key=lambda p: -p["jaccard"])

    out = {
        "generated_utc": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "definition": ("pred > 0 AND finite AND distance to nearest shipped label > "
                       "%.0f px (%.0f m)" % (args.kernel_px, args.kernel_px * 100)),
        "caveat": ("An earlier ad-hoc pass measured the same idea with a 7x7 Chebyshev "
                   "dilation (also 300 m); those transcript numbers are a superset of "
                   "the Euclidean ones here and are not the persisted values."),
        "kernel_px": args.kernel_px,
        "identical_jaccard_threshold": args.identical_jaccard,
        "footprint_px": int(valid.sum()),
        "label_px": int(lab.sum()),
        "chargeable_zone_px": int(free.sum()),
        "files": recs,
        "pairs_jaccard_ge_0.5": pairs,
        "chargeable_identical_groups": [],
    }
    seen = set()
    groups = []
    for p in pairs:
        if not p["chargeable_identical"]:
            continue
        matched = None
        for g in groups:
            if p["a"] in g or p["b"] in g:
                matched = g
                break
        if matched is None:
            groups.append({p["a"], p["b"]})
        else:
            matched.update({p["a"], p["b"]})
    out["chargeable_identical_groups"] = [sorted(g) for g in groups]
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, allow_nan=False)

    print("\nchargeable pairs with Jaccard >= 0.5: %d" % len(pairs))
    for p in pairs[:12]:
        print("  %.4f  %s  <->  %s  (%d px)"
              % (p["jaccard"], p["a"][-42:], p["b"][-42:], p["intersection_px"]))
    print("chargeably identical groups: %s" % out["chargeable_identical_groups"])
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
