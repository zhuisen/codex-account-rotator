# codex-rotate

把 **多个个人 ChatGPT Plus/Pro 账号** 做成一个池子,为 **Codex CLI** 透明轮换使用——一个人、自己买的号、全程本机、loopback-only、同一家庭 IP。

> 日常:用 **`cxp`** 代替 `codex`,你的 Codex 会话就会在多个号之间**逐请求透明轮换**:撞限自动换号、token 自动刷新、长会话消耗摊到所有号 ≈ **把额度上限扩成 N 倍**。菜单栏实时看每号余量。

> 🆕 **新电脑从零搭建** → [**SETUP.md**](SETUP.md)(凭证不搬运,新机 `codex login` 重新生成)。日常用法 / 排障 / 不变量 → [RUNBOOK.md](RUNBOOK.md)。

## 它解决的 4 个痛点

| 痛点 | 怎么解的 |
|---|---|
| ① token 失效要重登 | keepalive 定期 OAuth 刷新闲置号 + 代理发现过期当场刷新 → **永不手动重登** |
| ② 会话内切号要重启 | 代理逐请求透明轮换;Codex 每请求发完整上下文(无 `previous_response_id`)→ **中途换号无感、不重启** |
| ③ 额度不实时 | **官方 usage API**(`GET /backend-api/codex/usage`,零消耗)每 3 分钟刷全池 + 代理逐请求读 `x-codex-*` 响应头精确记账 |
| ④ 撞限要手动换 | 代理撞 429 → 标冷却 → 下个请求自动换号 |

## 架构:两层协作

```
                    ┌─ 账号池层 (auth.json swap) ────────────────────┐
  codex login 新号 ─┤  codex-rotate(CLI)  +  autosync(watcher)     │
                    │  keepalive(launchd 04:30,OAuth 保活闲置号)    │
                    │  槽位 auth/<account_id>.json(以 OAuth id 主键) │
                    └────────────────────────────────────────────────┘
                                   │ 复用同一个池
                    ┌─ 轮换代理层 (daily) ───────────────────────────┐
   cxp ──→ codex ──→│  proxy.py (127.0.0.1:8011, launchd 常驻)       │──→ chatgpt.com
   (--profile        │   选号(用量最少+跳冷却) → 过期自动 OAuth 刷新   │    /backend-api/codex
    rotateproxy)     │   → 注入 token+account_id → 429 冷却 → 逐请求记账 │
                    └────────────────────────────────────────────────┘
                    ┌─ 展示层 ───────────────────────────────────────┐
                    │  CodexBar(Tauri app):菜单栏弹窗 + 主窗口仪表盘  │
                    │  每号油表 + 推荐切号 + 开机自启(SwiftBar 已退役) │
                    └────────────────────────────────────────────────┘
```

- **plain `codex`** = 单号(走 `~/.codex/auth.json` 的当前号),完全不受影响。
- **`cxp`** = 多号透明轮换(经代理)。两种模式自动区分(`last_proxy_ts`),互不串号。

## 文件骨架

| 路径 | 作用 |
|---|---|
| `codex-rotate` | **CLI**:账号池管理(add/list/switch/refresh/keepalive/quota/sync/…) |
| `cx` | 交互式轮换辅助(`cx next` 撞墙切号+重开),单号模式用 |
| `codexbar/` | **CodexBar 桌面应用**(Tauri 2 + React):菜单栏弹窗 + 主窗口仪表盘 + 开机自启;`bash codexbar/scripts/deploy.sh` 构建部署到 `/Applications` |
| `swiftbar/codex-status.10s.py` | ~~SwiftBar 菜单栏插件~~(**已退役**,由 CodexBar 取代;脚本保留仅供参考) |
| `proxy/proxy.py` | **轮换代理本体**(stdlib,复用 `state.json` + `auth/`) |
| `proxy/cxp` | **日常入口**:`codex --profile rotateproxy`,经代理透明轮换 |
| `proxy/auth-token` | codex `auth.command` 占位 token(代理会覆盖) |
| `proxy/test-home/config.toml` | 隔离测试用 CODEX_HOME(非日常) |
| `proxy/README.md` | 代理层细节文档 |
| `launchd/*.plist` | 3 个常驻服务(装到 `~/Library/LaunchAgents/`) |
| `auth/`(gitignored) | 每号凭证槽位 `<account_id>.json`(0600) |
| `state.json`(gitignored) | 池状态(slots/active/last_aid/last_proxy_ts) |
| `RUNBOOK.md` | 运维手册(起停/排障/常见操作/踩坑) |
| `CHANGELOG.md` | 版本史 + bug 日志 |

