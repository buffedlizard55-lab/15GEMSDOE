# WORK PLAN - 15GEMSDOE

**Generated:** 2026-09-29  
**Objective:** Reach top of leaderboard (>0.3049) through systematic, audited improvements  
**Current Status:** Holdout best = 0.05302, Leader = 0.3168  
**Gap:** ~0.26 DTI improvement needed

---

## 🎯 EXECUTIVE SUMMARY

### Problem Analysis
1. **Duplicate submissions** causing repeated 0.1563 scores - **FIXED** with novelty gate
2. **Limited data modalities** - Only using competition-provided rasters
3. **Missing key datasets** from GDR 1391 (CC BY 4.0) and GeoDAWN (CC0)
4. **Need novel hypotheses** that use different information, not just re-tuning

### Solution Path
1. **Mine free data** from GDR 1391 and GeoDAWN (already identified)
2. **Implement new hypotheses** (5 generated, ranked by expected DTI improvement)
3. **Validate on holdout** before spending submission slots
4. **Submit only winners** that beat current best (0.05302)

---

## 📋 PRIORITIZED TASK LIST

### Phase 0: Repository Review (COMPLETED ✅)
- [x] Review README, AUDIT, sources.json
- [x] Understand current pipeline and gates
- [x] Identify duplicate submission root causes
- [x] Review existing hypotheses and results
- [x] Create NEW_HYPOTHESES.md with 5 unique candidates
- [x] Create DATA_SOURCES.md with verified free sources
- [x] Update README with project charter

### Phase 1: Data Inventory (CURRENT 🔄)
- [ ] **Verify existing aux data** - What's in `data/aux/`
- [ ] **Check GeoDAWN extension file** - Does it have TMI_up150, ratios?
- [ ] **Check GeoDAWN radiometric file** - Does it have K, Th, U, TC?
- [ ] **Document findings** in DATA_SOURCES.md

**Command to run:**
```bash
python3 << 'EOF'
import rasterio
import os

aux_dir = "data/aux"
if not os.path.exists(aux_dir):
    print(f"{aux_dir} does not exist")
    exit(1)

files = [f for f in os.listdir(aux_dir) if f.endswith('.tif')]
print(f"Found {len(files)} TIFF files in {aux_dir}:")

for f in files:
    path = os.path.join(aux_dir, f)
    try:
        with rasterio.open(path) as s:
            print(f"\n{f}:")
            print(f"  Bands: {s.count}")
            print(f"  Shape: {s.height}x{s.width}")
            print(f"  CRS: {s.crs}")
            print(f"  Descriptions: {[d for d in s.descriptions if d]}")
    except Exception as e:
        print(f"\n{f}: ERROR - {e}")
EOF
```

### Phase 2: Implement High-Priority Hypotheses (NEXT 🚀)

#### Hypothesis 3: Radiometric Ratio Edges (HIGHEST PRIORITY)
**Why:** Data likely already available, low implementation cost, high discovery potential

**Tasks:**
- [ ] Verify `data/aux/geodawn_rad_u8.tif` contains K, Th, U, TC bands
- [ ] Implement ratio computation (K/Th, U/Th, U/K, (K+U+Th)/TC)
- [ ] Implement edge detection on ratio grids
- [ ] Implement multi-ratio conjunction
- [ ] Validate on holdout
- [ ] If beats 0.05302, promote to candidate

**Estimated Time:** 2-4 hours
**Expected DTI Gain:** +0.005-0.012

**Implementation File:** `src/gems/fields_ext.py` (extend existing)

---

#### Hypothesis 5: Multi-Scale Curvature (SECOND PRIORITY)
**Why:** Uses existing data, method novelty, captures faults of all sizes

**Tasks:**
- [ ] Implement multi-scale Gaussian curvature (300m, 600m, 900m, 1200m)
- [ ] Implement stacking methods (sum, max, product)
- [ ] Test which scale/combination works best
- [ ] Validate on holdout
- [ ] If beats 0.05302, promote to candidate

**Estimated Time:** 2-3 hours
**Expected DTI Gain:** +0.003-0.008

**Implementation File:** `src/gems/fields.py` (add new field)

---

### Phase 3: Download and Process External Data

#### GDR 1391 Data Acquisition
**Priority:** HIGH (enables H1, H2, H4)

**Tasks:**
- [ ] Manual download from https://gdr.openei.org/submissions/1391
- [ ] Verify CC BY 4.0 license for all files
- [ ] Organize in `data/aux/gdr_1391/`
- [ ] Compute SHA-256 for all files
- [ ] Add to `data/sources.json`
- [ ] Verify CRS and resolution compatibility

**Dependencies:**
- GDR account (free registration)
- Internet access (not available in sandbox)

**Workaround:** Use transported copies from sibling repos if available

---

#### Hypothesis 1: Spring-Tufa-Vent Alignment
**Priority:** HIGH (highest discovery potential)

**Tasks:**
- [ ] Process spring point data → KDE grid
- [ ] Process tufa polygon data → KDE grid
- [ ] Process vent point data → KDE grid
- [ ] Process 2m temperature probes → 100m grid
- [ ] Implement conjunction logic
- [ ] Validate on holdout

