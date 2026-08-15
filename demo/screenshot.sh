#!/usr/bin/env bash
# Capture a screenshot of the running demo visualizer (for deck assets).
# The server must already be up:  .venv/bin/python -m uvicorn demo.api:app --port 8080
#
# Usage:
#   ./demo/screenshot.sh                                   # default view -> docs/demo-screenshot.png
#   ./demo/screenshot.sh "http://localhost:8080/" out.png
#
# For a time-travel GIF, capture several years and assemble with ffmpeg/imagemagick
# (driving the slider needs a scripted browser e.g. Playwright — not required for a still).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
URL="${1:-http://localhost:8080/}"
OUT="${2:-docs/demo-screenshot.png}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[[ -x "$CHROME" ]] || { echo "Chrome not found at: $CHROME (set \$CHROME)"; exit 1; }
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size=1680,1000 \
  --screenshot="$ROOT/$OUT" --virtual-time-budget=10000 "$URL"
echo "wrote $OUT ($(wc -c < "$OUT") bytes)"
