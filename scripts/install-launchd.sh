#!/usr/bin/env bash
# Generate + (re)load the five codex-rotate launchd agents.
#
# Generated rather than committed as files because every plist embeds absolute paths ($HOME, the repo
# location, the interpreter) — a committed copy would be wrong on any other machine and would drift
# silently on this one.
#
# ★ The interpreter is resolved and PINNED, never left to a shebang. launchd's default PATH is only
# /usr/bin:/bin:/usr/sbin:/sbin, so `#!/usr/bin/env python3` lands on macOS's /usr/bin/python3, which
# links LibreSSL 2.8.3 — and Cloudflare fingerprints that TLS ClientHello and answers 403 to
# GET /backend-api/codex/usage. Measured 2026-08-01, single variable, 3 trials each, identical token /
# headers / IP / minute:
#     /usr/bin/python3        LibreSSL 2.8.3   -> 403 403 403
#     /opt/homebrew/bin/py3   OpenSSL  3.6.3   -> 200 200 200
# Every agent was silently failing that way, so the pool's quota only ever came from stale rollout
# telemetry (observed: UI showed 100% for an account really at 16%).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# ★★★ **数据目录必须显式写进每一份 plist**（2026-09-10 四方评审抓到 critical）。
#
#    launchd 起的进程**不继承你的 shell 环境**,所以"用户 export 一下"在这里是无效的 ——
#    plist 里没写,子进程就只能按 `__file__` 去猜,猜出来的是**安装目录**。
#    从 `deploy.sh` 装的 macOS 机器上看不出问题:那条路径会把仓库路径烧进
#    `CODEXBAR_STORE_DEFAULT`,于是 app 的 `data_dir()` 恰好也等于仓库 —— 两边碰巧相同。
#    CI 出的安装包没有这个烧录值,app 落到 `app_data_dir()`,而 launchd 起的代理仍在
#    安装目录 ⇒ **route.local.json / state.json / auth/ 全部分叉**,
#    并且 `.refresh.lock` / `.state.lock` 落在两个不同路径上 = **等于没有锁**,
#    `codex-rotate` 与代理会同时刷同一个号的 refresh_token(一次性凭证)。
#
#    优先级与 Rust `store_dir()` **逐条对齐**(lib.rs:85)。顺序不一致就是换个地方分叉。
STORE="${CODEX_ROTATE_STORE:-${CODEXBAR_STORE:-$REPO}}"
# ★ app 通过 `spawn_cmd` 给每个子进程都设了 `CODEX_ROTATE_STORE`,所以由 app 调起本脚本时
#   上面第一条就命中;手动跑则退回仓库目录 —— 与改动前逐字相同。
if [ ! -d "$STORE" ]; then
    echo "⛔ 数据目录不存在:$STORE" >&2
    echo "   （从 app 里装会自动带上正确的目录;手动装请先建好,或 CODEX_ROTATE_STORE=<dir> 重跑）" >&2
    exit 78
fi
echo "==> 数据目录: $STORE"

AGENTS="$HOME/Library/LaunchAgents"
PREFIX="com.doushutangmu.codex-rotate"
UID_NUM="$(id -u)"

# --- resolve an interpreter with a modern TLS stack -------------------------------------------------
PY="${CODEX_ROTATE_PYTHON:-}"
if [ -z "$PY" ]; then
    for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
        [ -x "$cand" ] || continue
        if ! "$cand" -c 'import ssl,sys; sys.exit(0 if ssl.OPENSSL_VERSION.startswith("OpenSSL") else 1)' 2>/dev/null; then
            continue
        fi
        PY="$cand"; break
    done
fi
if [ -z "$PY" ]; then
    echo "✗ no python3 with an OpenSSL build found — LibreSSL gets 403 from the usage API." >&2
    echo "  install one (brew install python3) or set CODEX_ROTATE_PYTHON=/path/to/python3" >&2
    exit 1
fi
echo "==> interpreter: $PY  ($("$PY" -c 'import ssl;print(ssl.OPENSSL_VERSION)'))"

mkdir -p "$AGENTS"

# Log paths are NOT uniformly "$REPO/<name>.log": the proxy writes beside its own source, and CodexBar's
# log page reads these exact literals (src-tauri/src/lib.rs read_logs). Keep the two in sync.
log_path() {
    case "$1" in
        proxy) echo "$REPO/proxy/proxy.log" ;;
        *)     echo "$REPO/$1.log" ;;
    esac
}

# ★ 每个任务额外的环境变量(XML 片段)。`emit` 用完即清 —— 忘了清会把上一个任务的
#   变量带给下一个,而那种串味不会报错。
ENV_EXTRA=""

