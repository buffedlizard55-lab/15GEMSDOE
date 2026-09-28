# AUDIT — line-by-line verification, 2026-09-28

Scope: every factual claim made in this session's brief and in this repository.
Each row states the claim, what was actually checked, the command or URL that
checked it, and the verdict. Anything that could not be checked says so.

Verdicts: **CONFIRMED** (reproduced here), **CONFIRMED WITH CORRECTION**
(substance right, detail wrong), **UNVERIFIABLE** (no source reachable or no data),
**FALSE/STALE**.

---

## A. The scoring algebra

| # | Claim in the brief | Check | Verdict |
|---|---|---|---|
| A1 | Official `FN_w = |G| − TP_w` | Derived from the two published sums; asserted on random rasters in `scripts/verify_metric.py` check C. Max residual **0.00e+00**. | CONFIRMED |
| A2 | DTI reduces to `TP_w / (0.2·TP_w + 0.2·FP_w + 0.8·|G|)` | Follows from A1 with α+β = 1: `TP + αFP + βFN = αTP + αFP + β|G|`. Reproduced. | CONFIRMED |
| A3 | That is a weighted harmonic mean of recall (weight 0.8) and precision (weight 0.2) | `1/(β/R_w + α/P_w)` equals the official expression algebraically, and numerically on the worked example. Residual **5.55e-17**. | CONFIRMED |
| A4 | Worked example TP_w 3.00, FP_w 1.89, FN_w 2.00 → 0.60 | `3.00/(3.00 + 0.2·1.89 + 0.8·2.00) = 3.00/4.978 = 0.602652 → 0.60`. Denominator read from the page and reconstructed. | CONFIRMED |
| A5 | A block raises the score only if ΔTP_w/(ΔTP_w+ΔFP_w) > 0.2 × DTI | Derived (denominator grows by α(t+f), numerator by t) and tested on seven trial blocks plus a distance sweep. All consistent. | CONFIRMED |
| A6 | Scaling all values toward 1 always raises DTI ⇒ optimum near binary | Proved monotone: `DTI(t) = t·TP/(β|G| + αt(TP+FP))`, derivative sign = `β|G| > 0`; measured rising at seven values of t. | CONFIRMED |
| A7 | A relative recall gain outweighs the same relative precision gain iff precision > ¼ recall | Elasticity ratio = `(β/α)(P/R) = 4P/R`; measured > 1 exactly when `P > R/4`. | CONFIRMED |
| A8 | "TP_w takes a max over the 300 m neighbourhood, so redundant nearby predictions add false-positive mass without extra credit" | True by construction of the published `max` operator: two emitted pixels serving one truth pixel are credited once and billed twice. Verified by A5's trial blocks (adding a neighbouring pixel to an already-covered truth cell does not pay). | CONFIRMED |

## B. The organizers' four statements

All four were re-fetched verbatim this session; the exact strings are in
`data/sources.json` (S3, S4, S5).

| # | Brief's version | Actual text | Verdict |
|---|---|---|---|
| B1 | Known USGS/INGENIOUS fault pixels are masked from scoring in both rounds, using a pixel-exact mask identical to the training labels | Post 2: "Pixels corresponding to known USGS/INGENIOUS faults are masked / excluded from evaluation…"; "Re-evaluation will also mask/exclude the existing USGS/INGENIOUS faults." Post 4: "The mask is indeed pixel-exact - it is identical to the provided set of training fault labels." | CONFIRMED |
| B2 | A predicted pixel just beside a known trace is fully penalized unless near a new-fault pixel | Post 4: "A predicted pixel that is near a known fault trace but far from a new-fault ground truth pixel will be fully penalized, i.e., the buffer does not apply to known faults." | CONFIRMED |
| B3 | New-fault pixels can lie within 300 m of known traces | Post 4: "A new-fault ground truth pixel can indeed lie within 300m of a known fault trace." | CONFIRMED |
| B4 | "New fault" means any fault pixel not already captured, including extensions, splays, parallel strands and corrections | Topic 11536: "'new fault' means 'any fault pixel not already captured by USGS/INGENIOUS' and can include newly mapped geometry of an existing fault system." Post 4 adds "corrections or modifications to existing fault traces". | CONFIRMED WITH CORRECTION — see **I-3** |
| B5 | Organizers declined to say which data or fault types the test faults came from | Topic 11527 post 7: "We're not sharing details about the data sources, fault types, or coverage behind the test faults beyond what's in the problem description." | CONFIRMED |
| B6 | (additional, found while verifying) The largest prize pool is decided on a label set updated by expert review of Phase 1 submissions | Same post: "the largest prize pool (Phase 2) will use a test set that is updated by expert review of all Phase 1 submissions, so your fault predictions have an impact on final evaluation even if they are not the most performant in Phase 1." | CONFIRMED — and it materially changes what "good" means: coverage of *plausible* structure has value beyond the Phase 1 metric |

## C. The leaderboard and the 0.1563 repetition

