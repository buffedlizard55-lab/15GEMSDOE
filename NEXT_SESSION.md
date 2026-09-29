# NEXT SESSION GUIDE - 15GEMSDOE

**Last Updated:** 2026-09-29 02:00 UTC  
**Previous Session:** IMPLEMENTATION_COMPLETE.md  
**Status:** Ready for next session

---

## 🎯 QUICK START (Run These Commands First)

```bash
# 1. Navigate to repo
cd /home/user/15GEMSDOE

# 2. Check what was accomplished
cat IMPLEMENTATION_COMPLETE.md | head -50

# 3. Check holdout evaluation status
ls -lh /tmp/holdout_new_rad_ratios.json 2>/dev/null || echo "Holdout not complete"

# 4. Verify data is in place
ls -lh data/raw/*.tif data/aux/*.tif
```

---

## 📋 PRIORITY TASK LIST

### Task 1: Analyze Holdout Results (5 min)
**If holdout evaluation completed:**
```bash
python3 << 'EOF'
import json

with open('/tmp/holdout_new_rad_ratios.json') as f:
    data = json.load(f)

print("=== STAGE 1 RESULTS (Tuning Draw) ===")
if 'stage1' in data:
    for field, results in sorted(data['stage1'].items(), key=lambda x: x[1].get('dti', 0), reverse=True):
        if results.get('dti', 0) > 0.04:
            print(f"{field:30s} DTI: {results['dti']:.6f}  area: {results.get('target_area_px', 'N/A')}")

print("\n=== STAGE 2 RESULTS (4 Withholding Rules) ===")
if 'stage2' in data:
    for rule in ['random', 'short', 'isolated', 'long']:
        if rule in data['stage2']:
            print(f"\n{rule.upper()} rule:")
            for field, dti in sorted(data['stage2'][rule]['dti'].items(), key=lambda x: x[1], reverse=True):
                if dti > 0.04:
                    print(f"  {field:30s} {dti:.6f}")

print("\n=== PROMOTION DECISION ===")
if 'stage2' in data and 'stage1' in data:
    baseline = data['stage1']['conj_alteration_mag']['dti']
    print(f"Baseline (conj_alteration_mag): {baseline:.6f}")
    
    new_fields = ['conj_rad_u_k_mag', 'conj_rad_multi_ratio_mag', 'conj_rad_closure_mag', 
                 'conj_rad_k_th_mag', 'conj_rad_u_th_mag']
    
    for field in new_fields:
        if field in data['stage1']:
            stage1_dti = data['stage1'][field]['dti']
            rules_won = 0
            if 'stage2' in data:
                for rule in ['random', 'short', 'isolated', 'long']:
                    if rule in data['stage2'] and field in data['stage2'][rule]['dti']:
                        if data['stage2'][rule]['dti'][field] > baseline:
                            rules_won += 1
            
            if stage1_dti > baseline and rules_won >= 3:
                print(f"✅ {field}: PROMOTE (Stage1: {stage1_dti:.6f}, Rules won: {rules_won}/4)")
            else:
                print(f"❌ {field}: NOT PROMOTED (Stage1: {stage1_dti:.6f}, Rules won: {rules_won}/4)")
EOF
```

**If holdout not complete:** Wait for it to finish or restart it:
```bash
python3 scripts/evaluate_new_fields.py --collar-px 3 --out /tmp/holdout_new_rad_ratios.json
```

---

## 🚀 TASK 2: Implement Hypothesis 5 (Multi-Scale Curvature) (30-45 min)

**Objective:** Capture faults of all sizes by detecting curvature at multiple scales

**Implementation:**
```bash
# Edit src/gems/fields.py
nano src/gems/fields.py
```

