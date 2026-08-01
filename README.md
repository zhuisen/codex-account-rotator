# codex-rotate

把 **多个个人 ChatGPT Plus/Pro 账号** 做成一个池子,为 **Codex CLI** 透明轮换使用——一个人、自己买的号、全程本机、loopback-only、同一家庭 IP。

> 日常:用 **`cxp`** 代替 `codex`,你的 Codex 会话就会在多个号之间**逐请求透明轮换**:撞限自动换号、token 自动刷新、长会话消耗摊到所有号 ≈ **把额度上限扩成 N 倍**。菜单栏实时看每号余量。

> 🆕 **新电脑从零搭建** → [**SETUP.md**](SETUP.md)(凭证不搬运,新机 `codex login` 重新生成)。日常用法 / 排障 / 不变量 → [RUNBOOK.md](RUNBOOK.md)。

## 它解决的 4 个痛点

| 痛点 | 怎么解的 |
|---|---|
| ① token 失效要重登 | keepalive 定期 OAuth 刷新闲置号 + 代理发现过期当场刷新 → **永不手动重登** |
| ② 会话内切号要重启 | 代理逐请求透明轮换;Codex 每请求发完整上下文(无 `previous_response_id`)→ **中途换号无感、不重启** |
| ③ 额度不实时 | **事件驱动**:quotad 监测 codex 活动(4 路本地信号)→ 数秒内读**官方 usage API**(零消耗)刷当前号;实测发起调用后 **+8s** 见数、运行中每 20s 续刷。另有 300s 全池扫描兜底 + 代理逐请求记账 |
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
| `scripts/install-launchd.sh` | **生成并加载 5 个 launchd 服务**(autosync/keepalive/refreshquota/quotad/proxy)。生成而非提交成文件:plist 内嵌绝对路径,提交的副本换台机器就是错的,且会静默漂移(旧的 `launchd/*.plist` 就漂到了写死 `/usr/bin/python3`)。★脚本会**解析并钉住 OpenSSL 版的 python3**,见「维护约定」 |
| `auth/`(gitignored) | 每号凭证槽位 `<account_id>.json`(0600) |
| `state.json`(gitignored) | 池状态(slots/active/last_aid/last_proxy_ts) |
| `RUNBOOK.md` | 运维手册(起停/排障/常见操作/踩坑) |
| `CHANGELOG.md` | 版本史 + bug 日志 |

外部依赖:`~/.codex/config.toml` 里有一个 dormant 的 `[model_providers.rotateproxy]` 块;`~/.codex/rotateproxy.config.toml` 是 cxp 的 profile overlay。详见 RUNBOOK。

> ⛔ **加号/重登只用 `codex-rotate login`,别直接跑 `codex login` 或 `codex logout`。**
>
> **已观测(2026-07-30,两轮)**:连着登几个号,最后只剩最后登的那个;死掉的恰好是「下一次 login 运行时正躺在 `~/.codex/auth.json` 里」的那些。已确证被作废:plus4、plus3(`/models` 返回 401)。plus6 两轮都没被设为活跃 → 存活。
> ```
> 15:56:24 登 plus4  →  (之前的活跃号被作废)
> 15:56:57 登 plus3  →  plus4 被作废   ← 当时 auth.json 里是 plus4
> 15:58:09 登 plus7  →  plus3 被作废   ← 当时 auth.json 里是 plus3
> ```
> **受控实验已确证(2026-07-30 第三轮)**。单一变量对照,三轮只改一处:
> ```
> 第1轮  codex logout && codex login   登录前的活跃号 → 死    存活 2
> 第2轮  旧版 login(仅 syncback)        登录前的活跃号 → 死    存活 2
> 第3轮  新版 login(移开 auth.json)     登录前的活跃号 → 活 ✅  存活 3  ← 首次突破 2
> ```
> 结论:**假说①成立**——本机没有 token 时,登录不会作废任何号;前两轮必死的那个位置这次活了下来。同时**假说②被证伪**:plus7 是本设备「上一次签发」的授权,若服务端按设备撤销上一次,它应当死亡,但它存活。(假说③浏览器登出未被完全排除——若你用无痕窗口登录,它与①的预测一致。)
>
> 所以 `codex-rotate login` 的做法是:先 syncback(把活跃号最新 token 存回自己槽位),再把 `auth.json` **整个移开**,在「本机没有任何 token」的状态下跑 `codex login`,登完自动收编;失败或 Ctrl-C 会把移开的文件放回去。**永远不需要牺牲健康号**,加全新号也不会被拒。

## Quickstart

```bash
# 1) 加号 / 重登死号:★必须用 codex-rotate login,不要自己跑 codex logout
codex-rotate login                   # 移开 auth.json 再登,失败自动还原;加号/重登都用它

# 2) 日常用 cxp(多号透明轮换)
cxp                                  # 交互
cxp exec "修个 bug"                  # 非交互
codex                                # 想用单号:照旧,不受影响

# 3) 看池子 / 手动操作
codex-rotate list                    # 每号谁在用/冷却 + 周/月用量
codex-rotate switch plus2            # 手动切号(单号模式)
codex-rotate refresh all             # 手动 OAuth 刷新非活跃号
```

菜单栏(CodexBar)装好后顶部显示当前号周额度余量 + 重置倒计时。**左键右键都打开弹窗**(托盘没有原生菜单——macOS 无法让右键不弹它);弹窗里看每号油表、号间差值、重置卡状态、失效号折叠,**点任意账号会弹出主界面**,切号在主界面卡片上做。退出在主界面「设置」页(本 app 不占 Dock,没有别的退出口)。构建:`bash codexbar/scripts/deploy.sh`。

## 安全边界(红线)

全 **loopback(127.0.0.1)**、**单人**、**只轮你自己的号**、保活**串行不并发**、**不对外共享 Base URL**。守住这些,风险与你手动切号同级。⚠️ 用订阅 auth 做池化自动化偏离 OpenAI 官方推荐(官方推 API key),个人自用属灰区。

## 维护约定

- ★ **绝不让 python 解释器由 PATH 或 shebang 决定**。Cloudflare 按 TLS ClientHello 指纹拦截,macOS 的 `/usr/bin/python3`(LibreSSL 2.8.3)对 `GET /backend-api/codex/usage` 恒返 **403**,OpenSSL 3.x 同请求恒 **200**(2026-08-01 受控实验,单一变量,各 3 次,同 token/header/IP)。launchd 默认 PATH 只有 `/usr/bin:/bin:...`,所以 `#!/usr/bin/env python3` 必踩。装服务一律走 `scripts/install-launchd.sh`;CodexBar 侧见 `python_bin()`。
  - 排查提示:用 macOS 自带 `curl` 复现"也被挡"**不算独立证据**——它同样链 LibreSSL,是同一个失败模式。换 TLS 栈才是对照组。
- 改 `launchd` 的日志路径要同步 `codexbar/src-tauri/src/lib.rs` 的 `read_logs`(路径是写死的字面量,`proxy` 那条是 `proxy/proxy.log` 不是 `proxy.log`)。
- 改 `state.json` schema 或凭证逻辑要谨慎:proxy / codex-rotate / autosync / keepalive 都读写它。
