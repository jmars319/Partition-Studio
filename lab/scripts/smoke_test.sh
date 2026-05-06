#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

python3 "$SCRIPT_DIR/inspect_layout.py" "$PROJECT_ROOT/fixtures/normal-c-e-layout.json" --json >/dev/null
python3 "$SCRIPT_DIR/plan_operation.py" --layout "$PROJECT_ROOT/fixtures/normal-c-e-layout.json" --increase-c 40G --json >/dev/null
python3 "$SCRIPT_DIR/verify_layout.py" --before "$PROJECT_ROOT/fixtures/normal-c-e-layout.json" --increase-c 40G --json >/dev/null

if python3 "$SCRIPT_DIR/plan_operation.py" --layout "$PROJECT_ROOT/fixtures/e-has-insufficient-free-space.json" --increase-c 40G --json >/dev/null; then
  echo "expected insufficient-free-space fixture to block planning" >&2
  exit 1
fi

if python3 "$SCRIPT_DIR/verify_layout.py" --before "$PROJECT_ROOT/fixtures/dirty-filesystem-placeholder.json" --increase-c 40G --json >/dev/null; then
  echo "expected dirty filesystem placeholder to fail verification" >&2
  exit 1
fi

echo "smoke tests passed"
