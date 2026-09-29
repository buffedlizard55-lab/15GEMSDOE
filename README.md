# 15GEMSDOE — DOE GEMS Prize (DrivenData competition 306)

**Standing charter. Read this first in every session.** Everything below is
either quoted from an official source with a link, or measured in this
repository with the command that produced it. Assertions without one of those
two things are labelled as hypotheses or are not written down at all.

---

## 🎯 PROJECT CHARTER (Read Every Session)

### Core Objective
Place at the top of the leaderboard of the Geologic Enhanced Mapping System (GEMS) Prize, and produce a submission that anyone can download and upload in one click.

**Competition Links:**
- Competition: https://www.drivendata.org/competitions/306/competition-doe-gems/
- Problem description and metric: https://www.drivendata.org/competitions/306/competition-doe-gems/page/967/
- Official rules (PDF): https://docs.nlr.gov/docs/fy26osti/96647.pdf
- Reference solution: https://github.com/drivendataorg/gems-prize-reference-solution
- Leaderboard: https://www.drivendata.org/competitions/306/competition-doe-gems/leaderboard/

**Task Definition (verbatim):** *"develop models and algorithms that provide accurate information about the presence of structures that are indicative of geothermal resources—namely, geological faults."*

**Scored Objects:** **New faults** — defined by the sponsor as *"any fault pixel not already captured by USGS/INGENIOUS"*, including *"newly mapped geometry of an existing fault system"*.

### Core Values (From Arena AI Framework)

**Maximize P(Win)**
- Every decision weighs risk and reward against the probability of winning the prize
- Set aside emotions, make tough decisions to maximize P(Win)
- Frees us from constraints and clarifies we must put the project first

**Own the Outcome**
- Own results end to end — not just individual slices of work
- When problems arise and we have the means to act, we do so without waiting for permission
- Treat failure and success as signals and use them to improve
- Stay accountable to the final outcome

### Working Rules
1. **No claim without an official source or a command in this repo**
2. **No submission slot spent on an idea that has not beaten the current holdout best**
3. **No invented attribute, dataset or forum statement**
4. **Every measurement that contradicts a plan causes the plan to change that same session**
5. **All changes are written down rather than quietly dropped**

---

## 📊 CURRENT STATUS (2026-09-29)

### Leaderboard Position
- **Current Leader:** DARD at **0.3168** (11 submissions)
- **Our Best:** 0.1563 (repeated due to duplicate submissions)
- **Gap to Close:** ~0.16

### Duplicate Submission Analysis
**Problem:** Multiple submissions scoring **0.1563**

**Root Causes Identified:**
1. **Byte-identical files:** SHA-256 `7f00890a62878d61...` uploaded 3x across repos (5GEMSDOE, GEMSDOE, 7GEMSDOE)
2. **Chargeable-set duplicates:** 15 files share identical chargeable pixel sets (Jaccard ≥ 0.96)

**Solution Implemented:**
- Novelty gate now refuses array-identical candidates
- Chargeable-overlap criterion added to novelty gate
- Every emission hashed and gated before upload

### Current Best Holdout Performance
- **Detector:** `conj_alteration_mag` (GeoDAWN Th/K + U/K ratios × magnetic tilt edge)
- **Holdout DTI:** 0.05302
- **Beats baseline:** 4/4 withholding rules
- **Leakage probe:** 0.0000
- **Status:** PROMOTED

---

## 🔬 THE SCORING RULE (Audited Before Any Model Was Fitted)

### Official Metric
`dti = TP_w / (TP_w + 0.2 FP_w + 0.8 FN_w)`

With triangular kernel: `k(d) = max(1 - d/300 m, 0)`

**Verified against problem page's worked example:**
- TP_w 3.00, FP_w 1.89, FN_w 2.00 → **0.6027 → 0.60**
- Verification: `python scripts/verify_metric.py` (residual 0.0)

### Proven Consequences That Decide Strategy

| # | Consequence | Status | Strategic Implication |
|---|---|---|---|
| A | `TP_w + FN_w = \|G\|`, so `DTI = 1/(0.8/R_w + 0.2/P_w)` — weighted harmonic mean of weighted recall (0.8) and weighted precision (0.2) | PROVED | Recall matters 4× more than precision |
| B | A block of predictions pays off iff its own weighted precision exceeds **0.2 × DTI** | PROVED | Local precision bar at 6.3% for leader's 0.3168 |
| C | Pushing every value toward 1 raises DTI, so the **optimum is binary** | PROVED | Graded values are only a ranking device |
| D | A relative gain in recall beats the same relative gain in precision iff **P > R/4** | PROVED | Ratio = 4P/R |

**At current leader's 0.3168:**
- A lone pixel pays for itself out to **281 m (2.81 px)**
- Best measured map is **far more inclusive** than any calibrated 0.5 cutoff
- Emitted area is an **operating point chosen on a holdout**, not a probability threshold

