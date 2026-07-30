#!/usr/bin/env bash
export CODEX_HOME="${HOME}/.codex"

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

exec "${HOME}/.local/npm-global/bin/codex" "$@"
