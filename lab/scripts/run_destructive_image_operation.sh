#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
TEST_IMAGES_DIR="$PROJECT_ROOT/test-images"
LOGS_DIR="$PROJECT_ROOT/logs"
LOG_FILE="/dev/null"

IMAGE=""
INCREASE_C="40G"
DRY_RUN=0
ACK=0
ALLOW_LAB_BLOCK_DEVICE=0

usage() {
  cat <<'USAGE'
Guarded entrypoint for future destructive image operations.

Usage:
  scripts/run_destructive_image_operation.sh --image test-images/name.raw.img [options]

Options:
  --image PATH                               Target image. Must be under test-images/.
  --increase-c SIZE                         Amount to add to C. Default: 40G.
  --dry-run                                 Log the intended action without writes.
  --allow-lab-block-device                  Permit explicitly supplied lab loop devices.
  --i-understand-this-is-destructive         Required for future write mode.
  -h, --help                                Show this help.

Current status:
  Real partition mutation is intentionally not implemented in this phase.
  This script performs safety checks and logging, then refuses write mode.
USAGE
}

resolve_path() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path

print(Path(sys.argv[1]).resolve(strict=False))
PY
}

die() {
  printf 'ERROR: %s\n' "$*" | tee -a "$LOG_FILE" >&2
  exit 1
}

run() {
  printf '+ %s\n' "$*" | tee -a "$LOG_FILE"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@" 2>&1 | tee -a "$LOG_FILE"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --increase-c)
      INCREASE_C="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --allow-lab-block-device)
      ALLOW_LAB_BLOCK_DEVICE=1
      shift
      ;;
    --i-understand-this-is-destructive)
      ACK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$LOGS_DIR"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOGS_DIR/destructive_guard_${TIMESTAMP}.log"

[[ -n "$IMAGE" ]] || die "--image is required"

case "$IMAGE" in
  /dev/sda|/dev/nvme0n1|/dev/vda|/dev/xvda|/dev/disk0)
    die "refusing known system disk: $IMAGE"
    ;;
esac

if [[ "$IMAGE" == /dev/* && "$ALLOW_LAB_BLOCK_DEVICE" -ne 1 ]]; then
  die "refusing block device without --allow-lab-block-device"
fi

if [[ "$IMAGE" != /dev/* ]]; then
  RESOLVED_IMAGE="$(resolve_path "$IMAGE")"
  RESOLVED_TEST_IMAGES="$(cd "$TEST_IMAGES_DIR" && pwd -P)"
  [[ "$RESOLVED_IMAGE" == "$RESOLVED_TEST_IMAGES"/* ]] || die "image must be under $TEST_IMAGES_DIR"
  [[ -e "$RESOLVED_IMAGE" ]] || die "image not found: $RESOLVED_IMAGE"
else
  RESOLVED_IMAGE="$IMAGE"
fi

if [[ "$DRY_RUN" -eq 0 && "$ACK" -ne 1 ]]; then
  die "write mode requires --i-understand-this-is-destructive"
fi

printf 'tenra Partition Lab destructive guard\n' | tee -a "$LOG_FILE"
printf 'target=%s\nincrease_c=%s\ndry_run=%s\n' "$RESOLVED_IMAGE" "$INCREASE_C" "$DRY_RUN" | tee -a "$LOG_FILE"

INSPECT_ARGS=("$SCRIPT_DIR/inspect_image.py" --image "$RESOLVED_IMAGE" --json)
if [[ "$RESOLVED_IMAGE" == /dev/* ]]; then
  INSPECT_ARGS+=(--allow-lab-block-device --allow-outside-test-images)
fi
run "${INSPECT_ARGS[@]}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'Dry run complete. Real mutation is not implemented in this phase.\n' | tee -a "$LOG_FILE"
  exit 0
fi

die "real destructive partition mutation is intentionally not implemented yet"
