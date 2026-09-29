#!/usr/bin/env python
"""Fail if a published page has drifted from its evidence file.

The site is generated from docs/evidence/*.json, so a hand edit that changes a
number cannot survive: this re-reads the JSON and asserts the formatted value
appears in the HTML.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(ROOT, "docs", "evidence")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    ok = True
    ho = json.load(open(os.path.join(EV, "holdout_results.json")))
    holdout_html = read(os.path.join(ROOT, "docs", "holdout.html"))
    for rule, row in ho["fair_baseline_comparison"].items():
        for key, val in row.items():
            if not isinstance(val, float):
                continue
            s = "%.5f" % val
            if s not in holdout_html:
                print("MISSING %s %s = %s" % (rule, key, s))
                ok = False

    metric = json.load(open(os.path.join(EV, "metric_audit.json")))
    if not metric.get("all_checks_pass"):
        print("metric audit does not pass")
        ok = False
    audit_html = read(os.path.join(ROOT, "docs", "metric_audit.html"))
    if "%.1e" % metric["B_implementations_agree_max_abs_diff"] not in audit_html:
        print("metric audit page does not carry the implementation-agreement figure")
        ok = False

    val = json.load(open(os.path.join(EV, "submission_validation.json")))
    if not val.get("ok"):
        print("submission validator did not pass; the site must not offer the file")
        ok = False
    idx = read(os.path.join(ROOT, "docs", "index.html"))
    if "READY TO UPLOAD" not in idx:
        print("index.html does not state the validator verdict")
        ok = False

    # the download button must serve the newest manifest, and the audits page must
    # carry the chargeable numbers it is allowed to state
    dldir = os.path.join(ROOT, "docs", "downloads")
    mans = [json.load(open(os.path.join(dldir, f)))
            for f in sorted(os.listdir(dldir)) if f.endswith(".manifest.json")]
    if mans:
        newest = max(mans, key=lambda mm: str(mm.get("generated_utc", "")))
        href = 'href="downloads/%s"' % os.path.basename(newest.get("file", ""))
        if href not in idx and "downloads/%s" % os.path.basename(newest.get("file", "")) not in idx:
            print("index.html does not offer the newest manifest file: %s" % newest.get("file"))
            ok = False
        if newest.get("sha256", "")[:8] and newest["sha256"][:8] not in idx:
            print("index.html does not carry the newest file's SHA-256 prefix")
            ok = False
    chg = json.load(open(os.path.join(EV, "chargeable_support.json")))
    audits = read(os.path.join(ROOT, "docs", "audits.html"))
    if f"{chg['chargeable_zone_px']:,}" not in audits:
        print("audits.html does not carry the chargeable-zone pixel count")
        ok = False
    if len(chg.get("chargeable_identical_groups", [])) and "chargeably identical" not in audits.lower():
        print("audits.html does not explain the chargeable-identity mechanism")
        ok = False

    print("check_site: %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