**Estimated Time:** 4-6 hours (after data download)
**Expected DTI Gain:** +0.010-0.020

---

#### Hypothesis 4: Slip/Dilation Tendency
**Priority:** HIGH (stress-based, independent signal)

**Tasks:**
- [ ] Load slip tendency grid from GDR 1391
- [ ] Load dilation tendency grid from GDR 1391
- [ ] Compute gradients/edges
- [ ] Implement conjunction logic
- [ ] Validate on holdout

**Estimated Time:** 3-4 hours (after data download)
**Expected DTI Gain:** +0.007-0.015

---

#### Hypothesis 2: Heat Flow Anomaly
**Priority:** MEDIUM (data sparsity risk)

**Tasks:**
- [ ] Load heat flow measurements from GDR 1391
- [ ] Interpolate to 100m grid
- [ ] Remove regional trends
- [ ] Edge detection on residual
- [ ] Validate on holdout

**Estimated Time:** 3-5 hours (after data download)
**Expected DTI Gain:** +0.008-0.015

---

### Phase 4: Validation and Submission

For **each** implemented hypothesis:

1. **Holdout Validation**
   ```bash
   python scripts/evaluate_new_fields.py --collar-px 3 --field <field_name> --out docs/evidence/holdout_<field>.json
   ```
   - Must beat 0.05302 on collar-3
   - Must win ≥3 of 4 withholding rules
   - Leakage probe < 0.02

2. **Novelty Check**
   ```bash
   python scripts/audit_novelty.py
   ```
   - Must not be duplicate
   - Must not share chargeable set (Jaccard < 0.95)

3. **Acquisition Audit**
   ```bash
   python scripts/audit_acquisition.py --candidate <file.tif>
   ```
   - Must not have E-W artifacts
   - Must not have block boundary artifacts

4. **Contract Validation**
   ```bash
   python scripts/validate_submission.py <file.tif> --reference data/raw/sample_submission.tif
   ```
   - Must show: READY TO UPLOAD
   - All checks must pass

5. **Promotion**
   - If all gates pass, run `scripts/make_candidate.py` with new field
   - Generate manifest.json
   - Update docs and site

---

## 📅 TIMELINE ESTIMATE

### Week 1 (Current)
- **Day 1:** Data inventory + H3 implementation
- **Day 2:** H5 implementation + H3 validation
- **Day 3:** GDR 1391 download + H1 implementation
- **Day 4:** H1 validation + H4 implementation
- **Day 5:** Submit first improved candidate

### Week 2
- **Day 6:** H2 implementation + validation
- **Day 7:** Fusion experiments
- **Day 8:** Submit second improved candidate
- **Day 9:** Analyze leaderboard feedback
- **Day 10:** Submit third improved candidate

---

## 🎯 SUCCESS METRICS

### Minimum Viable
- ✅ Holdout DTI > 0.060 (13% improvement over 0.05302)
- ✅ Novelty gate PASS
- ✅ Acquisition audit PASS
- ✅ Submit 1-2 improved candidates per week

### Stretch Goals
- 🎯 Holdout DTI > 0.070 (32% improvement)
- 🎯 Leaderboard score > 0.200 (enter top 10)
- 🎯 3+ distinct hypotheses beating baseline

### Ultimate Goals
- 🏆 Leaderboard score > 0.250 (enter top 5)
- 🏆 Leaderboard score > 0.300 (beat current leader)
- 🏆 Win prize

---

## 📊 TRACKING METRICS

### Current Baseline
| Metric | Value | Source |
|--------|-------|--------|
| Holdout DTI (best) | 0.05302 | conj_alteration_mag |
| Leaderboard (best) | 0.1563 | Duplicate submissions |
| Leader (DARD) | 0.3168 | Public leaderboard |

### Target Improvements
| Hypothesis | Expected DTI | Status | Holdout Result | Leaderboard Result |
|------------|--------------|--------|----------------|-------------------|
| H3: Radiometric Ratio Edges | +0.005-0.012 | Not started | TBD | TBD |
| H5: Multi-Scale Curvature | +0.003-0.008 | Not started | TBD | TBD |
| H1: Spring-Tufa-Vent | +0.010-0.020 | Not started | TBD | TBD |
| H4: Slip/Dilation | +0.007-0.015 | Not started | TBD | TBD |
| H2: Heat Flow | +0.008-0.015 | Not started | TBD | TBD |

---

## 🔧 IMPLEMENTATION DETAILS

### Hypothesis 3: Radiometric Ratio Edges

**File:** `src/gems/fields_ext.py` (extend)

