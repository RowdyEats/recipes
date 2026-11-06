#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SITE_BASE_URL="${SITE_BASE_URL:-https://rowdyeats.github.io/recipes}"
export SITE_BASE_URL
python3 scripts/generate_content.py
python3 -m unittest discover -s tests -v
hugo build --gc --baseURL "${SITE_BASE_URL}/"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -a public/. "$TMP/"
# Add .nojekyll for GitHub Pages
touch "$TMP/.nojekyll"
git -C "$TMP" init -b gh-pages
git -C "$TMP" config user.email "rowdyeats@users.noreply.github.com"
git -C "$TMP" config user.name "RowdyEats"
git -C "$TMP" add -A
git -C "$TMP" commit -m "Publish static site to GitHub Pages"
git -C "$TMP" remote add origin "$(git -C "$ROOT" remote get-url origin)"
git -C "$TMP" push -f origin gh-pages
