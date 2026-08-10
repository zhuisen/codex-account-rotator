# codex-rotate

把 **多个个人 ChatGPT Plus/Pro 账号** 做成一个池子,为 **Codex CLI** 透明轮换使用——一个人、自己买的号、全程本机、loopback-only、同一家庭 IP。

> 日常:用 **`cxp`** 代替 `codex`,你的 Codex 会话就会在多个号之间**逐请求透明轮换**:撞限自动换号、token 自动刷新、长会话消耗摊到所有号 ≈ **把额度上限扩成 N 倍**。菜单栏实时看每号余量。

> 🆕 **新电脑从零搭建** → [**SETUP.md**](SETUP.md)(凭证不搬运,新机 `codex login` 重新生成)。日常用法 / 排障 / 不变量 → [RUNBOOK.md](RUNBOOK.md)。

## 先看这个:这套东西是两半

| | 【A】AI 用量信息 | 【B】账号池 + 轮换代理 |
|---|---|---|
| 干什么 | 汇总本机各 AI CLI **已经落盘**的 token 消耗 | 多个 ChatGPT 订阅做成池子,给 Codex CLI 逐请求透明轮换 |
| 要凭证吗 | **不要**。只读本机文件、不联网、不碰 token | 要,每号 OAuth |
| 谁能用 | **任何 macOS 用户**,装了下面四家 CLI 中任意一家就有数据 | 需要自备多个 ChatGPT Plus/Pro |
| 风险 | 无 | ⚠️ 自负,多账号轮换受 OpenAI 条款约束(本仓库 CHANGELOG 的 B7/B8/B14/B21 记过实测掉号) |

**只想看自己电脑烧了多少 token,只装 A 就行**,三步:

```bash
brew install python3 node && curl https://sh.rustup.rs -sSf | sh   # 前置(python3 必须 OpenSSL 构建)
git clone https://github.com/zhuisen/codex-account-rotator.git && cd codex-account-rotator
bash codexbar/scripts/setup-signing.sh && bash codexbar/scripts/deploy.sh
```

clone 到哪个目录都行 —— `deploy.sh` 会把仓库路径烧进二进制。完整说明见 [SETUP.md §6](SETUP.md)。

覆盖的 CLI:**Claude Code · Codex · Grok · Kimi**(Antigravity/agy **不支持**,它把会话存成 protobuf blob,本地没有可读用量)。加一家 = 在 `traffic/scan.py` 写个解析器 + 注册表加一行,前端自动跟上。

---

## 它解决的 4 个痛点

| 痛点 | 怎么解的 |
|---|---|
| ① token 失效要重登 | keepalive 定期 OAuth 刷新闲置号 + 代理发现过期当场刷新 → **永不手动重登** |
| ② 会话内切号要重启 | 代理逐请求透明轮换;Codex 每请求发完整上下文 → **中途换号无感、不重启**。同一段对话靠 body 里的 `prompt_cache_key` 粘住同一个号(codex 不发 `previous_response_id`,见 CHANGELOG B26) |
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
| `.traffic-cache.json`(gitignored) | `traffic/scan.py` 的**逐文件增量缓存**(~10MB,按 `(mtime,size)` 命中)。冷 ~18s → 热 ~1.4s 靠它。删了只是重扫一次,不丢数据 |
| `.traffic-latest.json`(gitignored) | 最近一次扫描的**成品快照**(~91KB)。两个 webview 都先读它再后台重扫,所以进页面/点托盘不再等 1~3 秒。由 `run_traffic` 原子写入(`.tmp<pid>` → `rename`) |
| `traffic/sources.local.json`(gitignored) | 本机停用哪些平台:`{"disabled": ["grok"]}`。等价 CLI:`--exclude grok` / `--only kimi` |
| `traffic/scan.py` | **多 AI 流量总览扫描器**(`[--days N] [--json] [--no-cache]`)。读 Claude / Codex / Grok / Kimi 四家 transcript（平台注册表在文件里，**加一家 = 写个解析器 + 加一行**，前端自动跟上）,**纯本地只读、不联网、不消耗任何额度**,与账号池无关。CodexBar「AI用量信息」页的数据源 |
| `claude/claude_tokens.py` | ⚠️ 只统计 Claude 的旧扫描器,能力已被 `traffic/scan.py` 完全覆盖(v0.7.0 起 app 不再调用)。保留仅作 CLI |
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

