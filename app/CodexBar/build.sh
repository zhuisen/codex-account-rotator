#!/usr/bin/env bash
# Build CodexBar.app with plain swiftc (no Xcode needed). Output: app/CodexBar/CodexBar.app
set -euo pipefail
cd "$(dirname "$0")"
APP="CodexBar.app"

# Versioning per CLAUDE.md: X.Y.Z + B.
#   SHORT (X.Y.Z) = release baseline — bump ONLY on a real release (batch / must-ship / user asks),
#                   NEVER per local build. Pre-1.0 dev stays at 0.1.0.
#   BUILD (B)     = build number, +1 every local build (the thing the user SEES change). Local-only.
SHORT="0.1.0"
BNFILE=".build_number"
BUILD=$(( $(cat "$BNFILE" 2>/dev/null || echo 0) + 1 )); echo "$BUILD" > "$BNFILE"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -o "$APP/Contents/MacOS/CodexBar" Sources/main.swift -framework AppKit

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>CodexBar</string>
    <key>CFBundleDisplayName</key><string>CodexBar</string>
    <key>CFBundleIdentifier</key><string>com.doushutangmu.codexbar</string>
    <key>CFBundleVersion</key><string>${BUILD}</string>
    <key>CFBundleShortVersionString</key><string>${SHORT}</string>
    <key>CFBundleExecutable</key><string>CodexBar</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSUIElement</key><true/>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>NSHumanReadableCopyright</key><string>codex-account-rotator</string>
</dict>
</plist>
PLIST

# ad-hoc sign so Gatekeeper/TCC treat it as a stable identity (no cert needed for local use)
codesign --force --deep --sign - "$APP" 2>/dev/null || echo "  (codesign skipped)"
echo "built $APP — ${SHORT}+${BUILD} ($(du -h "$APP/Contents/MacOS/CodexBar" | cut -f1))"
