#!/usr/bin/env bash
# Build, sign, deploy CodexBar to /Applications.
# Auto-uses "CodexBar Self-Signed" if available (run setup-signing.sh once first).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IDENTITY="CodexBar Self-Signed"
APP="/Applications/CodexBar.app"
BUILD="$ROOT/src-tauri/target/release/bundle/macos/CodexBar.app"

cd "$ROOT"

# ★ 把仓库根烧进二进制。GUI app 不继承 shell 环境,不能指望运行期 env(见 lib.rs 的 store_dir)。
#   别人 clone 到任何路径,跑一次这个脚本就能用。
export CODEXBAR_STORE_DEFAULT="$(cd "$ROOT/.." && pwd)"
echo "==> store dir: $CODEXBAR_STORE_DEFAULT"

# 全新 clone 没有 node_modules,直接 tauri build 会挂。有 lockfile 用 ci(可复现),否则 install。
if [ ! -d "$ROOT/node_modules" ]; then
    echo "==> installing npm deps (first run)…"
    if [ -f "$ROOT/package-lock.json" ]; then npm ci; else npm install; fi
fi

echo "==> building…"
npx tauri build --bundles app 2>&1 | tail -3

# ★ 必须**优雅**退出,不能直接 SIGKILL。窗口尺寸/位置由 tauri-plugin-window-state 保存,而它只在
#   `CloseRequested` / `RunEvent::Exit` 时写盘 —— `pkill -9` 不给退出处理任何机会,于是
#   「调好高度 → 跑一次更新 → 尺寸又回默认」,正是这个持久化要解决的问题本身。
echo "==> stopping old instance (graceful)"
osascript -e 'tell application "CodexBar" to quit' 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -f "/Applications/CodexBar.app/Contents/MacOS/codexbar" >/dev/null 2>&1 || break
    sleep 0.3
done
# 兜底:优雅退出没成功(比如 app 卡住)才强杀,此时状态确实会丢,但总比装不上强。
if pgrep -f "/Applications/CodexBar.app/Contents/MacOS/codexbar" >/dev/null 2>&1; then
    echo "    (graceful quit timed out — force killing; window geometry may reset)"
    pkill -9 -f "CodexBar" 2>/dev/null || true
    sleep 1
fi

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
