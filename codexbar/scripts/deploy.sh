#!/usr/bin/env bash
# Build, sign, deploy CodexBar to /Applications.
# Auto-uses "CodexBar Self-Signed" if available (run setup-signing.sh once first).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IDENTITY="CodexBar Self-Signed"
APP="/Applications/CodexBar.app"
BUILD="$ROOT/src-tauri/target/release/bundle/macos/CodexBar.app"

cd "$ROOT"

echo "==> building…"
npx tauri build --bundles app 2>&1 | tail -3

echo "==> stopping old instance"
pkill -9 -f "CodexBar" 2>/dev/null || true
sleep 1

echo "==> deploying to $APP"
rm -rf "$APP"
cp -R "$BUILD" "$APP"

if security find-identity -p codesigning 2>/dev/null | grep -q "$IDENTITY"; then
    echo "==> signing with '$IDENTITY'"
    codesign --force --deep --sign "$IDENTITY" "$APP"
    codesign --verify --strict "$APP"
else
    echo "⚠️  '$IDENTITY' not found — using ad-hoc (run setup-signing.sh once to fix)"
fi

echo "==> launching"
open "$APP"
echo "✓ deployed"