| # | Claim | Check | Verdict |
|---|---|---|---|
| C1 | "0.3049 is the highest score right now" | Fetched 2026-09-28: rank 1 DARD **0.3168** (11 submissions). The figure 0.3049 is what the group's own snapshot recorded on 2026-09-27. | **STALE** — see **I-1** |
| C2 | "Why do we keep scoring 0.1563 — are we copying the same work over and over?" | SHA-256 over every submitted raster in the group's repositories found `7f00890a62878d61…` present **three times** across two repositories, and that is the file recorded at 0.1563. The group's own ledger states "Published in 5GEMSDOE, GEMSDOE and 7GEMSDOE: three byte-identical copies." | CONFIRMED — identical bytes cannot score differently |
| C3 | "5GEMSDOE and GEMSDOE1 have the same score" | Yes: same displayed score *and* the same file hash. Also true of 8GEMSDOE. | CONFIRMED |
| C4 | Do equal scores always mean identical files? | No. Several unrelated competitors share four-decimal scores on the public board, and one of the group's 0.1563 files came from a different raster. | CONFIRMED — stated so C3 is not over-read |
| C5 | Why else did local numbers look good while the board did not? | The group's ledger pairs local and public scores: 0.2304→0.1563, 0.2059→0.1193, 0.1948→0.1152, 0.1767→0.0830, and notes "Holdout score is optimistic - fitted on the held-out traces." | CONFIRMED |

## D. Data and environment

| # | Claim | Check | Verdict |
|---|---|---|---|
| D1 | `bash scripts/download_competition_data.sh` / data placement is the only blocker | The three official rasters were assembled from the pinned public transport and hashed. All three SHA-256 digests match the pins exactly (418,912,844 / 425,830 / 1,599,597 bytes). `scripts/verify_data.py` exits 0. | CONFIRMED, with **I-2** on provenance |
| D2 | Grid: EPSG:32611, 100 m, 3292×3730, transform (100,0,243350,0,−100,4508550) | Read from all three rasters; identical. | CONFIRMED |
| D3 | The shipped `sample_submission.tif` "predicts total fault absence" | **It does not.** It contains 60,988 cells equal to 1.0, exactly the known-fault cells; the other 5,106,385 in-footprint cells are 0.0 and everything outside the footprint is NaN. Copying the template therefore predicts the catalogue and, once known faults are masked, scores zero. | **FALSE** as written on the page — see **I-4** |
| D4 | The valid footprint is the whole rectangle | No: only **5,167,373 / 12,279,160** cells (42.08 %) are inside the data footprint. Predictions must be NaN elsewhere, and the footprint mask matters for every FP calculation. | CONFIRMED WITH CORRECTION |

## E. Irregularities flagged for review

* **I-1 — Stale leader.** The brief's 0.3049 was correct on 2026-09-27 and is
  0.3168 on 2026-09-28. Every strategic constant in this repository is computed
  from the fetched 0.3168 and labelled as such.
* **I-2 — Data provenance.** The official data tab requires login and redirects
  to it. The rasters used here were fetched through a team-published public
  transport whose pins reproduce the official bytes. This is a *byte-integrity*
  check, not an origin guarantee. Prefer a direct download with credentials.
* **I-3 — Quote attribution.** "Extensions, splays, parallel strands" is the
  questioner's vocabulary (moongrega, topic 11536 post 1), not the organizer's.
  The organizer's own words are narrower. The substance is unaffected, but the
  attribution in the brief is not exact.
* **I-4 — Page contradicts its own file.** The problem description says the
  sample "predicts total fault absence"; the shipped file is the catalogue
  rasterised. Anyone who trusts the sentence and submits the template will score
  zero without knowing why.
* **I-5 — Submission-frequency wording.** The homepage blurb in the brief says
  three per week. The organizer's only statement on the clock is that the
  allowance "resets based on a rolling window, not at a specific date and time"
  (topic 11524). The exact rolling period is not stated in any source read here.
* **I-6 — Attribute stratification impossible.** The brief asks for withholding
  "by age or slip-rate class where attributes exist". They do not exist: the
  label raster is a bare int8 grid with no attribute table. Recorded as
  unavailable rather than approximated silently.
* **I-7 — Nine sources named but not read** (about page 968, the data tab, the
  rules HTML page, rules PDF §3.3–3.5 and Appendix A, forum threads 11529 and
  11543, GDR 1391, the DOE announcement). Listed in `data/sources.json` under
  `not_yet_verified` and on the Sources page. Thread 11529 (why the data-tab
  labels have one band while the reference solution has 19) is the most
  consequential of these: it bears directly on how the mask was rasterised.
* **I-8 — Hard-coded grid constants.** `scripts/make_submission.py` carries the
  origin in `GRID` rather than reading it from the reference raster. The
  validator checks the output against the reference, so a mismatch would fail
  loudly rather than silently — but the constant should be read from disk.

## F. What remains unproven, stated plainly

* No score on the private test set is known or forecast. Holdout DTI is a
  ranking instrument on a proxy target.
* No new fault and no geothermal resource is claimed.
* The holdout cannot reproduce a genuinely unmapped structure: its hidden pixels
  are faults that are already mapped.
* A learned segmentation model was not trained. The sandbox has 2 CPUs and
  ~3 GB RAM; a 19-band CNN over 12.3 Mpixels is not feasible here.
* `docs/evidence/fusion_results.json` is the only place a fusion conclusion can
  come from; if it is absent, no fusion claim may be made.