---

## ✅ VALIDATION THAT MIRRORS PUBLISHED SEMANTICS

### Hide-and-Recover Protocol
`src/gems/holdout.py` implements the four organizer statements (quoted verbatim in `data/sources.json`, with links) as an executable protocol:

1. Split catalogue into **3,603 junction-separated strands** in **3,199 connected systems**
2. Hide whole fault strands (hidden pixels become "new faults")
3. Rebuild **every** catalogue-derived feature from what stays visible
4. Mask remaining known faults **pixel-exactly** (per organizer statement)
5. Score DTI on hidden pixels alone
6. Report **dilate-1 leakage probe** next to every result

### Three Gates Between Idea and Submission Slot

**Gate 1: New-Information Gate** (`scripts/evaluate_new_fields.py`)
- Candidate must beat incumbent on tuning draw **AND** ≥3 of 4 withholding rules
- Leakage probe must be < 0.02 everywhere
- Current promoted: `conj_alteration_mag` (0.05302 vs 0.04015 for `curv_scarp`)

**Gate 2: Novelty Gate** (`src/gems/novelty.py`, `scripts/audit_chargeable.py`)
- Refuses candidates that:
  - Repeat prior raster (array identity)
  - Have rank correlation ρ ≥ 0.99 with top-10k overlap
  - Share chargeable pixel set with Jaccard ≥ 0.95
- The 15-file family sharing chargeable sets is now banned

**Gate 3: Acquisition Gate** (`src/gems/acquisition.py`, `scripts/audit_acquisition.py`)
- Detects and rejects:
  - East-west lineaments from survey design (200m/400m spacing)
  - Block boundary artifacts (4 acquisition blocks)
  - Orientation histogram anomalies

---

## 🏆 STRATEGY TO REACH TOP OF LEADERBOARD

### Current Performance Analysis
- **Best holdout:** 0.05302 (conj_alteration_mag)
- **Leader:** 0.3168 (DARD)
- **Gap:** ~6× improvement needed

### Why We're Behind
1. **Duplicate submissions** wasting slots (FIXED with novelty gate)
2. **Optimistic local holdout** (FIXED with leakage-controlled protocol)
3. **Limited data modalities** - only using competition-provided rasters
4. **Missing key datasets** from GDR 1391 and GeoDAWN

### Path Forward

**Immediate Actions (This Session):**
1. ✅ **Review repo** - COMPLETED
2. ✅ **Mine free data** - Identified GDR 1391 (CC BY 4.0) and GeoDAWN (CC0) sources
3. ✅ **Generate new hypotheses** - Created NEW_HYPOTHESES.md with 5 unique candidates
4. ⏳ **Validate top candidate** on holdout before submission

**Next Sessions:**
1. **Implement H3** (Radiometric Ratio Edges) - Uses existing GeoDAWN data
2. **Implement H5** (Multi-Scale Curvature) - Uses existing elevation data
3. **Download GDR 1391** - Spring, tufa, vent, heat flow, slip/dilation data
4. **Implement H1** (Spring-Tufa-Vent Alignment) - Highest discovery potential

### Success Metrics
- **Minimum:** Holdout DTI > 0.060 (13% improvement)
- **Stretch:** Holdout DTI > 0.070 (32% improvement)
- **Ultimate:** Leaderboard > 0.250 (top 5)

---

## 📁 REPOSITORY LAYOUT

