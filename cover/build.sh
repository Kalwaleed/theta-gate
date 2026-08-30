#!/usr/bin/env bash
# Render cover.html -> cover.png at exactly 1920x1080 (16:9).
#
# Chrome rather than a design tool so the cover is reproducible from source
# and shares one palette with app.py and docs/diagrams/*.html. --hide-scrollbars
# matters: without it Chrome reserves gutter width and the output is not 16:9.
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[ -x "$CHROME" ] || { echo "Chrome not found; set CHROME=/path/to/chrome" >&2; exit 1; }
"$CHROME" --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --window-size=1920,1080 --virtual-time-budget=10000 \
  --default-background-color=FFF5F5F5 \
  --screenshot="$PWD/cover.png" "file://$PWD/cover.html" 2>/dev/null
echo "wrote cover.png ($(sips -g pixelWidth -g pixelHeight cover.png 2>/dev/null | tail -2 | tr -d ' \n'))"
