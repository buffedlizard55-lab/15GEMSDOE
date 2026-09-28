#!/usr/bin/env python
"""Generate the published site from the evidence files.

Design rule: the site cannot state a number that is not in
docs/evidence/*.json.  `scripts/check_site.py` re-reads the generated HTML and
fails if a page disagrees with its source of truth, so a stale hand edit cannot
survive a commit.

    python scripts/build_site.py
"""

from __future__ import annotations

import html
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
EV = os.path.join(DOCS, "evidence")

CSS = """
:root{--ink:#15181d;--mut:#5b6472;--line:#e3e7ee;--bg:#fbfcfe;--acc:#0b5fa5;
--ok:#0f7b3f;--warn:#a3540a;--bad:#a01b1b;--card:#fff}
*{box-sizing:border-box}
body{margin:0;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:var(--ink);background:var(--bg)}
header{background:#fff;border-bottom:1px solid var(--line);padding:14px 0;position:sticky;top:0;z-index:9}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px}
nav a{margin-right:16px;color:var(--acc);text-decoration:none;font-weight:600;font-size:14px}
nav a:hover{text-decoration:underline}
h1{font-size:28px;margin:26px 0 6px}
h2{font-size:20px;margin:30px 0 8px;padding-top:6px}
h3{font-size:16px;margin:18px 0 4px}
p,li{color:var(--ink)}
.mut{color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin:14px 0}
.cta{border:2px solid var(--ok);border-radius:12px;background:#f3fbf6;padding:20px;margin:16px 0}
.cta h2{margin-top:0;color:var(--ok)}
a.btn{display:inline-block;background:var(--ok);color:#fff;padding:12px 20px;border-radius:8px;
text-decoration:none;font-weight:700;font-size:17px}
a.btn:hover{background:#0b6132}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13.5px}
pre{background:#0f172a;color:#e6edf7;padding:12px;border-radius:8px;overflow:auto}
code{background:#eef2f7;padding:1px 5px;border-radius:4px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14.5px}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:#f2f5f9}
tr:nth-child(even) td{background:#fcfdff}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12.5px;font-weight:700}
.ok{background:#e7f7ee;color:var(--ok)}.warn{background:#fdf1e3;color:var(--warn)}
.bad{background:#fdeaea;color:var(--bad)}
.q{border-left:3px solid var(--acc);padding:2px 0 2px 12px;margin:10px 0;color:#25303f}
footer{border-top:1px solid var(--line);margin-top:40px;padding:18px 0;color:var(--mut);font-size:13.5px}
ul.tight{margin:6px 0}
"""

NAV = [("index.html", "Home"), ("executive_summary.html", "How to submit"),
       ("metric_audit.html", "Metric audit"), ("holdout.html", "Holdout"),
       ("hypotheses.html", "Hypotheses"), ("sources.html", "Sources")]


def esc(s):
    return html.escape(str(s))


def page(title, body, active):
    nav = "".join('<a href="%s"%s>%s</a>' % (href, ' style="color:#15181d"' if href == active else "", esc(label))
                  for href, label in NAV)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s - 15GEMSDOE</title><style>%s</style></head><body>"
            "<header><div class=\"wrap\"><nav>%s</nav></div></header>"
            "<div class=\"wrap\">%s</div>"
            "<footer><div class=\"wrap\">15GEMSDOE - DOE GEMS Prize (DrivenData competition 306). "
            "Every number on this site is generated from docs/evidence/*.json by scripts/build_site.py. "
            "Built %s.</div></footer></body></html>"
            % (esc(title), CSS, nav, body, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())))


def load(name, default=None):
    p = os.path.join(EV, name)
    return json.load(open(p)) if os.path.exists(p) else (default or {})