```
15GEMSDOE/
├── README.md                    # This file - project charter
├── AUDIT.md                     # Line-by-line verification log
├── NEW_HYPOTHESES.md            # New geological hypotheses to test
├── LANDING_NOTE.md              # Session landing notes
├── index.html                   # GitHub Pages entry point
├── requirements.txt             # Python dependencies
│
├── data/
│   ├── raw/                     # Official competition rasters
│   │   ├── labels.tif           # Training fault labels
│   │   ├── training_features.tif # 19-band feature stack
│   │   └── sample_submission.tif # Template (NOT all-zero!)
│   ├── aux/                     # External data (gitignored)
│   │   ├── geodawn_extensions_u8.tif  # Upward-continued TMI, ratios
│   │   └── geodawn_rad_u8.tif        # Radiometric channels
│   └── sources.json             # Official source inventory
│
├── docs/
│   ├── index.html               # Site homepage
│   ├── executive_summary.html    # How to submit (FIXED: addresses [0,1] error)
│   ├── holdout.html              # Holdout protocol and results
│   ├── hypotheses.html           # Current hypothesis tracker
│   ├── metric_audit.html         # Metric verification
│   ├── sources.html              # Source documentation
│   ├── audits.html               # Audit results
│   ├── downloads/                # Submission files with manifests
│   └── evidence/                 # JSON evidence for all claims
│
├── scripts/
│   ├── fetch_official_data.sh   # Download competition data
│   ├── verify_data.py            # SHA-256 verification
│   ├── verify_metric.py          # Metric audit
│   ├── run_holdout.py            # Hide-and-recover protocol
│   ├── evaluate_new_fields.py    # New-information gate
│   ├── evaluate_stripe_fix.py    # De-striping test
│   ├── make_candidate.py         # Build and validate candidate
│   ├── make_submission.py        # Final submission writer
│   ├── validate_submission.py    # Contract validation ([0,1] check)
│   ├── audit_novelty.py          # Novelty gate
│   ├── audit_chargeable.py       # Chargeable-set duplicate check
│   ├── audit_acquisition.py      # Survey artifact audit
│   ├── build_site.py             # Generate HTML site
│   └── check_site.py             # Site validation
│
└── src/gems/
    ├── __init__.py
    ├── metric.py                 # Official DTI implementations
    ├── geotiff.py                # Dependency-free TIFF writer
    ├── catalogue.py              # Label raster processing
    ├── holdout.py                # Hide-and-recover protocol
    ├── fields.py                 # 7 candidate detectors
    ├── fields_ext.py             # New-information detectors
    ├── labeldiff.py              # Catalogue vs labels diff
    ├── novelty.py                # Duplicate detection
    ├── acquisition.py            # Survey artifact detection
    └── emit.py                   # Thinning, ridge width, operating point
```

---

## 🚀 QUICK START

### Prerequisites
```bash
# Install dependencies
pip install -r requirements.txt  # numpy, scipy, rasterio

# Data placement (ONLY BLOCKER - requires unrestricted machine)
bash scripts/download_competition_data.sh data/raw
python scripts/verify_data.py data/raw
```

### Reproduce Everything
```bash
# Verify metric
python scripts/verify_metric.py

# Run holdout protocol
python scripts/run_holdout.py --data-dir data/raw

# Evaluate new fields
python scripts/evaluate_new_fields.py --collar-px 3 --out docs/evidence/holdout_new_fields_collar3.json

# Build candidate
python scripts/make_candidate.py

# Validate submission (includes [0,1] range check)
python scripts/validate_submission.py docs/downloads/gems-tso1-20260929T005627Z-conj_alteration_mag.tif \
    --reference data/raw/sample_submission.tif

# Build site
python scripts/build_site.py
python scripts/check_site.py
```

### Generate New Hypotheses
See `NEW_HYPOTHESES.md` for 5 unique candidates ranked by expected improvement.

---

## 📊 WHAT IS MEASURED vs. NOT MEASURED

### ✅ Measured (in `docs/evidence/`)
- Metric equivalence to official definition
- Holdout DTI under leakage-controlled protocol
- Novelty (array identity, rank correlation, chargeable sets)
- Acquisition artifacts (E-W lineaments, block boundaries)
- Contract compliance ([0,1] range, CRS, resolution, bounds)

### ❌ Not Measured (and therefore not claimed)
- **No score on the private test set**
- **No discovery of a new fault**
- **No leaderboard improvement**

**Important:** Holdout DTI is a **ranking instrument**, not a forecast. The withheld pixels are faults already in the catalogue; the private set is faults judged to be **missing** from it.

---

## ⚠️ BLOCKERS AND LIMITATIONS

| # | Issue | Status | Workaround |
|---|-------|--------|------------|
| 1 | Official data tab requires login | **BLOCKED** | Use transported copies with SHA-256 verification |
| 2 | Label raster has no attributes | **IMPOSSIBLE** | Use geometry-based strata instead |
| 3 | Holdout cannot reproduce unmapped faults | **BY DESIGN** | Holdout is a ranking instrument, not a forecast |
| 4 | Limited compute (2 CPUs, ~3GB RAM) | **CONSTRAINT** | Use explicit detectors, not learned networks |
| 5 | Sandbox egress blocked | **BLOCKED** | Use transported copies from sibling repos |

---

## 🔍 IRREGULARITIES FOUND AND HANDLED

| # | Finding | Evidence | Action |
|---|---------|----------|--------|
| I-1 | Same raster uploaded multiple times (6 paths, 5 repos) | `docs/evidence/novelty_audit.json` | Novelty gate refuses array-identical candidates |
| I-2 | Different rasters, same chargeable set (15 files, Jaccard ≥ 0.96) | `docs/evidence/chargeable_support.json` | Chargeable-overlap criterion added to novelty gate |
| I-3 | `sample_submission.tif` is catalogue rasterized (60,988 ones) | `docs/evidence/data_verification.json` | Documented; not used as model |
| I-4 | QFDB "unmasked catalogue geometry" trap: only 1 pixel beyond 300m | `src/gems/labeldiff.py` | Hypothesis dropped; measurement kept |
| I-5 | Promoted candidate has 2-row survey-fabric periodicity | `docs/evidence/acquisition_audit.json` | Measured and documented |
| I-6 | Catalogue has 127 spike rows / 141 spike columns at 4 MAD | `docs/evidence/acquisition_audit.json` | Reported for like-for-like comparison |

