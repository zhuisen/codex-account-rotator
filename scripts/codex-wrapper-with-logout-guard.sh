#!/usr/bin/env bash
export CODEX_HOME="${HOME}/.codex"

# The npm install used on this machine cannot run `codex agents` because that command requires the
# standalone app-server package. Keep session discovery local and read-only instead.
list_codex_sessions() {
  local db="${CODEX_HOME}/state_5.sqlite"

  if [ ! -f "$db" ]; then
    printf 'Codex session database not found: %s\n' "$db" >&2
    return 1
  fi

  /usr/bin/sqlite3 -header -column "$db" <<'SQL'
SELECT
  name AS session_name,
  id AS session_id,
  strftime('%Y-%m-%d %H:%M', updated_at, 'unixepoch', 'localtime') AS updated_local
FROM threads
WHERE archived = 0
  AND name IS NOT NULL
  AND trim(name) <> ''
  AND (thread_source = 'user' OR thread_source IS NULL)
  AND source IN ('cli', 'vscode', 'exec')
ORDER BY updated_at DESC
LIMIT 100;
SQL
}

if [ "${1:-}" = "sessions" ]; then
  list_codex_sessions
  exit $?
fi

# Native resume/fork pickers are explicit user choices and must remain available. Only --last skips
# that choice and can silently append a new task to whichever thread happens to be newest.
guard_automatic_session_resume() {
  local -a args=("$@")
  local command=""
  local arg
  local index=0
  local has_last=0

  # Global Codex options may precede the subcommand. Skip the options supported by 0.150.1 so
  # `codex -C <dir> resume` cannot bypass the same isolation rule as `codex resume`.
  while [ "$index" -lt "${#args[@]}" ]; do
    arg="${args[$index]}"
    case "$arg" in
      -c|--config|--enable|--disable|--remote|--remote-auth-token-env|-i|--image|-m|--model|--local-provider|-p|--profile|-s|--sandbox|-C|--cd|--add-dir|-a|--ask-for-approval)
        index=$((index + 2))
        ;;
      --*=*|-*)
        index=$((index + 1))
        ;;
      *)
        command="$arg"
        break
        ;;
    esac
  done

  case "$command" in
    resume|fork)
      index=$((index + 1))
      while [ "$index" -lt "${#args[@]}" ]; do
        case "${args[$index]}" in
          -h|--help) return 0 ;;
          --last) has_last=1 ;;
        esac
        index=$((index + 1))
      done
      [ "$has_last" -eq 1 ] || return 0
      cat >&2 <<'WARN'
⛔ 已拦截自动恢复最近一条 Codex 会话

`--last` 会跳过选择器，容易把新任务续进最近的旧 thread。
原生 picker、session name 和 session ID 均可正常使用。

新任务：直接运行 codex，进入后用 /new <task-name>
选择当前目录会话：codex resume
选择全部会话：codex resume --all
指定会话：codex resume <session_id|session_name>
WARN
      return 64
      ;;
  esac
}

guard_automatic_session_resume "$@" || exit $?

# Native resume/fork filters by thread metadata. Codex can leave genuine interactive sessions with
# has_user_event=0, and cxp sessions are stamped rotateproxy even though this machine intentionally
# resumes them through plain Codex. Repair only sessions recorded in history.jsonl that already have
# native first-user-message metadata. One-shot exec, automation, aborted/empty, archived, and subagent
# threads are excluded by the SQL predicate.
repair_codex_session_visibility() (
  local db="${CODEX_HOME}/state_5.sqlite"
  local history="${CODEX_HOME}/history.jsonl"
  local jq_bin="/opt/homebrew/bin/jq"
  local ids_file=""
  local repair_status

  cleanup_ids_file() {
    if [ -n "$ids_file" ] && [ -e "$ids_file" ]; then
      /bin/unlink "$ids_file"
    fi
  }
  trap cleanup_ids_file EXIT

  [ -f "$db" ] && [ -s "$history" ] && [ -x "$jq_bin" ] || return 0

  ids_file="$(/usr/bin/mktemp "${TMPDIR:-/tmp}/codex-human-sessions.XXXXXX")" || return 1
  if ! "$jq_bin" -Rrs '
      [split("\n")[]
        | fromjson?
        | .session_id? // empty
        | select(test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"))]
      | unique[]
    ' "$history" > "$ids_file"; then
    return 1
  fi

  if [ ! -s "$ids_file" ]; then
    return 0
  fi

  /usr/bin/sqlite3 -batch "$db" >/dev/null <<SQL
.bail on
PRAGMA busy_timeout=5000;
CREATE TEMP TABLE history_ids (id TEXT PRIMARY KEY);
.mode tabs
.import $ids_file history_ids
BEGIN IMMEDIATE;
UPDATE threads
SET has_user_event = 1,
    model_provider = CASE
      WHEN model_provider = 'rotateproxy' THEN 'openai'
      ELSE model_provider
    END
WHERE archived = 0
  AND (thread_source = 'user' OR thread_source IS NULL)
  AND source IN ('cli', 'vscode', 'exec')
  AND first_user_message <> ''
  AND EXISTS (SELECT 1 FROM history_ids WHERE history_ids.id = threads.id)
  AND (has_user_event = 0 OR model_provider = 'rotateproxy');
COMMIT;
SQL
  repair_status=$?
  return "$repair_status"
)

# ── guard: `codex logout` REVOKES the active account's tokens server-side ──────────────────────────
# The codex binary logs "failed to revoke auth tokens during logout", i.e. logout is a server-side
# revocation, not a local sign-out. With codex-account-rotator the ACTIVE account's freshest tokens
# live only in ~/.codex/auth.json, so `codex logout && codex login` permanently kills whichever
# account was active — you gain the one you log in and lose the one you had. Measured twice
# (2026-07-30): plus4 died at 14:16 after a logout+login for plus7; plus3 and plus7 died at 15:26/15:27
# after logging in plus4. It looks like "this machine only allows 2 Codex logins"; it is self-inflicted.
#
# This guard lives in the PATH wrapper on purpose: a shell alias would be bypassed by `\codex logout`,
# which is exactly how it keeps getting typed. Use `codex-rotate login` to add / re-login an account.
if [ "$1" = "logout" ]; then
  case " $* " in
    *" --force "*|*" --yes "*) ;;   # explicit escape hatch
    *)
      cat >&2 <<'WARN'
⛔ 已拦截 `codex logout`

logout 会把【当前活跃号】的 token 在 OpenAI 服务端 revoke（不是本地登出），
该号立即永久失效、只能重新登录。这就是「每加一个号就死一个号」的原因。

要加号 / 重登，请改用：

    codex-rotate login

它会先把当前号存回槽位，再走 codex login，全程不调 logout。

真的要 revoke 当前号（几乎不需要）：codex logout --force
WARN
      exit 1
      ;;
  esac
fi

case "$1" in
  resume|fork)
    if ! repair_codex_session_visibility; then
      printf '%s\n' 'Warning: Codex session visibility repair failed; continuing with native resume.' >&2
    fi
    ;;
esac

exec "${HOME}/.local/npm-global/bin/codex" "$@"