emit() {  # emit <name> <body-xml> <arg…>
    local name="$1" body="$2"; shift 2
    local out="$AGENTS/$PREFIX.$name.plist"
    local logf; logf="$(log_path "$name")"
    {
        echo '<?xml version="1.0" encoding="UTF-8"?>'
        echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        echo '<plist version="1.0"><dict>'
        echo "  <key>Label</key><string>$PREFIX.$name</string>"
        echo '  <key>ProgramArguments</key><array>'
        printf '    <string>%s</string>\n' "$PY" "$@"
        echo '  </array>'
        # ★★ **每个任务都带,一个不漏。** 以前只有 proxy 有 EnvironmentVariables,
        #    而 quotad / autosync / dawnprobe 同样会写 state.json 和 auth/ ——
        #    漏掉任何一个,它就在另一个目录上单干。
        echo '  <key>EnvironmentVariables</key><dict>'
        echo "    <key>CODEX_ROTATE_STORE</key><string>$STORE</string>"
        [ -n "$ENV_EXTRA" ] && echo "$ENV_EXTRA"
        echo '  </dict>'
        ENV_EXTRA=""
        echo "$body"
        echo "  <key>StandardOutPath</key><string>$logf</string>"
        echo "  <key>StandardErrorPath</key><string>$logf</string>"
        echo '</dict></plist>'
    } > "$out"
    plutil -lint "$out" >/dev/null

    # ★★ **`bootout` 是异步的** —— 它返回时任务往往还挂在 domain 里，紧跟的
    #    `bootstrap` 就撞上 `Bootstrap failed: 5: Input/output error`。
    #    2026-09-10 实测:quotad 这样失败，而 `set -e` 让脚本**停在那一行** ——
    #    该任务已经 bootout、还没 bootstrap 回来，于是**服务就那么停着**，
    #    后面的 proxy / dawnprobe 连 plist 都没重写。
    #    「装了一半」和「装好了」在终端上只差最后几行输出，而守护进程是真的没了。
    launchctl bootout "gui/$UID_NUM/$PREFIX.$name" 2>/dev/null || true
    local i=0
    while [ "$i" -lt 50 ] && launchctl print "gui/$UID_NUM/$PREFIX.$name" >/dev/null 2>&1; do
        sleep 0.1; i=$((i + 1))
    done
    local tries=0 rc=1
    while [ "$tries" -lt 5 ]; do
        if launchctl bootstrap "gui/$UID_NUM" "$out" 2>/dev/null; then rc=0; break; fi
        tries=$((tries + 1)); sleep 0.3
    done
    # ★ 判据是**真的加载上了**，不是 bootstrap 的退出码 —— 后者在这条路径上不可靠。
    if ! launchctl print "gui/$UID_NUM/$PREFIX.$name" >/dev/null 2>&1; then
        echo "  ⛔ $name 装不上（bootstrap rc=$rc，重试 $tries 次后仍未加载）" >&2
        echo "     手动:launchctl bootstrap gui/$UID_NUM $out" >&2
        return 1
    fi
    echo "  ✓ $name$([ "$tries" -gt 0 ] && echo "（重试 $tries 次）")"
}

ROT="$REPO/codex-rotate"

emit autosync \
    "  <key>RunAtLoad</key><true/>
  <key>WatchPaths</key><array><string>$HOME/.codex/auth.json</string></array>" \
    "$ROT" sync

# ★★ keepalive(04:30) 与 refreshquota(07:00) 已于 2026-08-29 按用户要求**取消**，不再生成。
#    · refreshquota 是真冗余 —— quotad 每 300s 已经全池扫一遍（`tick_usage` → `refresh-all`）。
#    · keepalive 的职责由 proxy 接手：`_slot_token` 挑到 token 过期的**非活跃**号时会当场
#      OAuth 续期（双重锁保护）。
#    ⚠️ **但覆盖面不同**：proxy 只续它**挑得中**的号。一个长期不被挑中的号，token 到期后
#      **不会自愈** —— 2026-08-29 的 plus5 就是这样断的（11 天没续、access 过期 18.5h、
#      额度扫描每 300s 静默失败）。补救是手动 `codex-rotate refresh <label>`（非活跃号安全）。
#    ★ CLI 的 `keepalive` / `refresh-all` 子命令**都还在**，随时可手动跑；取消的只是定时器。

emit quotad \
    '  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>' \
    "$REPO/daemon/quota_daemon.py"

# ★ `CRP_PORT` 现在走 `ENV_EXTRA` —— `emit` 统一生成唯一的一个 EnvironmentVariables 字典。
#   在 body 里再写一个同名 key 会得到重复键的 plist,`plutil -lint` 未必拦得住。
ENV_EXTRA='    <key>CRP_PORT</key><string>8011</string>'
emit proxy \
    '  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>' \
    "$REPO/proxy/proxy.py"

# ★★ 每日清晨探针(06:00)。给 **Plus 号**各发一次最小计费补全,把 5h 窗口**锚定**上 ——
#    没被用过的 5h 窗口服务端每轮都回「此刻 + 整窗」,倒计时永远停在 ~4h55m,那 5 小时等于没在走。
#
#    ⚠️ **这是本仓唯一一个会自动花钱的定时器**,所以命令侧有三条护栏(见 `cmd_dawn_probe`):
#      ① `enabled` 默认**假** —— 装了这个 plist 也不会自己跑,要 `dawn-probe --enable`;
#      ② **当天幂等** —— app 内还有一条补跑路径,两条都调它,没有幂等就是双重计费;
#      ③ 每次运行落痕到 `state.json` 的 `dawn_probe`,UI 读它。
#
#    ★★ **为什么还要 app 内补跑**:本项目的日历定时有前科 —— keepalive/refreshquota 的
#      `StartCalendarInterval` 曾被本脚本以外的东西改写掉,`runs = 0`、**从未运行过**,
#      而没有任何一处会为此报红(改写者至今未查明)。所以这个 plist**不能是唯一的触发路径**。
#      发现定时不跑时先比对 plist 形态(单行 vs 逐行美化 + 空 EnvironmentVariables),别先怀疑脚本。
emit dawnprobe \
    '  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>' \
    "$ROT" dawn-probe

echo
echo "==> loaded:"
for n in autosync quotad proxy dawnprobe; do
    printf '  %-13s %s\n' "$n" \
        "$(launchctl print "gui/$UID_NUM/$PREFIX.$n" 2>/dev/null | awk '/^\tstate = /{print $3; exit}' || echo '?')"
done
