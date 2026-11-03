#!/usr/bin/env bash
# Builds the Expo web app, starts the backend test harness + a static server and runs the browser E2E.
set -euo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8  # Chromium needs a UTF-8 locale for non-ASCII download names
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$(mktemp -d)}"
mkdir -p "$OUT"
(cd "$ROOT/mobile" && EXPO_OFFLINE=1 EXPO_PUBLIC_API_URL=http://127.0.0.1:8010 npx expo export --platform web --output-dir "$OUT/web" >/dev/null)
python3 "$ROOT/backend/tests/e2e_server.py" --port 8010 --cors http://127.0.0.1:8011 > "$OUT/backend.log" 2>&1 &
B=$!
python3 -m http.server 8011 --bind 127.0.0.1 --directory "$OUT/web" > "$OUT/static.log" 2>&1 &
S=$!
trap 'kill $B $S 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:8010/api/v1/health >/dev/null && break; sleep 1; done
node "$ROOT/e2e/wavify.e2e.js" http://127.0.0.1:8011 "$OUT/screenshots"
