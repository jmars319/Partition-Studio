#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
TEST_IMAGES_DIR="$PROJECT_ROOT/test-images"
LOGS_DIR="$PROJECT_ROOT/logs"
LOG_FILE="/dev/null"

SCENARIO="normal-c-e-layout"
OUTPUT=""
DISK_SIZE="12GiB"
C_SIZE="4GiB"
E_SIZE="7GiB"
PARTITION_TABLE="gpt"
C_FILL_SIZE="3500MiB"
E_DATA_SIZE="2GiB"
FORMAT_NTFS=1
POPULATE=1
FORCE=0
DRY_RUN=0

usage() {
  cat <<'USAGE'
Create a disposable raw disk image under test-images/.

Usage:
  scripts/create_test_image.sh [options]

Options:
  --scenario NAME             Scenario name used for output filename.
  --output PATH               Output image path. Must be under test-images/.
  --disk-size SIZE            Raw image size. Default: 12GiB.
  --c-size SIZE               C partition size. Default: 4GiB.
  --e-size SIZE               E partition size. Default: 7GiB.
  --partition-table gpt|mbr   Partition table. Default: gpt.
  --c-fill SIZE               Synthetic data size for C. Default: 3500MiB.
  --e-data SIZE               Synthetic data size for E. Default: 2GiB.
  --no-format                 Create partitions only; skip NTFS formatting.
  --no-populate               Format but skip synthetic files.
  --force                     Replace an existing image.
  --dry-run                   Log commands without executing them.
  -h, --help                  Show this help.

Notes:
  Formatting and population require Linux, root, losetup, mkfs.ntfs, and mount support.
  Without those tools, the script still creates the partitioned raw image when possible.
USAGE
}

log() {
  printf '%s\n' "$*" | tee -a "$LOG_FILE"
}

run() {
  log "+ $*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@" 2>&1 | tee -a "$LOG_FILE"
  fi
}

die() {
  log "ERROR: $*"
  exit 1
}

size_to_mib() {
  PYTHONPATH="$SCRIPT_DIR" python3 - "$1" <<'PY'
import sys
from partitionlab_common import parse_size

size = parse_size(sys.argv[1])
mib = 1024 * 1024
if size % mib:
    raise SystemExit(f"size must be a whole MiB: {sys.argv[1]}")
print(size // mib)
PY
}

resolve_path() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path

print(Path(sys.argv[1]).resolve(strict=False))
PY
}

