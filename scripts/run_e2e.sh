#!/usr/bin/env bash
# Runs the browser end-to-end test against a demo server (sample audio + offline fake Spotify).
# Usage: scripts/run_e2e.sh [output-dir]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$(mktemp -d)}"
PORT="${E2E_PORT:-8799}"
mkdir -p "$OUT"
python3 "$ROOT/backend/tests/demo_server.py" --port "$PORT" --data-dir "$OUT/data" > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 1; done
rm -rf "$OUT/export"
node "$ROOT/e2e/ui.e2e.js" "http://127.0.0.1:$PORT" "$OUT/data-media" "$OUT/screenshots" "$OUT/export"
echo "Screenshots: $OUT/screenshots"