**Add to BANDS (around line 44):**
```python
BANDS = {
    "mag_anom": 0, "rtp": 1, "tmi_hg": 2, "geod_2ndinv": 3,
    "iso_grav_anom_slope": 4, "tc": 5, "geod_shearrate": 6,
    "geod_dilaterate": 7, "tmi_vg": 8, "deq_n100a15": 9,
    "iso_grav_anom_vg": 10, "det_elev": 11, "iso_grav_anom": 12, "tmi": 13,
    "depth_to_base_surf": 14, "ieq_n100a15": 15, "cond_surf": 16,
    "iso_grav_anom_hg": 17, "det_elev_slope": 18,
}
```

**Add to FIELDS (around line 47):**
```python
FIELDS = ("catalogue_proximity", "curv_scarp", "mag_tilt", "grav_grad",
          "cond_depth", "seismo_prior", "strain_ridge",
          "curv_multiscale_sum", "curv_multiscale_max", "curv_multiscale_prod")
```

**Add new field functions (before the _gauss function):**
```python
def _multi_scale_curvature(det_elev, valid, scales=[3, 6, 9, 12], sigma=1.0):
    """Multi-scale curvature for fault detection at different sizes."""
    curvatures = []
    for scale in scales:
        smoothed = _gauss(det_elev, sigma * scale)
        curv = np.abs(_laplacian(smoothed))
        curvatures.append(_nan_safe_z(curv, valid))
    
    # Sum
    curv_sum = np.clip(np.sum(curvatures, axis=0), 0, 1)
    # Max
    curv_max = np.max(curvatures, axis=0)
    # Product
    prod = np.ones_like(curvatures[0], dtype=np.float64)
    for c in curvatures:
        prod *= np.maximum(c, 1e-6)
    
    return {
        "curv_multiscale_sum": curv_sum.astype(np.float32),
        "curv_multiscale_max": curv_max.astype(np.float32),
        "curv_multiscale_prod": prod.astype(np.float32),
    }
```

**Add to build_fields function (around line 150):**
```python
    # Multi-scale curvature (H5)
    ms_curv = _multi_scale_curvature(base["det_elev"], valid)
    for k, v in ms_curv.items():
        out[k] = v
```

**Test the new fields:**
```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from src.gems import fields as F
import numpy as np
import rasterio

with rasterio.open('data/raw/labels.tif') as s:
    labels = s.read(1)
    valid = np.isfinite(labels)

fields = F.build_fields('data/raw/training_features.tif', valid, valid, sigma=1.0, tag='test')
for k in ['curv_multiscale_sum', 'curv_multiscale_max', 'curv_multiscale_prod']:
    if k in fields:
        print(f'{k}: min={fields[k].min():.4f}, max={fields[k].max():.4f}, mean={fields[k].mean():.4f}')
    else:
        print(f'{k}: NOT FOUND')
"
```

---

## 📥 TASK 3: Download GDR 1391 Data (Manual - 15 min)

**Objective:** Get spring, tufa, vent, heat flow, slip/dilation data

**Instructions:**
1. Open browser to: https://gdr.openei.org/submissions/1391
2. Click "Download" button for the full compilation
3. Extract the ZIP file
4. Copy relevant files to `data/aux/gdr_1391/`:
   ```
   data/aux/gdr_1391/
   ├── springs/          # Spring locations (shapefile or CSV)
   ├── tufa/            # Tufa/sinter deposits (shapefile or raster)
   ├── vents/           # Volcanic vents (shapefile or CSV)
   ├── heat_flow/       # Heat flow measurements (CSV or raster)
   ├── slip_dilation/   # Slip/dilation tendency grids (TIFF)
   └── temperature/     # 2m temperature probes (CSV or raster)
   ```
5. Verify CRS is EPSG:32611 and resolution is 100m (or can be resampled)

**Note:** If egress is blocked in sandbox, download on local machine and transfer.

---

## 🔬 TASK 4: Implement Hypothesis 1 (Spring-Tufa-Vent Alignment) (If GDR Data Available) (45-60 min)

**Objective:** Detect faults by aligning spring, tufa, and vent point patterns

