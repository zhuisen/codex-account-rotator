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
        echo "$body"
        echo "  <key>StandardOutPath</key><string>$logf</string>"
        echo "  <key>StandardErrorPath</key><string>$logf</string>"
        echo '</dict></plist>'
    } > "$out"
    plutil -lint "$out" >/dev/null
    launchctl bootout "gui/$UID_NUM/$PREFIX.$name" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_NUM" "$out"
    echo "  ✓ $name"
}

ROT="$REPO/codex-rotate"

emit autosync \
    "  <key>RunAtLoad</key><true/>
  <key>WatchPaths</key><array><string>$HOME/.codex/auth.json</string></array>" \
    "$ROT" sync

emit keepalive \
    '  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>30</integer></dict>' \
    "$ROT" keepalive

emit refreshquota \
    '  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>' \
    "$ROT" refresh-all

emit quotad \
    '  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>' \
    "$REPO/daemon/quota_daemon.py"

emit proxy \
    '  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key><dict><key>CRP_PORT</key><string>8011</string></dict>' \
    "$REPO/proxy/proxy.py"

echo
echo "==> loaded:"
for n in autosync keepalive refreshquota quotad proxy; do
    printf '  %-13s %s\n' "$n" \
        "$(launchctl print "gui/$UID_NUM/$PREFIX.$n" 2>/dev/null | awk '/^\tstate = /{print $3; exit}' || echo '?')"
done