# 4) 验"这号真的还能干活吗"(⚠️ 计费:每号一次最小补全,实测单次 <1%)
codex-rotate probe plus5 plus7       # 指定号:问 hi,要求答 ok;答出来才算通过
codex-rotate probe --all             # 全池(必须显式,防手滑)
codex-rotate probe plus5 --model gpt-5.5 --effort low
```

菜单栏(CodexBar)装好后顶部显示当前号周额度余量 + 重置倒计时。**左键右键都打开弹窗**(托盘没有原生菜单——macOS 无法让右键不弹它)。弹窗分**账号｜今日**两个 Tab,停留页会记住、重开直达:

- **账号**:每号油表、号间差值、重置卡状态、失效号折叠,**点任意账号会弹出主界面**,切号在主界面卡片上做。底栏 `刷新全池[免费] | 检查 token | 探针[计费]`。
- **今日**:今日总 token / 等效费用 / 较昨日涨跌 + 小时堆叠图 + 三家平台明细(点一行直接跳主窗该平台详情)。数据来自**上次扫描的快照**(读盘 ~1ms),点摘要行的 `↻` 立刻重扫。底栏中键变成 `打开流量总览 ↗`。

退出在主界面「设置」页。构建:`bash codexbar/scripts/deploy.sh`。

> **Dock 图标默认关**(纯菜单栏形态),可在「设置」页打开。开启后**只在主界面打开时**占一格,关掉主界面立刻让出位置(所以不能从程序坞唤起 app,要走菜单栏)。`Info.plist` 的 `LSUIElement` 保持 `true`(决定冷启动瞬间不闪图标),运行期用 `setActivationPolicy` 切,不需重启。

主界面侧栏 4 页:**总览** / **AI用量信息** / 日志 / 设置。消耗页汇总 **Claude + Codex + Grok + Kimi** 四家(v0.7.0 起,取代原来分开的「Token 消耗」与「Claude 消耗」两页):堆叠面积图 + 今日/7/14/30/90d 五档,点任一平台进「详情」看分模型拆解与费率卡。数据源全是**本机 CLI 自己落的盘**、零额度消耗——`~/.claude/projects/**/*.jsonl` · `~/.codex/sessions/**/rollout-*.jsonl` · `~/.grok/**/updates.jsonl`。费用一栏是**按牌价折算的等效 API 成本**(四类 token 分别计价,缓存读按 10%),订阅制下并非实付。

> ⚠️ **消耗页只有 token 量,没有 Claude 的额度油表**,这是刻意的:Claude Code **不把额度写进任何本地文件**(两次实测,最近一次 2026-08-10 覆盖 Claude Code 2.1.224 / 5648 个 transcript:`usage` 里只有 token 计数;唯一相关的结构化字段 `error.rateLimits` **从未被填过**;`~/.claude` 下也无额度快照。⚠️ 朴素 grep 会因为文件路径和对话正文给出大量假阳性),`/usage` 的额度条是实时从服务端拉的。要拿它就必须用订阅凭证调 Anthropic 端点,而 Anthropic Consumer Terms §3 明文禁止「非 API key 的自动化访问」。codex 那页能有油表,是因为 codex **把额度写进了本地 rollout**——两边没有对等物。

## 安全边界(红线)

全 **loopback(127.0.0.1)**、**单人**、**只轮你自己的号**、保活**串行不并发**、**不对外共享 Base URL**。守住这些,风险与你手动切号同级。⚠️ 用订阅 auth 做池化自动化偏离 OpenAI 官方推荐(官方推 API key),个人自用属灰区。

## 维护约定

- ★ **绝不让 python 解释器由 PATH 或 shebang 决定**。Cloudflare 按 TLS ClientHello 指纹拦截,macOS 的 `/usr/bin/python3`(LibreSSL 2.8.3)对 `GET /backend-api/codex/usage` 恒返 **403**,OpenSSL 3.x 同请求恒 **200**(2026-08-01 受控实验,单一变量,各 3 次,同 token/header/IP)。launchd 默认 PATH 只有 `/usr/bin:/bin:...`,所以 `#!/usr/bin/env python3` 必踩。装服务一律走 `scripts/install-launchd.sh`;CodexBar 侧见 `python_bin()`。
  - 排查提示:用 macOS 自带 `curl` 复现"也被挡"**不算独立证据**——它同样链 LibreSSL,是同一个失败模式。换 TLS 栈才是对照组。
- 改 `launchd` 的日志路径要同步 `codexbar/src-tauri/src/lib.rs` 的 `read_logs`(路径是写死的字面量,`proxy` 那条是 `proxy/proxy.log` 不是 `proxy.log`)。
- 改 `state.json` schema 或凭证逻辑要谨慎:proxy / codex-rotate / autosync / keepalive 都读写它。
