# 15GEMSDOE — DOE GEMS Prize (DrivenData competition 306)

**Standing charter. Read this first in every session.** Everything below is
either quoted from an official source with a link, or measured in this
repository with the command that produced it. Assertions without one of those
two things are labelled as hypotheses or are not written down at all.

---

## 1. The outcome we are building

Place at the top of the leaderboard of the Geologic Enhanced Mapping System
(GEMS) Prize, and produce a submission that anyone can download and upload in
one click.

* Competition: https://www.drivendata.org/competitions/306/competition-doe-gems/
* Problem description and metric: https://www.drivendata.org/competitions/306/competition-doe-gems/page/967/
* Official rules (PDF): https://docs.nlr.gov/docs/fy26osti/96647.pdf
* Reference solution: https://github.com/drivendataorg/gems-prize-reference-solution
* Leaderboard: https://www.drivendata.org/competitions/306/competition-doe-gems/leaderboard/

Task (verbatim): *"develop models and algorithms that provide accurate
information about the presence of structures that are indicative of geothermal
resources—namely, geological faults."* The scored objects are **new faults**,
which the sponsor defines as *"any fault pixel not already captured by
USGS/INGENIOUS"*, including *"newly mapped geometry of an existing fault
system"*.

## 2. The scoring rule, audited before any model was fitted

`dti = TP_w / (TP_w + 0.2 FP_w + 0.8 FN_w)`, with a triangular kernel
`k(d) = max(1 - d/300 m, 0)`. Verified against the problem page's own worked
example (TP_w 3.00, FP_w 1.89, FN_w 2.00 → **0.6027 → 0.60**) by
`python scripts/verify_metric.py`, which also proves four consequences that
decide the whole strategy:

| # | Consequence | Status |
|---|---|---|
| A | `TP_w + FN_w = \|G\|`, so `DTI = 1/(0.8/R_w + 0.2/P_w)` — a weighted harmonic mean of weighted recall (weight 0.8) and weighted precision (weight 0.2) | proved, residual 0.0 |
| B | A block of predictions pays off iff its own weighted precision exceeds **0.2 × DTI** | proved, and tested on trial blocks |
| C | Pushing every value toward 1 raises DTI, so the optimum is **binary**; graded values are only a ranking device | proved monotone |
| D | A relative gain in recall beats the same relative gain in precision iff **P > R/4** | proved, ratio = 4P/R |

At the current leader's 0.3168, consequence B sets the bar at **6.3 % local
precision**, and a lone pixel pays for itself out to **281 m (2.81 px)**. That is
why the best measured map is far more inclusive than any calibrated 0.5 cutoff,
and why the emitted area is an *operating point chosen on a holdout*, not a
probability threshold.

## 3. Validation that mirrors the published semantics

`src/gems/holdout.py` implements the four organizer statements (quoted verbatim
in `data/sources.json`, with links) as an executable protocol: withhold whole
fault segments, rebuild every catalogue-derived feature from what stays visible,
mask the remaining known faults pixel-exactly, and score DTI on the withheld
pixels alone. `scripts/run_holdout.py` tunes the operating point on one draw and
then re-verifies on four withholding rules (random, short, isolated, long).

A split is only trusted if the **dilate-1 leakage probe** is low: a prediction
made by dilating the visible catalogue by one pixel must not already score well.
Reported per rule, alongside the results, in `docs/HOLDOUT.md`.

## 4. Core values that govern the work

* **Maximize P(Win).** Every decision weighs risk and reward against the
  probability of winning the prize, not against looking busy.
* **Own the outcome.** Failure and success are both signals. If a measurement
  contradicts a plan, the plan changes that same session, and the reversal is
  written down rather than quietly dropped.

Working rules: no claim without an official source or a command in this repo; no
submission slot spent on an idea that has not beaten the current holdout best; no
invented attribute, dataset or forum statement.

## 5. Reproduce everything

```bash
bash scripts/fetch_official_data.sh data/raw     # place + SHA-256 verify the rasters
python  scripts/verify_data.py    data/raw      # independent re-check, writes evidence JSON
python  scripts/verify_metric.py                # audit the metric, writes evidence JSON
python  scripts/run_holdout.py --data-dir data/raw   # tune + verify on the holdout
python  scripts/tune_fusion.py  --data-dir data/raw  # choose detector fusion
python  scripts/make_submission.py --data-dir data/raw   # write the GeoTIFF
python  scripts/validate_submission.py docs/downloads/<file>.tif --reference data/raw/sample_submission.tif
```

The submission writer uses `src/gems/geotiff.py`, a dependency-free TIFF writer,
so a valid file can always be produced without GDAL. Everything else needs
`numpy`, `scipy`, `rasterio` (`requirements.txt`).

## 6. What is measured, and what is not

Measured, on the leakage-controlled holdout, by `scripts/run_holdout.py`:
see `docs/evidence/holdout_results.json`, summarised in `docs/HOLDOUT.md`.

Not measured, and therefore not claimed: **no score on the private test set, no
discovery of a new fault, and no leaderboard improvement.** The withheld pixels
are faults that are *already in the catalogue*; the private set is faults an
expert judged to be *missing from it*. Every holdout DTI in this repository is a
ranking instrument, not a forecast.

## 7. Blockers and limitations

1. **Data origin.** The official data tab redirects to login. The rasters used
   here come from the free public transport pinned in `config/data_pins.json`;
   all three SHA-256 digests match the inventory taken on an unrestricted runner,
   so the bytes are right, but they were not pulled with a DrivenData account.
   Prefer a direct download when credentials are available.
2. **No attributes.** The label raster carries no age or slip-rate field, so the
   attribute-stratified withholding the brief asks for is **not possible from the
   shipped data**. Geometry-based strata are used instead and the gap is stated.
3. **One region, one era.** The holdout draws its "new" faults from the same map
   the model can see. It cannot reproduce a genuinely unmapped structure.
4. **Compute.** This sandbox has 2 CPUs and ~3 GB RAM, so the 418 MB, 19-band
   feature stack is used through explicit detector fields rather than a learned
   segmentation network. The CNN path from the reference solution is untested
   here.

## 8. Layout

```
src/gems/metric.py      official DTI, three independent implementations + audit helpers
src/gems/geotiff.py     dependency-free float32 GeoTIFF writer/reader
src/gems/catalogue.py   label raster -> components, strands, isolation
src/gems/holdout.py     hide-and-recover protocol + leakage probe
src/gems/fields.py      the seven candidate detectors
src/gems/emit.py        thinning, ridge width, operating-point sweep
scripts/                the eight runnable steps above, each writing evidence JSON
tests/                  metric equivalence, GeoTIFF round-trip, contract checks
docs/                   the published site, the submission, and the evidence
```

Submission artefacts live in `docs/downloads/` with a `.manifest.json` next to
each one recording its SHA-256, grid, policy and the holdout score that selected
it. The site at `docs/index.html` has the download and the exact upload steps at
the top of the page, above everything else.