**Pseudocode:**
```python
def build_radiometric_ratios(rad_path, valid, sigma=1.0):
    # Load K, Th, U, TC bands
    rad = _read(rad_path, valid)
    
    # Compute ratios
    ratios = {}
    if 'K' in rad and 'Th' in rad:
        ratios['K_Th'] = np.nan_to_num(rad['K'] / rad['Th'])
    if 'U' in rad and 'Th' in rad:
        ratios['U_Th'] = np.nan_to_num(rad['U'] / rad['Th'])
    if 'U' in rad and 'K' in rad:
        ratios['U_K'] = np.nan_to_num(rad['U'] / rad['K'])
    if all(k in rad for k in ['K', 'Th', 'U', 'TC']):
        ratios['total_closure'] = np.nan_to_num(
            (rad['K'] + rad['U'] + rad['Th']) / rad['TC']
        )
    
    # Edge detection on each ratio
    edges = {}
    for name, ratio in ratios.items():
        g = _grad_mag(_gauss(ratio, sigma))
        edges[name + '_edge'] = _nan_safe_z(g, valid)
    
    # Multi-ratio conjunction
    if len(edges) >= 2:
        # Try all pairs
        for (n1, e1), (n2, e2) in combinations(edges.items(), 2):
            conj = conjunction(e1, e2, valid)
            name = f"conj_{n1}_{n2}"
            ratios[name] = conj
    
    return ratios
```

**Validation:**
```bash
python scripts/evaluate_new_fields.py --collar-px 3 --field rad_k_th_edge_conj --out docs/evidence/holdout_rad_ratios.json
```

---

### Hypothesis 5: Multi-Scale Curvature

**File:** `src/gems/fields.py` (add new field)

**Pseudocode:**
```python
def multi_scale_curvature(det_elev, valid, scales=[3, 6, 9, 12]):
    """Compute curvature at multiple scales and stack."""
    curvatures = []
    for scale in scales:
        # Gaussian smoothing at scale * 100m (scale is in pixels)
        smoothed = _gauss(det_elev, sigma=scale)
        # Laplacian for curvature
        curv = np.abs(_laplacian(smoothed))
        # Normalize
        curv = _nan_safe_z(curv, valid)
        curvatures.append(curv)
    
    # Stacking methods
    results = {}
    
    # Sum
    results['curv_multiscale_sum'] = np.clip(np.sum(curvatures, axis=0), 0, 1)
    
    # Max
    results['curv_multiscale_max'] = np.max(curvatures, axis=0)
    
    # Product (AND logic)
    prod = np.ones_like(curvatures[0])
    for c in curvatures:
        prod *= np.maximum(c, 1e-6)
    results['curv_multiscale_prod'] = prod
    
    return results
```

**Note:** Need to add to BANDS and FIELDS in fields.py

---

## 📝 DAILY WORK LOG

### 2026-09-29 (Session 1)
- [x] Reviewed repository structure
- [x] Created NEW_HYPOTHESES.md with 5 unique candidates
- [x] Created DATA_SOURCES.md with verified sources
- [x] Updated README.md with project charter
- [x] Created WORK_PLAN.md
- [ ] **NEXT:** Run data inventory script

**Time Spent:** ~2 hours  
**Next Session:** Start with data inventory, then implement H3

---

## 🚨 BLOCKERS AND RISKS

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Data not available in aux | Medium | High | Download from official sources |
| GDR 1391 download blocked | High | High | Use transported copies from sibling repos |
| Hypotheses don't beat baseline | Medium | Medium | Test multiple variants, validate thoroughly |
| Submission slots wasted | Low | High | NEVER submit without holdout validation |
| Compute limitations | High | Medium | Use explicit detectors, not deep learning |

---

## ✅ QUALITY CHECKLIST

Before considering any work complete:

1. **No Hallucinations**
   - [ ] Every factual claim has official source URL
   - [ ] Every measurement has reproducible command
   - [ ] All claims verified line-by-line

2. **Reproducibility**
   - [ ] All scripts have usage documentation
   - [ ] All random seeds are fixed
   - [ ] All data inputs are versioned (SHA-256)

3. **Auditability**
   - [ ] All results logged to docs/evidence/
   - [ ] All decisions documented
   - [ ] All failures recorded (negative results)

4. **Compliance**
   - [ ] All external data licenses verified
   - [ ] All sources disclosed in submission notes
   - [ ] All competition rules followed

---

## 📞 HELP AND REFERENCES

### Internal Documentation
- `README.md` - Project charter (read every session)
- `AUDIT.md` - Line-by-line verification log
- `NEW_HYPOTHESES.md` - New hypotheses to implement
- `DATA_SOURCES.md` - Free data sources inventory
- `docs/hypotheses.html` - Current hypothesis tracker
- `docs/holdout.html` - Holdout protocol and results

### External References
- Competition: https://www.drivendata.org/competitions/306/
- Rules: https://docs.nlr.gov/docs/fy26osti/96647.pdf
- GDR 1391: https://gdr.openei.org/submissions/1391
- GeoDAWN: https://doi.org/10.5066/P93LGLVQ

---

**Status:** Ready to begin Phase 1 (Data Inventory)  
**Next Action:** Run data inventory script to verify available aux data  
**Owner:** Autonomous agent (this session)  
**Review:** All work subject to line-by-line verification, no hallucinations

---

*Work line by line verifying from official verified trusted sources. No hallucinations.*
