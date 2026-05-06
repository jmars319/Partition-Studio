#!/usr/bin/env bash
set -euo pipefail

APP_NAME="tenra Partition"
SOURCE_APP="src-tauri/target/release/bundle/macos/${APP_NAME}.app"
TARGET_APP="/Applications/${APP_NAME}.app"
LEGACY_APP="/Applications/tenra Partition Studio.app"

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "Missing built app at ${SOURCE_APP}" >&2
  echo "Run npm run package:desktop first." >&2
  exit 1
fi

rm -rf "$TARGET_APP"
ditto "$SOURCE_APP" "$TARGET_APP"
xattr -dr com.apple.quarantine "$TARGET_APP" 2>/dev/null || true
rm -rf "$SOURCE_APP"
rm -rf "$LEGACY_APP"
echo "Installed ${TARGET_APP}"