under_test_images() {
  local path="$1"
  local resolved_parent
  local resolved_path
  mkdir -p "$TEST_IMAGES_DIR"
  resolved_parent="$(cd "$TEST_IMAGES_DIR" && pwd -P)"
  resolved_path="$(resolve_path "$path")"
  [[ "$resolved_path" == "$resolved_parent"/* ]]
}

apply_scenario_defaults() {
  case "$SCENARIO" in
    normal-c-e-layout|gpt-layout)
      PARTITION_TABLE="gpt"
      ;;
    mbr-layout)
      PARTITION_TABLE="mbr"
      ;;
    e-has-insufficient-free-space)
      PARTITION_TABLE="gpt"
      E_DATA_SIZE="6500MiB"
      ;;
    dirty-filesystem-placeholder|encrypted-filesystem-placeholder|interrupted-operation-placeholder|non-adjacent-free-space)
      PARTITION_TABLE="gpt"
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario)
      SCENARIO="$2"
      shift 2
      ;;
    --output)
      OUTPUT="$2"
      shift 2
      ;;
    --disk-size)
      DISK_SIZE="$2"
      shift 2
      ;;
    --c-size)
      C_SIZE="$2"
      shift 2
      ;;
    --e-size)
      E_SIZE="$2"
      shift 2
      ;;
    --partition-table)
      PARTITION_TABLE="$2"
      shift 2
      ;;
    --c-fill)
      C_FILL_SIZE="$2"
      shift 2
      ;;
    --e-data)
      E_DATA_SIZE="$2"
      shift 2
      ;;
    --no-format)
      FORMAT_NTFS=0
      shift
      ;;
    --no-populate)
      POPULATE=0
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

apply_scenario_defaults

case "$PARTITION_TABLE" in
  gpt|mbr) ;;
  *) die "--partition-table must be gpt or mbr" ;;
esac

mkdir -p "$TEST_IMAGES_DIR" "$LOGS_DIR"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOGS_DIR/create_${SCENARIO}_${TIMESTAMP}.log"

if [[ -z "$OUTPUT" ]]; then
  OUTPUT="$TEST_IMAGES_DIR/${SCENARIO}.raw.img"
fi

under_test_images "$OUTPUT" || die "output must be under $TEST_IMAGES_DIR"

if [[ -e "$OUTPUT" && "$FORCE" -eq 0 ]]; then
  die "output already exists; use --force to replace it: $OUTPUT"
fi

log "tenra Partition Lab image creation"
log "scenario=$SCENARIO"
log "output=$OUTPUT"
log "disk_size=$DISK_SIZE c_size=$C_SIZE e_size=$E_SIZE partition_table=$PARTITION_TABLE"

C_MIB="$(size_to_mib "$C_SIZE")"
E_MIB="$(size_to_mib "$E_SIZE")"
C_START_MIB=1
C_END_MIB=$((C_START_MIB + C_MIB))
E_START_MIB="$C_END_MIB"
E_END_MIB=$((E_START_MIB + E_MIB))

if [[ "$FORCE" -eq 1 ]]; then
  run rm -f "$OUTPUT"
fi

run truncate -s "$DISK_SIZE" "$OUTPUT"

if [[ "$PARTITION_TABLE" == "gpt" ]]; then
  run parted -s "$OUTPUT" mklabel gpt
else
  run parted -s "$OUTPUT" mklabel msdos
fi

run parted -s -a optimal "$OUTPUT" unit MiB mkpart primary ntfs "${C_START_MIB}" "${C_END_MIB}"
run parted -s -a optimal "$OUTPUT" unit MiB mkpart primary ntfs "${E_START_MIB}" "${E_END_MIB}"

if command -v parted >/dev/null 2>&1; then
  run parted -s "$OUTPUT" unit s print free
fi

if [[ "$FORMAT_NTFS" -eq 0 ]]; then
  log "Skipping NTFS formatting because --no-format was provided."
  exit 0
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  log "Skipping NTFS formatting: loop-device formatting is Linux-only."
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  log "Skipping NTFS formatting: root is required for losetup and mount."
  exit 0
fi

for tool in losetup mkfs.ntfs mount umount; do
  command -v "$tool" >/dev/null 2>&1 || die "required tool not found for formatting: $tool"
done

LOOPDEV=""
MNT_C=""
MNT_E=""
cleanup() {
  set +e
  if [[ -n "$MNT_C" && -d "$MNT_C" ]]; then umount "$MNT_C" >/dev/null 2>&1; rmdir "$MNT_C" >/dev/null 2>&1; fi
  if [[ -n "$MNT_E" && -d "$MNT_E" ]]; then umount "$MNT_E" >/dev/null 2>&1; rmdir "$MNT_E" >/dev/null 2>&1; fi
  if [[ -n "$LOOPDEV" ]]; then losetup -d "$LOOPDEV" >/dev/null 2>&1; fi
}
trap cleanup EXIT

log "+ losetup --find --show --partscan $OUTPUT"
if [[ "$DRY_RUN" -eq 0 ]]; then
  LOOPDEV="$(losetup --find --show --partscan "$OUTPUT")"
  log "$LOOPDEV"
else
  LOOPDEV="/dev/loop-dryrun"
fi

P1="${LOOPDEV}p1"
P2="${LOOPDEV}p2"
if [[ "$DRY_RUN" -eq 0 ]]; then
  for _ in {1..20}; do
    [[ -b "$P1" && -b "$P2" ]] && break
    sleep 0.25
  done
  [[ -b "$P1" ]] || die "partition node not found: $P1"
  [[ -b "$P2" ]] || die "partition node not found: $P2"
fi

run mkfs.ntfs -F -L C "$P1"
run mkfs.ntfs -F -L E "$P2"

if [[ "$POPULATE" -eq 0 ]]; then
  log "Skipping synthetic test data because --no-populate was provided."
  exit 0
fi

command -v fallocate >/dev/null 2>&1 || die "required tool not found for population: fallocate"

MNT_C="$(mktemp -d)"
MNT_E="$(mktemp -d)"
run mount "$P1" "$MNT_C"
run mount "$P2" "$MNT_E"

run mkdir -p "$MNT_C/Windows/System32" "$MNT_C/Users/LabUser"
run mkdir -p "$MNT_E/data/projects" "$MNT_E/data/checksums"
run fallocate -l "$C_FILL_SIZE" "$MNT_C/Users/LabUser/fill-c-01.dat"
run fallocate -l "$E_DATA_SIZE" "$MNT_E/data/projects/archive-001.bin"

if command -v sha256sum >/dev/null 2>&1 && [[ "$DRY_RUN" -eq 0 ]]; then
  log "+ sha256sum $MNT_E/data/projects/archive-001.bin > $MNT_E/data/checksums/manifest.sha256"
  sha256sum "$MNT_E/data/projects/archive-001.bin" > "$MNT_E/data/checksums/manifest.sha256"
fi

run sync
run umount "$MNT_C"
run umount "$MNT_E"
rmdir "$MNT_C" "$MNT_E"
MNT_C=""
MNT_E=""

log "Created disposable image: $OUTPUT"