---

## 📚 EXTERNAL DATA SOURCES (Free, Official, Verified)

### GDR Submission 1391 - INGENIOUS Great Basin Regional Dataset Compilation
- **URL:** https://gdr.openei.org/submissions/1391
- **License:** CC BY 4.0
- **Status:** Free for competition use (rules A.5 permits use and sharing with sponsor)
- **Contents:**
  - Quaternary fault shapefiles (with ages, slip rates)
  - Spring locations (temperature, chemistry)
  - Tufa/sinter deposit polygons
  - Volcanic vent points
  - 2m temperature probe data
  - Well temperature/chemistry data
  - Heat flow measurements
  - Slip tendency grids
  - Dilation tendency grids
  - Conductive models
  - Gravity/magnetics

### USGS GeoDAWN - Airborne Magnetic and Radiometric Surveys
- **URL:** https://doi.org/10.5066/P93LGLVQ
- **License:** CC0 1.0 Universal (public domain)
- **Status:** Already partially used in repository
- **Contents:**
  - Magnetic grids (RTP, TMI, derivatives)
  - Radiometric grids (K, Th, U, TC)
  - Upward-continued TMI (150m)
  - Contractor ratio grids (Th/K, U/K, U/Th)

### Competition Data
- **URL:** https://www.drivendata.org/competitions/306/competition-doe-gems/data/
- **License:** Competition data (requires login)
- **Status:** Transported copies verified via SHA-256

---

## 🎯 NEXT STEPS (Prioritized)

### Phase 1: Immediate (This Session)
- [x] Review repository structure
- [x] Mine free data sources
- [x] Generate new hypotheses (NEW_HYPOTHESES.md)
- [ ] **Verify available data** in `data/aux/` for H3 and H5
- [ ] **Start implementing H3** (Radiometric Ratio Edges)

### Phase 2: Short Term (Next 2 Sessions)
- [ ] Complete H3 implementation
- [ ] Implement H5 (Multi-Scale Curvature)
- [ ] Validate both on holdout
- [ ] Promote winner if beats 0.05302

### Phase 3: Medium Term (Next Week)
- [ ] Download GDR 1391 datasets
- [ ] Implement H1 (Spring-Tufa-Vent Alignment)
- [ ] Implement H4 (Slip/Dilation Tendency)
- [ ] Submit top candidate (max 3 per rolling week)

### Phase 4: Long Term
- [ ] Implement H2 (Heat Flow Anomaly)
- [ ] Fusion of top performers
- [ ] Iterate based on leaderboard feedback

---

## 📞 GETTING HELP

### Official Sources
- Competition forum: https://community.drivendata.org/c/gems-prize-challenge/111
- Organizer statements: See `data/sources.json` for verified quotes

### Repository Questions
- Check `AUDIT.md` for verification status of all claims
- Check `docs/evidence/` for JSON evidence files
- Run validation scripts to reproduce results

---

## ✅ SUBMISSION CHECKLIST

Before uploading any file:

1. **Contract Validation**
   ```bash
   python scripts/validate_submission.py <file.tif> --reference data/raw/sample_submission.tif
   ```
   - Must show: `READY TO UPLOAD`
   - Checks: CRS, resolution, bounds, [0,1] range, datatype

2. **Novelty Gate**
   ```bash
   python scripts/audit_novelty.py
   ```
   - Must not be duplicate of any prior
   - Must not share chargeable set (Jaccard < 0.95)

3. **Acquisition Audit**
   ```bash
   python scripts/audit_acquisition.py --candidate <file.tif>
   ```
   - Must not have E-W lineament dominance
   - Must not have block boundary artifacts

4. **Holdout Performance**
   - Must beat current best (0.05302) on collar-3
   - Must win ≥3 of 4 withholding rules
   - Leakage probe must be < 0.02

---

## 📝 CHANGE LOG

### 2026-09-29
- Added NEW_HYPOTHESES.md with 5 unique geological hypotheses
- Updated README with project charter and strategy
- Documented duplicate submission root causes and fixes
- Prioritized next steps

### 2026-09-28
- Audited all claims (AUDIT.md)
- Verified metric against official example
- Implemented hide-and-recover holdout protocol
- Added novelty gate (array + chargeable)
- Added acquisition audit
- Promoted conj_alteration_mag as new best

---

**Built with ✅ Max P(Win) and ✅ Own the Outcome**

*Every factual claim in this repository is either quoted from an official source with a URL, or measured with a command you can run. No hallucinations.*
