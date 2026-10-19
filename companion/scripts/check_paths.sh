#!/bin/sh
# R1 / risks.md A6: a companion branch may only change our own paths.
# Usage: companion/scripts/check_paths.sh [base-ref]   (default: upstream/dev, the branch the fork syncs from)
set -eu

base="${1:-upstream/dev}"
bad=$(git diff --name-only "$base"...HEAD -- | grep -Ev \
    '^(companion/|compose\.companion\.yml$|compose\.local\.yml$|\.github/workflows/companion[^/]*\.yml$|\.gitignore$)' || true)

if [ -n "$bad" ]; then
    echo "These upstream-owned files changed relative to $base (R1):"
    echo "$bad"
    exit 1
fi
echo "ok: only allowlisted paths changed relative to $base"