外部依赖:`~/.codex/config.toml` 里有一个 dormant 的 `[model_providers.rotateproxy]` 块;`~/.codex/rotateproxy.config.toml` 是 cxp 的 profile overlay。详见 RUNBOOK。

> ⛔ **加号/重登只用 `codex-rotate login`,别直接跑 `codex login` 或 `codex logout`。**
>
> **实测机制(2026-07-30,两次事故 4 个号)**:`codex login` 会把**运行那一刻 `~/.codex/auth.json` 里的号**在服务端 revoke(它自带隐式 logout;`codex logout` 是显式做同一件事)。所以连登三个号只会剩最后一个:
> ```
> 15:56:24 登 plus4  →  (作废当时的活跃号)
> 15:56:57 登 plus3  →  plus4 被作废   ← 登录前 auth.json 里是 plus4
> 15:58:09 登 plus7  →  plus3 被作废   ← 登录前 auth.json 里是 plus3
> plus6 全程没被设为活跃            → 幸存
> ```
> 看起来像「这台机器只能登 2 个 Codex」——**不是限制,是登录流程本身**。
>
> 先把 token 存起来**没用**:服务端那份也被作废了。唯一无损的办法是**让被作废的那个 token 本来就该作废**。`codex-rotate login` 就是这么做的——登录前先把「牺牲号」放进 auth.json:① 你指定要重登的号(`codex-rotate login plus3`,它的旧 token 反正要换);② 任意已失效的号(token 早就没用);③ 都没有就拒绝执行,并告诉你会毁掉哪个活号。
>
> `~/.local/bin/codex` 包装脚本另外拦截了 `codex logout`(含 `\codex logout`——反斜杠只绕 alias 不绕 PATH),需 `--force` 才放行。

## Quickstart

```bash
# 1) 加号 / 重登死号:★必须用 codex-rotate login,不要自己跑 codex logout
codex-rotate login [label]           # 先放好牺牲号再登,零连坐;重登某号就带上它的 label

# 2) 日常用 cxp(多号透明轮换)
cxp                                  # 交互
cxp exec "修个 bug"                  # 非交互
codex                                # 想用单号:照旧,不受影响

# 3) 看池子 / 手动操作
codex-rotate list                    # 每号谁在用/冷却 + 周/月用量
codex-rotate switch plus2            # 手动切号(单号模式)
codex-rotate refresh all             # 手动 OAuth 刷新非活跃号
```

菜单栏(CodexBar)装好后顶部显示当前号周额度余量 + 重置倒计时,点击弹窗看每号油表、推荐切号、失效号折叠;主窗口(设置页)可开「开机自启」。构建:`bash codexbar/scripts/deploy.sh`。

## 安全边界(红线)

全 **loopback(127.0.0.1)**、**单人**、**只轮你自己的号**、保活**串行不并发**、**不对外共享 Base URL**。守住这些,风险与你手动切号同级。⚠️ 用订阅 auth 做池化自动化偏离 OpenAI 官方推荐(官方推 API key),个人自用属灰区。

## 维护约定

- **改插件必 bump `swiftbar/codex-status.10s.py` 的 `VERSION`**——菜单栏显示它,用户靠它判断更新生效没。
- 改 `state.json` schema 或凭证逻辑要谨慎:proxy / codex-rotate / autosync / keepalive 都读写它。
