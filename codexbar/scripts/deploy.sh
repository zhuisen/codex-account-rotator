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

# ★ 构建号 `B` 不在这里维护了 —— `src-tauri/build.rs` 从 git 现算
#   （发版后本地就是 release ⇒ B=0 ⇒ 显示纯 `vX.Y.Z`；改过才有 `+B`）。
#   见 CLAUDE.md §3.7。这里刻意什么都不做，别把计数器加回来。

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

# ⚠️ 不用 `grep -q`：它匹配到就退出，`security` 若还在写会吃 SIGPIPE，pipefail 让整个条件
#   变成**假** —— 静默落到下面 ad-hoc 那一支，下次启动重新弹 TCC 授权（同 `_running` 那条竞态）。
if security find-identity -p codesigning 2>/dev/null | grep -F "$IDENTITY" >/dev/null; then
    echo "==> signing with '$IDENTITY'"
    codesign --force --deep --sign "$IDENTITY" "$APP"
    codesign --verify --strict "$APP"
else
    echo "⚠️  '$IDENTITY' not found — using ad-hoc (run setup-signing.sh once to fix)"
fi

echo "==> launching"
open "$APP"

# ★★★ **核实跑起来的真的是刚装的这一份**（2026-09-21 补，事故驱动）。
#
#   本机有 **3 个 bundle 共用 `com.doushutangmu.codexbar`**：/Applications、构建树
#   `src-tauri/target/release/bundle/macos/`、以及 `~/archive/...` 里的快照备份。
#   单实例闸是 flock（CLAUDE.md §5 / .claude/rules/ui.md），谁先抢到锁谁活，
#   **后来者判 `HeldByOther` 后静默退出** —— 那是设计，不是缺陷。
#
#   ⚠️ 但两件事叠在一起就成了陷阱：archive 里那份 **v1.4.1（2026-09-08）** 抢着锁，
#   于是 `open /Applications/CodexBar.app` **每次都无声无息地什么都没发生**，
#   用户对着一个 13 天前的构建看了很久，症状是「菜单栏 AI 用量变成全量展示」
#   ——那恰好是 v1.4.1 之后三个 commit 才修的东西。
#   deploy 全程报「✓ deployed」，因为它只管装、从不看**谁在跑**。
#
#   ★ 同族判据：本仓已有的「常驻服务代码 ✓ 均为最新」比的是进程启动时刻 vs 源码 mtime。
#     这里比的是**可执行文件路径** —— 同一个问题的另一面：装好了 ≠ 跑起来了。
sleep 3
# ⚠️ **awk 里不许 `exit`，管道尾巴上也不许 `head`**（2026-09-23 实测）。本脚本开着
#   `set -euo pipefail`：awk 读到第一行就退出会关掉管道，`ps` 还在写就吃 SIGPIPE（exit 141），
#   pipefail 把它算成整条管道失败，`set -e` 随即**静默杀掉整个 deploy.sh** ——
#   后面的版本号与 B≠0 告警一行都不打，而看上去和成功一模一样（新包其实已经装好并启动了）。
#   是竞态：`ps` 写得比 awk 退出快就不触发，所以时好时坏。闸：tests/test_deploy_script_sigpipe.py。
_running="$(ps -Ao pid=,comm= | awk '$2 ~ /codexbar$/ && !f {print $1; f=1}')"
if [ -z "$_running" ]; then
    echo "⚠️  启动后没看到 codexbar 进程 —— 它可能被单实例闸挡住了，或者崩了。"
elif [ "$(ps -o comm= -p "$_running")" != "$APP/Contents/MacOS/codexbar" ]; then
    echo "🛑 **跑起来的不是刚装的那一份！**"
    echo "   期望: $APP/Contents/MacOS/codexbar"
    echo "   实际: $(ps -o comm= -p "$_running")  (pid $_running)"
    echo "   原因：同 bundle id 的另一个副本先抢到了单实例锁，新装的这份静默退出了。"
    echo "   处理：先退掉上面那个进程（osascript -e 'tell application \"CodexBar\" to quit'），"
    echo "        再重新 open '$APP'；并考虑把那个陈旧副本移走/改名。"
fi

# ★★★ 把这次烤进产物的版本号**当场打出来**（2026-09-17 补）。
#
#   起因：v1.6.1 发版后用户在界面上看到 `v1.6.1+10`。产物没错 —— 它确实是在
#   `git tag` **之前 38 秒**、从一个脏工作区构建的，`B` 从 git 现算就是 10。
#   错的是顺序（见 CLAUDE.md §3）。但真正让它难发现的是：
#   **deploy 全程不说自己烤了什么版本**，于是"版本对不对"要等用户打开界面才知道。
#   ★ 一个在动作发生那一刻就能看见的事实，不该留到事后由人去界面上发现。
# ★ 用脚本开头就算好的 `$ROOT`（绝对路径）—— 此处已经 `cd "$ROOT"` 过，
#   再拿 `$0` 推相对路径会解析失败，实测当场把版本打成 `?`。
VER=$(node -p "require('$ROOT/src-tauri/tauri.conf.json').version" 2>/dev/null || echo "?")
TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [ -n "$TAG" ]; then
    B=$(git rev-list --count "$TAG..HEAD" 2>/dev/null || echo 0)
    [ -n "$(git status --porcelain 2>/dev/null)" ] && B=$((B + 1))
else
    B=0
fi
if [ "$B" = "0" ]; then
    echo "✓ deployed — v${VER}（B=0：你跑的这份**就是** release）"
else
    echo "✓ deployed — v${VER}+${B}"
    echo "   ⚠️  B=${B} ≠ 0：这份产物**不是** release。距 ${TAG:-?} 有 $((B)) 个改动。"
    # ★★ 把 B 拆成「commit 数」与「脏文件」两项分别报（2026-09-19 加）。
    #    此前只笼统说「发版时请在 git tag 之后再跑」—— 而 v1.7.0 那次 tag 顺序**是对的**，
    #    真因是 `Cargo.lock` 被构建改了却没进 commit（版本号写进它自己的 package 条目，
    #    而它只在**构建之后**才变）。一条指向错误原因的告警比没有告警更糟：
    #    它让人去检查一个本来就对的东西。所以这里必须说**是哪一项**、脏的是**哪些文件**。
    _ahead="$(git -C "$ROOT" rev-list --count "${TAG:-HEAD}"..HEAD 2>/dev/null || echo '?')"
    _dirty="$(git -C "$ROOT" status --porcelain 2>/dev/null)"
    echo "      · 距 tag 的 commit 数：${_ahead}"
    if [ -n "$_dirty" ]; then
        echo "      · 脏工作区（+1）——以下文件未提交："
        printf '%s\n' "$_dirty" | sed 's/^/          /'
        echo "        ↳ 常见元凶：\`Cargo.lock\`（版本号改完、**构建之后**才会变）。"
        echo "          把它并进 release commit 再 \`git tag -f\`，然后重跑本脚本。"
    else
        echo "      · 工作区干净 ⇒ B 全部来自 commit 数：在 \`git tag\` **之后**再跑本脚本（CLAUDE.md §3 4.5）。"
    fi
fi