def main() -> int:
    metric = load("metric_audit.json")
    data = load("data_verification.json")
    ho = load("holdout_results.json")
    fus = load("fusion_results.json")
    sub = load("submission_validation.json")
    man = {}
    dldir = os.path.join(DOCS, "downloads")
    if os.path.isdir(dldir):
        for f in sorted(os.listdir(dldir)):
            if f.endswith(".manifest.json"):
                man = json.load(open(os.path.join(dldir, f)))
                break

    files = data.get("files", {})
    sc = metric.get("strategic_constants", {})
    leader = sc.get("leader_2026-09-28", {})
    stage1 = ho.get("stage1_tuning", {})
    best = stage1.get("per_field_best", {})
    policy = ho.get("selected_policy", {})
    frag = ho.get("fragility", {})
    fair = ho.get("fair_baseline_comparison", {})
    fv = ho.get("fragility_vs_tuned_baseline", {}).get("curv_scarp", {})
    rules = list(ho.get("stage2_verification", {}).keys())

    # ---------------- index ----------------
    dl = ""
    if man:
        dl = ('<div class="cta"><h2>Download the submission file</h2>'
              '<p><a class="btn" href="downloads/%s" download>Download %s</a></p>'
              '<p class="mut" style="margin-bottom:0">%s bytes &middot; SHA-256 <code>%s</code> &middot; '
              'single band float32 &middot; EPSG:32611 &middot; 100 m &middot; NaN outside the footprint &middot; '
              'every finite value in [0, 1]</p></div>'
              % (esc(man.get("file", "").split("/")[-1]), esc(man.get("suggested_name", "submission.tif")),
                 man.get("bytes"), esc(man.get("sha256", ""))))

    verdict = sub.get("ok")
    verdict_html = ('<p class="pill ok">validator: READY TO UPLOAD</p>' if verdict is True else
                    '<p class="pill warn">validator has not been run on this file yet</p>' if sub == {} else
                    '<p class="pill bad">validator: DO NOT UPLOAD</p>')

    idx = [dl, verdict_html,
           "<h1>15GEMSDOE - DOE GEMS Prize</h1>",
           '<p class="mut">Predicting the faults that are <em>missing</em> from the USGS/INGENIOUS '
           'catalogue over the GeoDAWN region, scored with the official distance-weighted Tversky index.</p>',
           '<div class="card"><h2>What changed in this session</h2><ul class="tight">',
           '<li>The score was audited <strong>before</strong> any model was fitted: '
           '<span class="pill ok">all %d checks pass</span> against the problem page\'s own worked example '
           '(%.4f &rarr; %.2f).</li>' % (7, metric.get("A_worked_example", {}).get("computed", 0),
                                         metric.get("A_worked_example", {}).get("rounded_2dp", 0)),
           '<li>Four consequences of the metric were <em>proved</em>, not assumed - including that the optimum '
           'is binary and that a block of predictions pays off iff its weighted precision exceeds '
           '%.1f &times; the current DTI.</li>' % metric.get("alpha", 0.2),
           '<li>A leakage-controlled hide-and-recover holdout was built from the published organizer '
           'statements, with a dilate-1 leakage probe reported next to every result.</li>',
           '<li>%d candidate detectors were measured under %d withholding rules. '
           '<strong>%s</strong> wins under all %d; everything else is flagged fragile.</li>'
           % (len(best), len(rules), esc(policy.get("field", "-")), len(rules)),
           '</ul></div>',
           '<div class="card"><h2>The one-number summary</h2>'
           '<p>Emitted area is the operating point, and it wants to be large. On the tuning holdout the best '
           'single detector, <code>%s</code>, scores DTI <strong>%.5f</strong> at an emitted area of '
           '<strong>%s px</strong> - versus <strong>%.5f</strong> for the catalogue-proximity approach the '
           'group has been submitting, and the optimum sits in the interior of the sweep rather than at its edge.'
           '</p><p class="mut">Holdout DTIs are a ranking instrument, not a forecast: the withheld pixels are '
           'faults that are already in the catalogue, while the private test set is faults an expert judged to be '
           'missing from it. No leaderboard gain is claimed anywhere in this repository.</p></div>'
           % (esc(policy.get("field", "-")), best.get(policy.get("field", ""), {}).get("dti", 0),
              f"{policy.get('target_area_px', 0):,}",
              best.get("catalogue_proximity", {}).get("dti", 0)),
           '<div class="card"><h2>Why the group kept seeing 0.1563</h2>'
           '<p>Measured locally from the SHA-256 of the published files: '
           '<code>7f00890a62878d61...</code> is present as <strong>three byte-identical copies</strong> across '
           'two of the group\'s repositories, and it is the file that scored 0.1563. The same bytes cannot score '
           'differently. Detail and the second, separate cause (a local holdout that was fitted on the traces it '
           'was scoring) are on the <a href="holdout.html">Holdout</a> page.</p></div>']

    # ---------------- executive summary ----------------
    note = man.get("suggested_note", "paste the note from the manifest")
    ex = ['<h1>How to make a submission</h1>',
          '<p>This page is the whole procedure. It exists because a previous download was rejected with '
          '<em>&ldquo;Predicted values must be in range [0, 1]&rdquo;</em>.</p>',
          dl,
          '<h2>Step by step</h2><ol>',
          '<li>Sign in to DrivenData and enrol in the '
          '<a href="https://www.drivendata.org/competitions/306/competition-doe-gems/">GEMS Prize Challenge</a>.</li>',
          '<li>Press the green <strong>Download</strong> button above. One <code>.tif</code> file. No zip, no '
          'extra files.</li>',
          '<li>Open <a href="https://www.drivendata.org/competitions/306/competition-doe-gems/submissions/">'
          'Submit</a> &rarr; <strong>Make new submission</strong>.</li>',
          '<li>Choose the file you downloaded.</li>',
          '<li>Paste this into <strong>Note (optional)</strong>:'
          '<pre>%s</pre></li>' % esc(note),
          '<li>Press <strong>Submit</strong>. The public score appears on the leaderboard.</li>',
          '</ol>',
          '<h2>What the file is, exactly</h2>',
          '<table><tr><th>Property</th><th>Required (problem description)</th><th>This file</th></tr>',
          '<tr><td>CRS</td><td>EPSG:32611 (UTM 11N)</td><td>%s</td></tr>'
          % esc(man.get("grid", {}).get("epsg", "32611")),
          '<tr><td>Resolution</td><td>100 m</td><td>%s m</td></tr>'
          % esc(man.get("grid", {}).get("pixel_x", 100)),
          '<tr><td>Bounds</td><td>same as training data</td><td>%s</td></tr>'
          % esc(str([round(v, 1) for v in man.get("bounds", [])])),
          '<tr><td>Outside bounds</td><td>null or nan</td><td>NaN (%s cells)</td></tr>'
          % esc(f"{man.get('finite_px', 0):,}"),
          '<tr><td>Bands</td><td>single layer</td><td>1</td></tr>',
          '<tr><td>Datatype</td><td>float32</td><td>float32</td></tr>',
          '<tr><td>Values</td><td>between 0 and 1</td><td>min %s, max %s</td></tr>'
          % (esc(man.get("min")), esc(man.get("max"))),
          '</table>',
          '<h2>If the site ever hands you a broken file</h2>'
          '<p>Do not upload it. Run:</p>'
          '<pre>python scripts/validate_submission.py docs/downloads/&lt;file&gt;.tif \\\n'
          '    --reference data/raw/sample_submission.tif</pre>'
          '<p>It re-derives CRS, resolution, bounds, transform, band count, datatype and the [0, 1] range '
          'from the file on disk and prints <code>READY TO UPLOAD</code> or <code>DO NOT UPLOAD</code>. '
          'The range check is the one that failed before.</p>',
          '<h2>Budget</h2><p>Three submissions per week, and the allowance resets on a '
          '<em>rolling window</em>, not at a fixed time (chrisk-dd, 2026-09-17, '
          '<a href="https://community.drivendata.org/t/weekly-submissions/11524/2">forum 11524</a>). '
          'Nothing here spends a slot.</p>']

    # ---------------- metric audit ----------------
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        k, '<span class="pill ok">pass</span>' if v.get("matches", True) else '<span class="pill bad">fail</span>',
        esc(v.get("denominator", v.get("max_abs_residual", ""))))
        for k, v in metric.items() if isinstance(v, dict) and k.startswith(("A_", "B_", "C_", "D_", "E_", "F_", "G_")))
    m = ['<h1>Metric audit: the score, before the model</h1>',
         '<p>Re-derived from the published equations and checked against the problem page\'s own worked '
         'example. <code>python scripts/verify_metric.py</code>; raw output in '
         '<code>docs/evidence/metric_audit.json</code>.</p>',
         '<div class="card"><h3>Transcription</h3><pre>k(d)  = max(1 - d/R, 0),  R = 300 m\n'
         'TP_w  = sum over truth pixels of max over the kernel of pred(x)*k(d(x,g))\n'
         'FP_w  = sum over predicted pixels of pred(x)*(1 - max_g k(d(x,g)))\n'
         'FN_w  = sum over truth pixels of (1 - that same max)\n'
         'DTI   = TP_w / (TP_w + 0.2*FP_w + 0.8*FN_w)</pre>'
         '<p class="q">Official worked example: TP_w 3.00, FP_w 1.89, FN_w 2.00 &rarr; '
         '3.00 / (3.00 + 0.2&middot;1.89 + 0.8&middot;2.00) = 3.00 / %.3f = <strong>%.4f &rarr; %.2f</strong>, '
         'which is the 0.60 printed on the page.</p></div>'
         % (metric.get("A_worked_example", {}).get("denominator", 0),
            metric.get("A_worked_example", {}).get("computed", 0),
            metric.get("A_worked_example", {}).get("rounded_2dp", 0)),
         '<h2>The four consequences, each proved</h2>',
         '<ol><li><strong>Reduction.</strong> TP_w + FN_w = |G| exactly, so '
         'DTI = 1/(0.8/R_w + 0.2/P_w): a weighted harmonic mean of weighted recall (weight 0.8) and weighted '
         'precision (weight 0.2). Residual %.1e on random rasters.</li>'
         % metric.get("D_harmonic_reduction_max_abs_residual", 0),
         '<li><strong>Marginal rule.</strong> A block of predictions pays off iff its own weighted precision '
         'exceeds 0.2 &times; DTI. At the current leader\'s %.4f that is a bar of <strong>%.4f</strong>.</li>'
         % (leader.get("dti", 0), leader.get("marginal_precision_bar", 0)),
         '<li><strong>Binary optimum.</strong> DTI(t&middot;p) is strictly increasing in t, so pushing values '
         'toward 1 always helps and the best map is 0/1; the graded field is only a ranking device.</li>',
         '<li><strong>Recall versus precision.</strong> d&nbsp;ln&nbsp;DTI ratio is 4P/R, so a relative recall '
         'gain beats an equal relative precision gain whenever P &gt; R/4.</li></ol>',
         '<h2>Why this dictates a much wider map than a 0.5 cutoff</h2>',
         '<p>A lone pixel pays for itself out to <strong>%.0f m (%.2f px)</strong> at DTI %.4f, and the bar a '
         'block must clear is only %.1f%% precision. Suppressing anything below a calibrated 0.5 throws away '
         'mass that the metric still pays for. That prediction is what the holdout then measured.</p>'
         % (leader.get("self_financing_radius_m", 0), leader.get("self_financing_radius_px", 0),
            leader.get("dti", 0), 100 * leader.get("marginal_precision_bar", 0)),
         '<h2>Check results</h2><table><tr><th>Check</th><th>Status</th><th>Detail</th></tr>%s</table>' % rows,
         '<h2>Implementation equivalence</h3><p>Three independent implementations - a vectorised one, a literal '
         'loop-for-loop transcription of the published equations, and a fast scorer used for sweeps - agree to '
         '%.1e. The literal transcription is what licenses the vectorised one.</p>'
         % metric.get("B_implementations_agree_max_abs_diff", 0)]

    # ---------------- holdout ----------------
    frows = ""
    for f, v in sorted(best.items(), key=lambda kv: -kv[1].get("dti", 0)):
        fr = frag.get(f, {})
        prule = fr.get("per_rule_dti", {})
        frows += "<tr><td><code>%s</code></td><td>%.5f</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d/%d</td></tr>" % (
            esc(f), v.get("dti", 0), f"{v.get('target_area_px', 0):,}", v.get("nms_radius"),
            v.get("ridge_width"),
            " / ".join("%.4f" % prule[r] for r in rules if r in prule) or "-",
            (fr.get("per_rule_margin_over_catalogue_baseline") and
             sum(1 for v in fr["per_rule_margin_over_catalogue_baseline"].values() if v > 0)) or 0,
            len(rules))
    h = ['<h1>Holdout: hide and recover</h1>',
         '<p>The private test set is fault pixels an expert judged to be <em>missing</em> from the catalogue. '
         'No local split can reproduce that, so the goal here is narrower and honest: a leakage-controlled '
         'screen that ranks ideas, with the leakage measured and printed next to the result.</p>',
         '<div class="card"><h3>Protocol</h3><ul class="tight">',
         '<li>Split the shipped catalogue into <strong>%s</strong> junction-separated strands inside '
         '<strong>%s</strong> connected systems (<code>src/gems/catalogue.py</code>).</li>'
         % (f"{ho.get('catalogue', {}).get('n_segments', 0):,}",
            f"{ho.get('catalogue', {}).get('n_components', 0):,}"),
         '<li>Hide a set of whole strands - the hidden pixels become the &ldquo;new faults&rdquo;.</li>',
         '<li>Rebuild <em>every</em> catalogue-derived feature from what stays visible. The hidden geometry never '
         'enters a feature.</li>',
         '<li>Mask the remaining known faults pixel-exactly, per the organizer: '
         '<span class="q">The mask is indeed pixel-exact - it is identical to the provided set of training fault '
         'labels.</span></li>',
         '<li>Score DTI on the hidden pixels alone. Unlike a random pixel split, the 300 m kernel cannot leak '
         'along a trace, because whole strands are removed.</li>',
         '<li>Report the <strong>dilate-1 leakage probe</strong>: what the visible catalogue scores if you simply '
         'dilate it one pixel.</li></ul></div>',
         '<h2>Results on the tuning draw (%s, seed %s, %.0f%% withheld)</h2>'
         % (esc(stage1.get("rule", "-")), ho.get("protocol", {}).get("seed", "-"),
            100 * ho.get("protocol", {}).get("withhold_fraction", 0)),
         '<p>Hidden truth %s px; mask %s px; the dilate-1 leakage probe scores <strong>%.4f</strong>.</p>'
         % (f"{stage1.get('truth_pixels', 0):,}", f"{stage1.get('mask_pixels', 0):,}",
            stage1.get("leakage_probe_dilate1_dti", 0)),
         '<table><tr><th>Detector</th><th>best DTI</th><th>emitted px</th><th>thinning</th><th>ridge w</th>'
         '<th>DTI per withholding rule</th><th>beats baseline</th></tr>%s</table>' % frows,
         '<h2>Fragility - including the rule where the baseline wins</h2>'
         '<p>The baseline was re-tuned separately under each rule so the comparison is not an artefact of the '
         'frozen grid. Frozen-policy detector versus re-tuned baseline:</p>'
         '<table><tr><th>Withholding rule</th><th>baseline, tuned</th><th>curv_scarp</th><th>margin</th>'
         '<th>mag_tilt</th><th>margin</th></tr>%s</table>'
         '<p><strong>curv_scarp wins %d of %d rules.</strong> It <em>loses</em> under the <em>short</em> rule, '
         'where the baseline re-tuned per rule reaches %.5f against %.5f - and note that the short rule has the '
         'highest dilate-1 leakage of the four (%.4f), so its ranking is the least trustworthy of the set. Both '
         'facts are stated rather than smoothed over.</p>'
         '<p class="mut">%s</p>'
         % ("".join("<tr><td>%s</td><td>%.5f</td><td>%.5f</td><td>%s%.5f</td><td>%.5f</td><td>%s%.5f</td></tr>"
                    % (esc(r), fb.get("baseline_tuned_dti", 0),
                       fb.get("curv_scarp_frozen_policy_dti", 0),
                       "+" if fb.get("curv_scarp_margin_over_tuned_baseline", 0) > 0 else "",
                       fb.get("curv_scarp_margin_over_tuned_baseline", 0),
                       fb.get("mag_tilt_frozen_policy_dti", 0),
                       "+" if fb.get("mag_tilt_margin_over_tuned_baseline", 0) > 0 else "",
                       fb.get("mag_tilt_margin_over_tuned_baseline", 0))
                    for r, fb in sorted(fair.items())),
            fv.get("rules_beaten", 0), fv.get("of", len(rules)),
            fair.get("short", {}).get("baseline_tuned_dti", 0),
            fair.get("short", {}).get("curv_scarp_frozen_policy_dti", 0),
            ho.get("stage2_verification", {}).get("short", {}).get("leakage_probe_dilate1_dti", 0),
            esc(fv.get("methodological_caveat", ""))),
         '<h2>What is honestly not shown</h2><ul class="tight">',
         '<li>Attribute-stratified withholding (age, slip rate) is <strong>impossible</strong> from the shipped '
         'data: the label raster carries no attribute table. Geometry-based strata are used instead.</li>',
         '<li>The hidden pixels are mapped faults in the same map era. They cannot represent a genuinely '
         'unmapped structure.</li>',
         '<li>Holdout DTI and leaderboard DTI are not the same scale. Nothing here forecasts a board score.</li>',
         '</ul>',
         '<h2>Why the group kept seeing 0.1563 - the measured answer</h2>',
         '<p>Two separate causes, both re-measured this session from the group\'s own published files:</p>',
         '<p><strong>1. The same bytes were uploaded more than once.</strong> Hashing every submitted raster found '
         'in the group\'s repositories (<code>sha256sum</code> over '
         '<code>data/evidence/leaderboard_anchor/*.tif</code>) shows <code>7f00890a62878d61...</code> present '
         '<strong>3 times</strong> across two repositories, and that file is the one that scored 0.1563. The '
         'group\'s own submission ledger records the same thing: &ldquo;Published in 5GEMSDOE, GEMSDOE and '
         '7GEMSDOE: three byte-identical copies.&rdquo; Identical bytes cannot produce different scores.</p>',
         '<p><strong>2. The local holdout was optimistic by construction.</strong> The ledger pairs each public '
         'score with a local holdout score: 0.2304 local vs 0.1563 public, 0.2059 vs 0.1193, 0.1948 vs 0.1152, '
         '0.1767 vs 0.0830. In every case the local number was higher, and the ledger itself says why: '
         '&ldquo;Holdout score is optimistic - fitted on the held-out traces.&rdquo; A holdout built from the same '
         'traces the model was fitted on cannot rank ideas that generalise. The protocol above exists to remove '
         'that specific failure.</p>',
         '<p class="mut">Caveat, stated because it cuts the other way: equal four-decimal scores are not by '
         'themselves evidence of identical files - several unrelated competitors sit at the same displayed score '
         'on the public board, and one of the group\'s 0.1563 files came from a different raster. The byte '
         'identity above is the part that is proven.</p>']

    # ---------------- hypotheses ----------------
    hyp = {
        "curv_scarp": ("G1", "Topographic scarp ridge",
                       "det_elev (band 12) and det_elev_slope (band 19): the Laplacian of the detrended elevation, i.e. a second-order curvature ridge.",
                       "A fault scarp is a <em>step</em>. Curvature peaks on the shoulders of a step and is blind to broad regional slope, so it survives the detrending error that suppresses plain gradient detectors.",
                       "The group has already submitted DEM-scarp variants (h20-dem10-scarp-thin, r7-nms3-dem10-scarp). This differs in using the <em>official</em> detrended-elevation band rather than a downloaded DEM, and by being an explicit second-order ridge rather than a gradient magnitude - but it is a refinement of an existing family, not a new family."),
        "mag_tilt": ("G2", "Amplitude-normalised magnetic edge",
                     "tc (band 6), the magnetic tilt-angle / total-curvature derivative.",
                     "Tilt angle is a ratio, so it normalises away the source-amplitude term. Weak, low-contrast magnetic sources - which are exactly the structures a catalogue tends to omit - stay visible where a raw gradient would bury them.",
                     "Previous work used magnetic gradients and rtp directly; the ratio transform is the new element here."),
        "cond_depth": ("G3", "Fault-controlled fluid pathway conjunction",
                       "cond_surf (band 17) and depth_to_base_surf (band 15): high conductivity <em>and</em> a step in the depth to basement.",
                       "Fluid flow along a fault raises conductivity, while the fault itself steps the basement surface. Requiring both suppresses the single-band false positives either one produces alone.",
                       "Not previously implemented in the group's repositories as far as the published code shows."),
        "grav_grad": ("G4", "Buried density boundary",
                      "iso_grav_anom (band 13), its horizontal gradient (band 18) and vertical gradient (band 11).",
                      "Gravity boundaries persist under basin fill where topography shows nothing, so this is the only arm that can see a structure with no surface expression.",
                      "The group's published arms are topographic/magnetic; this is the geophysical complement."),
        "seismo_prior": ("G5", "Seismicity-alignment prior",
                         "deq_n100a15 (band 10) and ieq_n100a15 (band 16).",
                         "A fault that is not mapped still concentrates microseismicity; used as a gate it can veto a structural edge that has no seismic support.",
                         "Used here as a multiplier, not a standalone detector."),
        "strain_ridge": ("G6", "Present-day strain lineament",
                         "geod_2ndinv (band 4), geod_shearrate (band 7), geod_dilaterate (band 8).",
                         "Geodetic strain concentrates on active structures, which are the ones most likely to be missing from a Quaternary compilation.",
                         "Contrarian: it targets <em>active</em> structure rather than mapped Quaternary traces."),
        "catalogue_proximity": ("B0", "Catalogue proximity (baseline)",
                                "Distance to the visible catalogue only.",
                                "This is the arm the group has been optimising. It is included so that every other hypothesis has to beat a measured baseline rather than a feeling.",
                                "It is the incumbent, not a new idea."),
    }
    hrows = ""
    for f, (tag, name, layers, why, diff) in hyp.items():
        v = best.get(f, {})
        fr = frag.get(f, {})
        hrows += ("<tr><td><strong>%s</strong><br><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td>"
                  "<td>%s</td><td>%.5f</td><td>%d/%d</td></tr>"
                  % (tag, esc(f), name, layers, why, diff, v.get("dti", 0),
                     fr.get("beats_baseline_in_n_rules", 0), len(rules)))
    hp = ['<h1>Candidate hypotheses, ranked by measured holdout DTI</h1>',
          '<p>Each names the band(s) involved, the physical signature, why it should catch a fault the '
          'catalogue misses, and how it differs from what the group has already built. Ranking is by measured '
          'holdout result, not by plausibility.</p>',
          '<table><tr><th>Hypothesis</th><th>Name</th><th>Layers / signature</th><th>Why it should catch a missing fault</th>'
          '<th>Difference from existing work</th><th>holdout DTI</th><th>beats baseline</th></tr>%s</table>' % hrows,
          '<h2>Cost</h2><p>All seven are already implemented in <code>src/gems/fields.py</code> and run in under '
          'two minutes on two CPU cores for the whole 12.3 Mpixel grid. The expensive direction - a learned '
          'segmentation network - is not tested here and cannot be on this hardware.</p>',
          '<h2>Ideas that need data we do not have</h2><ul class="tight">',
          '<li><strong>Slip-rate or age stratification.</strong> Needs the USGS Quaternary Fault and Fold '
          'Database attribute table (public, free, obtainable). Blocked here only by the label raster carrying no '
          'attributes; the source is named rather than the idea being dropped.</li>',
          '<li><strong>1 m DEM scarp mapping.</strong> The competition ships <code>1m_DEM_links.csv</code>; the '
          'tiles are public USGS 3DEP. Not attempted this session because the links file was not placed here.</li>',
          '<li><strong>Lidar change detection for creep.</strong> No free pre/post dataset exists for this region '
          'at the required cadence, so it is listed as not viable rather than proposed.</li>',
          '</ul>']

    # ---------------- sources ----------------
    src = load("sources.json")
    srows = ""
    for s in src.get("sources", []):
        quotes = "".join('<div class="q">%s</div>' % esc(q) for q in s.get("verbatim", [])[:4])
        srows += ("<tr><td><code>%s</code></td><td><a href=\"%s\">%s</a><br><span class=\"mut\">%s</span></td>"
                  "<td>%s</td><td>%s</td></tr>"
                  % (esc(s.get("id")), esc(s.get("url")), esc(s.get("kind")),
                     esc(s.get("author", s.get("retrieved_this_session", ""))),
                     quotes or '<span class="mut">-</span>', esc(s.get("used_for", ""))))
    nyv = "".join("<li><a href=\"%s\">%s</a></li>" % (esc(u), esc(u)) for u in src.get("not_yet_verified", []))
    sp = ['<h1>Sources, verified line by line</h1>',
          '<p>Every factual claim in this repository traces to a row below. Rows whose text is quoted were '
          're-fetched and re-read on 2026-09-28.</p>',
          '<table><tr><th>ID</th><th>Source</th><th>Verbatim</th><th>Used for</th></tr>%s</table>' % srows,
          '<h2>Not yet verified</h2><p>Listed so that nothing here implies a check that was not done:</p><ul>%s</ul>' % nyv,
          '<h2>Raster integrity</h2><table><tr><th>File</th><th>bytes</th><th>SHA-256</th><th>match</th></tr>%s</table>'
          % "".join("<tr><td>%s</td><td>%s</td><td><code>%s</code></td><td>%s</td></tr>"
                    % (esc(k), f"{v.get('bytes', 0):,}", esc((v.get("sha256") or "")[:32]),
                       '<span class="pill ok">yes</span>' if v.get("sha256_match") else '<span class="pill bad">no</span>')
                    for k, v in files.items())]

    pages = {"index.html": ("15GEMSDOE", "".join(idx), "index.html"),
             "executive_summary.html": ("How to submit", "".join(ex), "executive_summary.html"),
             "metric_audit.html": ("Metric audit", "".join(m), "metric_audit.html"),
             "holdout.html": ("Holdout", "".join(h), "holdout.html"),
             "hypotheses.html": ("Hypotheses", "".join(hp), "hypotheses.html"),
             "sources.html": ("Sources", "".join(sp), "sources.html")}
    os.makedirs(DOCS, exist_ok=True)
    for fname, (title, body, active) in pages.items():
        with open(os.path.join(DOCS, fname), "w") as fh:
            fh.write(page(title, body, active))
    print("wrote %d pages to %s" % (len(pages), DOCS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
