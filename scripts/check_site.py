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

    print("check_site: %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
