#!/usr/bin/env bash

set -euo pipefail

REPORT_FILE="$(mktemp /tmp/validation.XXXXXX.json)"
LAST_OUTPUT=""

cleanup() {
  rm -f "$REPORT_FILE"
}

trap cleanup EXIT

while true; do
  python3 "scripts/generate_insight_weekly_report.py" --days 7 > "$REPORT_FILE"
  CURRENT_OUTPUT="$(cat "$REPORT_FILE")"
  if [ "$CURRENT_OUTPUT" != "$LAST_OUTPUT" ]; then
    echo "$CURRENT_OUTPUT"
    LAST_OUTPUT="$CURRENT_OUTPUT"
  fi

  READY="$(python3 - "$REPORT_FILE" <<'PY'
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text(encoding="utf-8"))
    print(str(bool(data.get("ready_for_decision", False))).lower())
except Exception:
    print("false")
PY
)"

  if [ "$READY" = "true" ]; then
    echo "READY_FOR_DECISION"
    exit 0
  fi

  sleep 5
done
