#!/usr/bin/env bash
# Refresh the vendored legalrag package snapshot from the main source tree.
# The HF Space's Docker build context is this folder, so it can only COPY files
# that live here — hence the vendored copy. Re-run this if the main package
# changes and you want the Space to pick up the change, then rebuild/redeploy.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../../src/legalrag"
rm -rf "$HERE/vendor/legalrag"
cp -r "$SRC" "$HERE/vendor/legalrag"
find "$HERE/vendor" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
echo "refreshed vendor/legalrag from $SRC"
