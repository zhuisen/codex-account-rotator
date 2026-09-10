#!/usr/bin/env bash
export CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"

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

# ★★ `repair_codex_session_visibility()` 已删除（2026-09-08）。
#
# 它在每次 `codex resume/fork` 前跑一段 SQL，把 `state_5.sqlite` 里 `model_provider` 为
# `rotateproxy` 的行改写成 `openai` 并置 `has_user_event=1`，本意是让被代理戳记的会话
# 在 picker 里可见。它现在必须走，有三条独立理由：
#
# ① **它制造的正是它要修的问题。** `cxp` 自 `aa1efb7` 起让所有子命令都走 `--profile rotateproxy`，
#    于是 picker 请求的是 rotateproxy，而这段 SQL 把 DB 改成 openai —— 两边永远对不上。
#    更糟的是**入口顺序决定副作用**：裸 `command codex resume` 会触发它，
#    而 cxp 因为把 `--profile` 放在第一位反而跳过（守卫只看 `$1`）。同一台机器两种行为。
# ② **DB 与 rollout 文件头从此不一致。** 文件里 session_meta 仍写着原 provider，
#    活跃会话被 CLI 自然回写时又把 DB 改回去 —— 列表因此会自己翻转。
# ③ ★ **未加引号的 `<<SQL` 让注释里的反引号被 bash 执行。** 2026-09-08 实测 stderr 出现
#    `history.jsonl: command not found` / `reusme: command not found` / `cli/vscode: command not found`
#    —— 那些字都在我写的 SQL 注释里。`bash -n` 对此**完全沉默**。
#
# 根治（迁移历史 provider）涉及 192 个 rollout 文件各 +5 字节，会让
# `thread_history_1.sqlite` 的 `rollout_byte_offset` 全部失效，是一次需要备份与回滚的
# 数据迁移，不属于这个 wrapper 的职责。详见交接包
# `output/codex-resume-handoff-20260908/CLAUDE_HANDOFF.md`。
#
# 现状与绕法：`codex resume` 按**当前 provider** 过滤，所以 cxp 只列 rotateproxy 戳记的会话；
# 旧的 openai 会话仍可用 `codex resume <session-id>` 直接进入，或用裸
# `command codex resume`（不经 cxp，provider=openai）浏览。


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

# ★ 这里原本有一个 `case "$1" in resume|fork)` 分支去跑上面那个已删的 repair。
#   连同删掉 —— 留一个只打警告的空分支比没有更糟：它会让人以为还有东西在守着。

# ── 走轮换代理 ────────────────────────────────────────────────────────────────
#
# ★★ 2026-09-09 用户定稿：`omc ask codex` / VS Code / `\codex` **一并跟随路由**。
#    在这之前它们调的是裸 `codex` ⇒ 落到内置 provider `openai` ⇒ **单号直连**，
#    烧 `auth.json` 里的当值号，而 CodexBar 上的「账号池 ↔ 中转站」开关管不到它们。
#
#    能这么做的前提是「一个 provider，两种上游」：中转站不再有自己的 profile，
#    账号池 ↔ 中转站的切换发生在代理内部，所以这里只需恒定注入 `rotateproxy`。
#
# ★ 需要**真正直连某一个号**（例如跑 `/usage` 看重置卡）请用 `cxd` ——
#   它直接调真二进制、绕过本 wrapper。
#
# ★★ 判据与 `proxy/cxp` **共用同一份**（`proxy/codex-profile-scope.sh`）。
#    同一条规则的两份实现必然在边界输入上分叉，而这条分叉的后果是
#    **静默退回单号直连、不轮换** —— 失败不出声，最坏的那一类。
CODEX_ROTATE_STORE="${CODEX_ROTATE_STORE:-${HOME}/Projects/tools/codex-account-rotator}"
export CODEX_ROTATE_STORE
_scope="${CODEX_ROTATE_STORE}/proxy/codex-profile-scope.sh"
_profile=()
if [ -f "$_scope" ]; then
  # shellcheck source=/dev/null
  . "$_scope"
  if codex_wants_profile "$@"; then
    # ★★ 保留这道硬闸:codex 对「`--profile X` 但 `X.config.toml` 不存在」**不报错**,
    #    直接静默退回 base 配置(直连单号、不轮换、WS 全开)—— 和正常运行长得一模一样。
    if [ ! -f "${CODEX_HOME}/rotateproxy.config.toml" ]; then
      printf '%s\n' \
        "⛔ codex: profile 文件不存在 —— ${CODEX_HOME}/rotateproxy.config.toml" \
        "   codex 对这种情况**不报错**,会静默退回 base 配置(直连单号、不轮换、WS 全开)," \
        "   所以这里替它硬失败。" \
        "   要单号直连请用 \`cxd\`。" >&2
      exit 78
    fi
    _profile=(--profile rotateproxy)
  fi
else
  # ⚠️ **不许静默跳过。** 判据文件不在 = 安装坏了;悄悄不注入等于把
  #    「装坏了」伪装成「你选了单号直连」,而那正是这一整套要防的事。
  printf '%s\n' \
    "⛔ codex: 找不到 profile 判据 —— $_scope" \
    "   没有它就无法决定该不该走轮换代理,而猜错的那一边(不注入)是**静默**失败。" \
    "   修:确认 CODEX_ROTATE_STORE 指向仓库根,或重装 wrapper。" \
    "   要单号直连请用 \`cxd\`。" >&2
  exit 78
fi

exec "${CODEX_NATIVE_BIN:-${HOME}/.local/npm-global/bin/codex}" "${_profile[@]}" "$@"