**Implementation Steps:**

1. **Create KDE function in fields_ext.py:**
```python
def _point_kde(points_path, valid, bandwidth_px=5, sigma=1.0):
    """Create KDE grid from point data."""
    import pandas as pd
    import rasterio
    
    # Read points (assuming CSV with x,y columns in meter coordinates)
    df = pd.read_csv(points_path)
    
    # Create grid
    with rasterio.open('data/raw/labels.tif') as s:
        height, width = s.height, s.width
        transform = s.transform
    
    # Convert points to pixel coordinates
    points_px = []
    for _, row in df.iterrows():
        x, y = row['x'], row['y']  # Assuming columns are x,y in meters
        px, py = ~transform * (x, y)
        points_px.append((int(py), int(px)))
    
    # Create KDE grid
    from scipy.stats import gaussian_kde
    import numpy as np
    
    # Simple approach: create density grid
    grid = np.zeros((height, width), dtype=np.float32)
    for py, px in points_px:
        # Add Gaussian at each point
        for dy in range(-bandwidth_px, bandwidth_px + 1):
            for dx in range(-bandwidth_px, bandwidth_px + 1):
                ny, nx = py + dy, px + dx
                if 0 <= ny < height and 0 <= nx < width:
                    dist = np.sqrt(dx**2 + dy**2)
                    if dist <= bandwidth_px:
                        grid[ny, nx] += np.exp(-dist**2 / (2 * sigma**2))
    
    # Normalize
    grid = _nan_safe_z(grid, valid)
    return grid
```

2. **Add to build_aux_fields:**
```python
# Spring-Tufa-Vent KDE fields (H1)
if os.path.exists(os.path.join(aux_dir, "gdr_1391", "springs", "springs.csv")):
    cached("spring_kde", lambda: _point_kde(
        os.path.join(aux_dir, "gdr_1391", "springs", "springs.csv"),
        valid, bandwidth_px=5))

if os.path.exists(os.path.join(aux_dir, "gdr_1391", "tufa", "tufa.shp")):
    # For polygons, use centroid or rasterize
    pass  # TODO

if os.path.exists(os.path.join(aux_dir, "gdr_1391", "vents", "vents.csv")):
    cached("vent_kde", lambda: _point_kde(
        os.path.join(aux_dir, "gdr_1391", "vents", "vents.csv"),
        valid, bandwidth_px=5))
```

3. **Add conjunctions:**
```python
CONJUNCTIONS = {
    # ... existing ...
    # Spring-Tufa-Vent conjunctions (H1)
    "conj_spring_tufa_vent": ("spring_kde", "tufa_kde", "vent_kde"),
    "conj_spring_mag": ("spring_kde", "mag_tilt"),
    "conj_tufa_mag": ("tufa_kde", "mag_tilt"),
}
```

---

## ✅ TASK 5: Validate and Promote (15 min)

**For each implemented hypothesis:**

1. **Add to NEW_FIELDS in evaluate_new_fields.py:**
```python
NEW_FIELDS = (..., "curv_multiscale_sum", "curv_multiscale_max", "curv_multiscale_prod", ...)
```

2. **Run holdout evaluation:**
```bash
python3 scripts/evaluate_new_fields.py --collar-px 3 --out docs/evidence/holdout_<name>.json
```

3. **Check if beats baseline:**
```bash
# Compare with conj_alteration_mag (0.05302)
python3 -c "
import json
with open('docs/evidence/holdout_<name>.json') as f:
    data = json.load(f)
    
baseline = 0.05302
for field, results in data['stage1'].items():
    if results['dti'] > baseline:
        print(f'✅ {field} BEATS BASELINE: {results[\"dti\"]:.6f} > {baseline:.6f}')
"
```

4. **If promoted, create candidate:**
```bash
python3 scripts/make_candidate.py --field <field_name> --area 100000 --nms 1 --tag <unique_tag>
```

