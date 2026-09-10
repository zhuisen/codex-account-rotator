# shellcheck shell=bash
# 共享判据：这次调用该不该带 `--profile rotateproxy`。
#
# ★★ **两个入口共用同一份**（`proxy/cxp` 与 PATH wrapper `~/.local/bin/codex`）。
#    本仓铁律：同一条规则的两份实现在边界输入上必然分叉，而这条规则分叉的后果是
#    **静默退回单号直连、不轮换** —— 失败不出声，是最坏的那一类。
#
# ★★ `--profile` 只能给**运行时**子命令（2026-09-08 实测，codex 0.154.0-alpha.6）。
#    0.154 起 codex 对非运行时子命令直接硬报错、不再静默忽略：
#      Error: --profile only applies to runtime commands and `codex mcp`: `codex`, `codex exec`,
#      `codex review`, `codex resume`, `codex queue`, `codex archive`, `codex delete`,
#      `codex unarchive`, `codex fork`, `codex mcp`, `codex sandbox`, and `codex debug prompt-input`.
#    而 alias 曾给**每一个**子命令都塞 profile ⇒ 升级当天 `codex doctor` / `update` /
#    `plugin` / `features` / `completion` 全部一句话就死（用户报的「codex 的本地工具都用不了了」）。
#
# ⚠️ 用**黑名单**不是白名单：白名单会把 `codex 修一下这个 bug` 这种**裸 prompt**
#    （首个非选项 token 不匹配任何子命令）判成"未知"而丢掉 profile ⇒ 静默退回单号直连。
#    黑名单只认这几个确定不是运行时的名字，prompt 与未来新增的运行时子命令仍走代理。
#
# ⚠️ 别用 `codex <sub> --help` 去测这个：clap 在 `--help` 上短路，profile 校验根本没跑到，
#    26 个子命令会**全绿**、与事实相反。闸见 tests/test_cxp_profile_scope.py。
#
# 用法：`codex_wants_profile "$@"` —— 返回 0 = 该注入，1 = 不该。

codex_wants_profile() {
  local -a argv=("$@")
  local i=0

  # ★ 已经有 `--profile` 就不再注入。cxp 注入之后 `exec command codex` 会**再次**
  #   经过 PATH wrapper —— 不查这一条会变成 `--profile x --profile x`。
  local a
  for a in "${argv[@]}"; do
    case "$a" in
      -p|--profile|--profile=*) return 1 ;;
    esac
  done

  # 子命令前可以有全局选项；带值的那些要跳 2 个 token。
  while [ "$i" -lt "${#argv[@]}" ]; do
    case "${argv[$i]}" in
      -c|--config|--enable|--disable|--remote|--remote-auth-token-env|-i|--image|-m|--model|--local-provider|-p|--profile|-s|--sandbox|-C|--cd|--add-dir|-a|--ask-for-approval)
        i=$((i + 2)) ;;
      --*=*|-*)
        i=$((i + 1)) ;;
      *)
        break ;;
    esac
  done

  case "${argv[$i]:-}" in
    # `a` = `apply` 的别名；`e` 是 `exec` 的别名，属运行时，不在此列。
    agents|login|logout|plugin|app-server|remote-control|app|completion|update|doctor|apply|a|migrate-rollouts|cloud|exec-server|features|help)
      return 1 ;;                                   # 非运行时:不注入
    debug)
      # 整个 `debug` 里只有 `debug prompt-input` 被允许带 profile。
      [ "${argv[$((i + 1))]:-}" = "prompt-input" ] && return 0
      return 1 ;;
    sessions)
      return 1 ;;                                   # wrapper 自己的只读子命令,不转发给 codex
    *)
      return 0 ;;                                   # 运行时子命令、裸 prompt、裸 codex
  esac
}

# ── 解析出真正的子命令 ───────────────────────────────────────────────────────
#
# ★★ **守卫必须用这个，不能看 `$1`。** clap 允许全局选项放在子命令**前面**，
#    所以 `codex -C /tmp logout` / `codex -c k=v logout` / `codex -m x logout` 的
#    `$1` 都不是 `logout`。PATH wrapper 的 logout 拦截原来正是 `[ "$1" = "logout" ]` ——
#    一条 `codex -C /tmp logout` 就能绕过去，而 logout 会在**服务端 revoke 当值号**
#    （实测两次：2026-07-30 因此死了 plus3/plus4/plus7 三个号）。
#
# 输出解析到的子命令（没有则输出空串）。带值的全局选项跳 2 个 token —— 这份清单
# 与 `codex_wants_profile` 里那份**必须是同一份**，所以两者共用下面这个函数。
codex_subcommand() {
  local -a argv=("$@")
  local i=0
  while [ "$i" -lt "${#argv[@]}" ]; do
    case "${argv[$i]}" in
      -c|--config|--enable|--disable|--remote|--remote-auth-token-env|-i|--image|-m|--model|--local-provider|-p|--profile|-s|--sandbox|-C|--cd|--add-dir|-a|--ask-for-approval)
        i=$((i + 2)) ;;
      --*=*|-*)
        i=$((i + 1)) ;;
      *)
        printf '%s' "${argv[$i]}"; return 0 ;;
    esac
  done
  printf ''
}

# ★★ 会在**服务端**动凭证的子命令。两者都会让当值号的 token 失效：
#    `logout` 直接 revoke；`login` 覆盖 `~/.codex/auth.json`，把上一个号的最新 token 丢掉
#    （本仓的号只存在于那一份文件里）。加号/重登一律走 `codex-rotate login`。
codex_is_credential_command() {
  case "$(codex_subcommand "$@")" in
    logout|login) return 0 ;;
    *) return 1 ;;
  esac
}
