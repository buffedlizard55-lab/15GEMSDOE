"""Hide-and-recover holdout that mirrors the published scoring semantics.

Official statements implemented here (quoted in data/sources.json with links):

  S-1  "The mask is indeed pixel-exact - it is identical to the provided set of
        training fault labels."            chrisk-dd, topic 11516 post 4, 2026-09-21
  S-2  "Pixels corresponding to known USGS/INGENIOUS faults are masked /
        excluded from evaluation, so they do not count towards penalty terms."
        and "Re-evaluation will also mask/exclude the existing USGS/INGENIOUS
        faults."                            chrisk-dd, topic 11516 post 2, 2026-09-16
  S-3  "for scoring purposes it should not matter whether these known faults are
        included with predictions or not." chrisk-dd, topic 11516 post 2
  S-4  "A predicted pixel that is near a known fault trace but far from a
        new-fault ground truth pixel will be fully penalized, i.e., the buffer
        does not apply to known faults."    chrisk-dd, topic 11516 post 4
  S-5  "A new-fault ground truth pixel can indeed lie within 300m of a known
        fault trace."                       chrisk-dd, topic 11516 post 4
  S-6  "'new fault' means 'any fault pixel not already captured by
        USGS/INGENIOUS' and can include newly mapped geometry of an existing
        fault system."                      chrisk-dd, topic 11536 post 2, 2026-09-23

Protocol.  Pick a set W of segments from the shipped catalogue and *hide* them.
The visible catalogue is V = labels \\ W.  Then

    truth  G  = pixels of W, minus a collar of `collar_px` around V  (S-5 says
                genuine new faults may sit close to known traces, but a withheld
                pixel that is 1 px from V would be claimed by a trivial
                dilation of the visible catalogue, so those few pixels are
                reported as `collar_dropped` and excluded from G);
    mask   M  = pixels of V (score-neutral, pixel-exact, S-1..S-3);
    valid     = the data footprint (finite in the shipped sample submission).

Every catalogue-derived feature must be computed from V only.  `dti(pred, G,
mask=M, valid=valid)` then charges false positives against G alone (S-4), gives
no credit or penalty on V (S-3), and never sees the hidden geometry (S-1/S-6).

Four withholding rules are provided.  An idea that only wins under one of them
is reported as fragile; this module exists so that claim is a measurement rather
than an assertion.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

RULES = ("random", "short", "isolated", "long")


def choose_withheld(records: Sequence[Dict[str, object]], rule: str,
                    fraction: float = 0.2, seed: int = 0,
                    max_pixels: Optional[int] = None) -> List[int]:
    """Select segment ids to hide under one of the four rules.

    random   : uniform sample of segments (shuffled, seeded)
    short    : shortest first -- probes the small splays a catalogue omits
    isolated : most distant from any other segment first -- probes stand-alone
               strands rather than splays of a mapped system
    long     : longest first -- probes along-strike extensions of big systems
    """
    rng = random.Random(seed)
    recs = [r for r in records if r["pixels"] > 0]
    if rule == "random":
        order = recs[:]
        rng.shuffle(order)
    elif rule == "short":
        order = sorted(recs, key=lambda r: (r["pixels"], r["id"]))
    elif rule == "long":
        order = sorted(recs, key=lambda r: (-r["pixels"], r["id"]))
    elif rule == "isolated":
        order = sorted(recs, key=lambda r: (-(r.get("isolation_m") or 0.0), r["id"]))
    else:
        raise ValueError("unknown withholding rule %r" % rule)

    total = sum(r["pixels"] for r in recs)
    target = fraction * total if max_pixels is None else min(max_pixels, fraction * total)
    chosen: List[int] = []
    acc = 0
    for r in order:
        if acc >= target:
            break
        chosen.append(int(r["id"]))
        acc += int(r["pixels"])
    return chosen


def build_holdout(labels: np.ndarray, seg_ids: np.ndarray,
                  withheld_ids: Sequence[int], valid: np.ndarray,
                  collar_px: int = 1) -> Dict[str, object]:
    """Return truth/mask/valid rasters for one withholding draw."""
    hidden = np.isin(seg_ids, np.asarray(list(withheld_ids), dtype=seg_ids.dtype))
    visible = (labels > 0) & ~hidden

    if collar_px > 0:
        near_visible = ndimage.binary_dilation(
            visible, structure=np.ones((2 * collar_px + 1,) * 2, bool))
    else:
        near_visible = visible
    collar_zone = hidden & near_visible
    truth = hidden & ~collar_zone & valid
    mask = visible & valid

    return {
        "truth": truth,
        "mask": mask,
        "valid": valid,
        "hidden_all": hidden,
        "visible": visible,
        "collar_dropped": int(collar_zone.sum()),
        "truth_pixels": int(truth.sum()),
        "mask_pixels": int(mask.sum()),
        "valid_pixels": int(valid.sum()),
        "n_withheld_segments": int(len(withheld_ids)),
    }


def leakage_probe(holdout: Dict[str, object], pixel_metres: float = 100.0) -> Dict[str, float]:
    """How much of the hidden truth a trivial dilation of the *visible* catalogue claims.

    If a dollop of the visible catalogue at 1 px already scores well, the split is
    not hiding anything and every downstream number is meaningless.  The runner
    reports this next to the results and refuses to draw conclusions when it is
    high.
    """
    from .metric import dti
    visible = np.asarray(holdout["visible"])
    for pad in (1, 2, 3):
        probe = ndimage.binary_dilation(visible, np.ones((2 * pad + 1,) * 2, bool))
        p = probe.astype(np.float64)
        r = dti(p, holdout["truth"], mask=holdout["mask"], valid=holdout["valid"])
        if pad == 1:
            first = r["dti"]
    return {"dilate1_dti": first, "pad_used": 1}