5. **Validate candidate:**
```bash
python3 scripts/validate_submission.py docs/downloads/<file>.tif --reference data/raw/sample_submission.tif
```

---

## 📊 EXPECTED OUTCOMES

| Task | Expected Time | Expected Outcome |
|------|---------------|------------------|
| Analyze holdout results | 5 min | Identify top performer |
| Implement H5 | 45 min | 3 new fields ready |
| Download GDR 1391 | 15 min (manual) | Data available |
| Implement H1 | 60 min | 3-5 new fields ready |
| Validate & Promote | 15 min | 1-2 candidates ready |

**Total:** ~2.5 hours  
**Deliverable:** 1-2 improved submissions ready for upload

---

## 🎯 SUCCESS CRITERIA FOR NEXT SESSION

### Minimum
- [ ] Holdout evaluation completed and analyzed
- [ ] H5 (Multi-Scale Curvature) implemented
- [ ] 1 new hypothesis beats baseline (0.05302)

### Stretch
- [ ] GDR 1391 data downloaded
- [ ] H1 (Spring-Tufa-Vent) implemented
- [ ] 2+ new hypotheses beat baseline

### Ultimate
- [ ] Candidate promoted and validated
- [ ] Submission file generated
- [ ] Ready to upload to DrivenData

---

## 🚨 BLOCKERS TO WATCH FOR

1. **Holdout evaluation not complete**
   - Solution: Restart with `python3 scripts/evaluate_new_fields.py`

2. **Missing dependencies**
   - Solution: `pip install --break-system-packages rasterio numpy scipy`

3. **GDR 1391 download blocked**
   - Solution: Download on local machine, transfer to sandbox

4. **Data format issues**
   - Solution: Check CRS and resolution, resample if needed

---

## 📞 QUICK REFERENCE

### Important Files
```
README.md                    # Project charter (read every session)
NEW_HYPOTHESES.md            # 5 new hypotheses to implement
DATA_SOURCES.md              # Verified data sources
WORK_PLAN.md                 # Prioritized task list
IMPLEMENTATION_COMPLETE.md   # What was accomplished
SESSION_SUMMARY_20260929.md  # Detailed session log

src/gems/fields.py           # Base detectors
src/gems/fields_ext.py       # Extended detectors (edit here)
scripts/evaluate_new_fields.py # Evaluation script (edit NEW_FIELDS)
scripts/make_candidate.py     # Candidate generation

data/raw/                   # Competition data (verified)
data/aux/                   # External data (partial)
```

### Important Commands
```bash
# Verify data
python3 scripts/verify_data.py data/raw

# Evaluate new fields
python3 scripts/evaluate_new_fields.py --collar-px 3 --out /tmp/results.json

# Make candidate
python3 scripts/make_candidate.py --field <name> --area 100000 --nms 1

# Validate submission
python3 scripts/validate_submission.py <file.tif> --reference data/raw/sample_submission.tif

# Check novelty
python3 scripts/audit_novelty.py

# Check acquisition
python3 scripts/audit_acquisition.py --candidate <file.tif>
```

### Important URLs
- Competition: https://www.drivendata.org/competitions/306/
- GDR 1391: https://gdr.openei.org/submissions/1391
- GeoDAWN: https://doi.org/10.5066/P93LGLVQ
- Rules: https://docs.nlr.gov/docs/fy26osti/96647.pdf

---

## 🏆 MOTIVATION

**Current Status:**
- We have the tools
- We have the data (partial)
- We have the hypotheses
- We have the pipeline

**What's Left:**
- Implement remaining hypotheses
- Validate on holdout
- Submit improved candidates

**Impact:**
- Each new hypothesis has potential to discover faults others miss
- Each submission increases our leaderboard position
- Each iteration brings us closer to the top

**Goal:** Beat 0.3049 and win the prize!

---

**Maximize P(Win) | Own the Outcome | No Hallucinations**
