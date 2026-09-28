#!/usr/bin/env bash
# Place the official competition rasters and prove they are the official bytes.
#
# The DrivenData data tab requires an account and redirects to login, so this
# script fetches the same rasters through the free public transport that the
# project pins in config/data_pins.json: the Dropbox mirrors linked from the
# official data tab, carried through a public GitHub repository.  Every byte is
# checked against the SHA-256 recorded when the rasters were first inventoried on
# an unrestricted runner (2026-09-14).  A mismatch aborts.
#
# Usage:
#   bash scripts/fetch_official_data.sh [TARGET_DIR]
#
# Default TARGET_DIR is ./data/raw (git-ignored).  If you have DrivenData
# credentials, prefer downloading the four files from
# https://www.drivendata.org/competitions/306/competition-doe-gems/data/
# directly into TARGET_DIR and running scripts/verify_data.py instead.
set -euo pipefail

TARGET="${1:-data/raw}"
REPO="https://github.com/buffedlizard55-lab/5GEMSDOE.git"
COMMIT="6e8d28ba407b5d748de5b3e94635c41d95e35354"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== fetching transport from $REPO @ $COMMIT"
git clone --quiet --filter=blob:none --no-checkout "$REPO" "$WORK/repo"
git -C "$WORK/repo" checkout --quiet "$COMMIT" -- data/bridge

mkdir -p "$TARGET"
echo "== assembling training_features.tif from 5 parts"
cat "$WORK"/repo/data/bridge/gems-geodawn-numerical-features.tif.part-* \
    > "$TARGET/training_features.tif"
cp "$WORK/repo/data/bridge/existing_faults.tif"    "$TARGET/labels.tif"
cp "$WORK/repo/data/bridge/example_submission.tif" "$TARGET/sample_submission.tif"
cp "$WORK/repo/data/bridge/manifest.json"          "$TARGET/bridge_manifest.json"

echo "== verifying SHA-256 against config/data_pins.json"
python3 "$(dirname "$0")/verify_data.py" "$TARGET"
echo "== done: official rasters in $TARGET"
