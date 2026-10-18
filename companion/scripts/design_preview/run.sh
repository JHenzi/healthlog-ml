#!/bin/sh
# Rebuild the design-review page: the app's real templates rendered with synthetic data (never real data, R4).
#
#   companion/scripts/design_preview/run.sh <out-dir>     # writes <out-dir>/preview/companion-design-review.html
#
# Needs the throwaway test DB with the companion schema migrated: run companion/scripts/test.sh once first.
# Everything the renderer writes is rolled back.
set -eu

out=$(cd "${1:?usage: run.sh <out-dir>}" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)

rm -rf "$out/preview" && mkdir -p "$out/preview/screens/fonts"
docker run --rm --network host -v "$repo:/repo:ro" -v "$out:/out" -v healthlog-testpip314:/root/.cache/pip \
    -w /repo/companion python:3.14-slim sh -c "
        pip install -q --root-user-action=ignore -r requirements-dev.txt >/dev/null 2>&1
        PYTHONPATH=/repo/companion python -W ignore scripts/design_preview/render.py /out/preview/screens
        chown -R $(id -u):$(id -g) /out/preview"
cp "$repo/companion/web/static/style.css" "$out/preview/screens/"
cp "$repo"/companion/web/static/fonts/*.woff2 "$out/preview/screens/fonts/"
sed -i 's#https://testserver/#https://companion.example/#g' "$out"/preview/screens/*.html
cp "$here/review_template.html" "$out/review_template.html"
python3 "$here/build.py" "$out"
echo "$out/preview/companion-design-review.html"
