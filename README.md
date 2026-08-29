# codex-rotate

把 **多个个人 ChatGPT Plus/Pro 账号** 做成一个池子,为 **Codex CLI** 透明轮换使用——一个人、自己买的号、全程本机、loopback-only、同一家庭 IP。

> 日常:用 **`cxp`** 代替 `codex`,你的 Codex 会话就会在多个号之间**逐请求透明轮换**:撞限自动换号、token 自动刷新、长会话消耗摊到所有号 ≈ **把额度上限扩成 N 倍**。菜单栏实时看每号余量。

> 🆕 **新电脑从零搭建** → [**SETUP.md**](SETUP.md)(凭证不搬运,新机 `codex login` 重新生成)。日常用法 / 排障 / 不变量 → [RUNBOOK.md](RUNBOOK.md)。

## 先看这个:这套东西是两半

| | 【A】AI 用量信息 | 【B】账号池 + 轮换代理 |
|---|---|---|
| 干什么 | 汇总本机各 AI CLI **已经落盘**的 token 消耗 | 多个 ChatGPT 订阅做成池子,给 Codex CLI 逐请求透明轮换 |
| 要凭证吗 | **不要**。只读本机文件、不联网、不碰 token | 要,每号 OAuth |
| 谁能用 | **任何 macOS 用户**,装了下面任意一家 AI CLI 就有数据 | 需要自备多个 ChatGPT Plus/Pro |
| 风险 | 无 | ⚠️ 自负,多账号轮换受 OpenAI 条款约束(本仓库 CHANGELOG 的 B7/B8/B14/B21 记过实测掉号) |

**只想看自己电脑烧了多少 token,只装 A 就行**,三步:

```bash
brew install python3 node && curl https://sh.rustup.rs -sSf | sh   # 前置(python3 必须 OpenSSL 构建)
git clone https://github.com/zhuisen/codex-account-rotator.git && cd codex-account-rotator
bash codexbar/scripts/setup-signing.sh && bash codexbar/scripts/deploy.sh
```

clone 到哪个目录都行 —— `deploy.sh` 会把仓库路径烧进二进制。完整说明见 [SETUP.md §6](SETUP.md)。

覆盖的 CLI:**Claude Code · Codex · Grok · Kimi · Antigravity(agy) · OpenClaw · Reasonix · DeepSeek Harness**。加一家 = 在 `traffic/scan.py` 写个解析器 + 注册表加一行,前端自动跟上。

⚠️ **agy 只覆盖 print 模式**(`agy -p`,即 `omc ask` / `omc team` 走的那条)。它自己**不落用量**,数据是 `bin/agy` wrapper 从 `--output-format json` 抄下来的;**交互式会话拿不到**,页面上有覆盖率徽章标注。装这一家需要一步额外配置,见 `SETUP.md` §2.1。

---

## 它解决的 4 个痛点

| 痛点 | 怎么解的 |
|---|---|
| ① token 失效要重登 | 代理挑到 token 过期的**非活跃**号时当场 OAuth 续期(双重锁) → 有流量的号**不用手动重登**。⚠️ 定时保活(keepalive)已于 2026-08-29 取消,所以**长期不被挑中的号不会自愈** —— 那种情况手动 `codex-rotate refresh <label>` 即可(非活跃号安全);真死了才 `codex login` |
| ② 会话内切号要重启 | 代理逐请求透明轮换;Codex 每请求发完整上下文 → **中途换号无感、不重启**。同一段对话靠 body 里的 `prompt_cache_key` 粘住同一个号(codex 不发 `previous_response_id`,见 CHANGELOG B26) |
| ③ 额度不实时 | **事件驱动**:quotad 监测 codex 活动(4 路本地信号)→ 数秒内读**官方 usage API**(零消耗)刷当前号;实测发起调用后 **+8s** 见数、运行中每 20s 续刷。另有 300s 全池扫描兜底 + 代理逐请求记账 |
| ④ 撞限要手动换 | 代理撞 429 → 标冷却 → 下个请求自动换号 |

## 架构:两层协作

```
                    ┌─ 账号池层 (auth.json swap) ────────────────────┐
  codex login 新号 ─┤  codex-rotate(CLI)  +  autosync(watcher)     │
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
| `.traffic-cache.json`(gitignored) | `traffic/scan.py` 的**逐文件增量缓存**(~14MB,按 `(mtime,size)` 命中)。冷 ~23s → 热 ~0.8s 靠它。额外存 `off`+锚点哈希，Claude 据此**只解析追加的部分**。删了只是重扫一次,不丢数据 |
| `.traffic-latest.json`(gitignored) | 最近一次扫描的**成品快照**(~91KB)。两个 webview 都先读它再后台重扫,所以进页面/点托盘不再等 1~3 秒。由 `run_traffic` 原子写入(`.tmp<pid>` → `rename`) |
| `traffic/sources.local.json`(gitignored) | 本机停用哪些平台:`{"disabled": ["grok"]}`。等价 CLI:`--exclude grok` / `--only kimi` |
| `traffic/scan.py` | **多 AI 流量总览扫描器**(`[--days N] [--json] [--no-cache]`)。读 Claude / Codex / Grok / Kimi / Antigravity 五家 + OpenClaw / Reasonix / DeepSeek Harness 三个宿主源(按模型名回流各家)（平台注册表在文件里，**加一家 = 写个解析器 + 加一行**，前端自动跟上）,**纯本地只读、不联网、不消耗任何额度**,与账号池无关。CodexBar「AI用量信息」页的数据源 |
| `traffic/discover.py` | **数据源体检**(`--json`):找本机还有哪些 AI 把用量落了盘,并现场验算它的 token 口径。纯本地只读、不联网、不碰凭证,SQLite 一律 `mode=ro`,**只出报告不自动启用**(接一家的实质是写解析器) |
| `claude/claude_tokens.py` | ⚠️ 只统计 Claude 的旧扫描器,能力已被 `traffic/scan.py` 完全覆盖(v0.7.0 起 app 不再调用)。保留仅作 CLI |
| `scripts/install-launchd.sh` | **生成并加载 3 个 launchd 服务**(autosync/quotad/proxy)。★ keepalive(04:30)与 refreshquota(07:00)已于 2026-08-29 按需取消 —— 前者职责由代理接手(覆盖面见上表①),后者与 quotad 的 300s 全池扫描重复。两个 CLI 子命令仍可手动跑。生成而非提交成文件:plist 内嵌绝对路径,提交的副本换台机器就是错的,且会静默漂移(旧的 `launchd/*.plist` 就漂到了写死 `/usr/bin/python3`)。★脚本会**解析并钉住 OpenSSL 版的 python3**,见「维护约定」 |
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

菜单栏(CodexBar)装好后顶部显示当前号周额度余量。标题有**四种风格**可在「设置」页切换 —— 完整 `pro1 周 67% ↻5d21h` / 简 `pro1 67%` / 极简 `67%` / 今日 `67% 🔹 1.29B`(最后一档把账号池余量与今日全平台 token 并成一行);百分比那一段按余量阈值**染色并加粗**(≥50% 绿 · <50% 琥珀 · 耗尽红),额度未知时退成 `—` 且不上色。**左键右键都打开弹窗**(托盘没有原生菜单——macOS 无法让右键不弹它)。弹窗分**账号｜今日**两个 Tab,停留页会记住、重开直达:

- **账号**:每号油表、号间差值、重置卡状态、失效号折叠。**点任意账号会弹出主界面**;鼠标停在某一行上,行尾会淡入一个**「切换」按钮 —— 点它直接换号,不打开主界面**(当前号不显示这个按钮)。底栏 `刷新全池[免费] | 检查 token | 探针[计费]`。
- **今日**:今日总 token / 等效费用 / 较昨日涨跌 + 小时堆叠图 + 各平台明细(点一行直接跳主窗该平台详情)。数据来自**上次扫描的快照**(读盘 ~1ms),点摘要行的 `↻` 立刻重扫。底栏中键变成 `打开流量总览 ↗`。两个窗口共用同一份快照与同一条新鲜度规则,谁扫完都会广播给对方,所以**不会各扫一遍**。

退出在主界面「设置」页。构建:`bash codexbar/scripts/deploy.sh`。

> **Dock 图标默认关**(纯菜单栏形态),可在「设置」页打开。开启后**只在主界面打开时**占一格,关掉主界面立刻让出位置(所以不能从程序坞唤起 app,要走菜单栏)。`Info.plist` 的 `LSUIElement` 保持 `true`(决定冷启动瞬间不闪图标),运行期用 `setActivationPolicy` 切,不需重启。

主界面侧栏 4 页:**总览** / **AI用量信息** / 日志 / 设置。消耗页按平台汇总本机各 AI CLI 的落盘用量(v0.7.0 起,取代原来分开的「Token 消耗」与「Claude 消耗」两页)。★ **OpenClaw 是宿主不是平台**:它每条记录按**模型名**归到真正的平台(`gpt/o1/o3/o4`→Codex、`claude`→Claude、`deepseek`→DeepSeek、`mimo`→MiMo…,认不出才回落 provider 名),所以**页面上的平台数不固定**,取决于你在 OpenClaw 里用过哪些模型:堆叠面积图 + 今日/7/14/30/90d 五档,点任一平台进「详情」看分模型拆解与费率卡。数据源全是**本机 CLI 自己落的盘**、零额度消耗——`~/.claude/projects/**/*.jsonl` · `~/.codex/sessions/**/rollout-*.jsonl` · `~/.grok/**/updates.jsonl` · `~/.kimi-code/sessions/**/wire.jsonl`。费用一栏是**按牌价折算的等效 API 成本**(按 token 分类分别计价,缓存读按 10%),订阅制下并非实付。

> **AI 平台管理**(「设置」页):每个平台可**改名 / 改色 / 停用 / ▲▼ 排序**,偏好存 localStorage 并经 Tauri 事件广播给菜单栏。**停用 = 整家从图表与汇总里移除,总 token 与总费用跟着扣**;排序只影响列表与图例,堆叠图仍按占比大的贴基线。⚠️ 它只管「怎么显示」,不管「有没有数据」—— 后者由 `traffic/scan.py` 的注册表决定,与 `traffic/sources.local.json` 的 `{"disabled":[…]}`(那层压根不解析)是两回事。

> **「扫描新数据源」**(「设置」页,实测 ~40s):找本机还有哪些 AI 把用量落了盘,并现场验算它的 token 口径(哪些字段加起来等于 total ⇒ 缓存要不要减)。**只出报告、不自动启用** —— 接一家的实质是写一个解析器。

> **缓存计入口径**(「设置」页,三档):`含缓存` / `不含缓存读` / `不含缓存`。**token 量与费用一起变**,并且**页面构成也跟着变**——不计入的类,它的指标(总览的「缓存」KPI、详情页费率卡的「缓存读」列、构成行里对应项)会从页面上消失,而不是显示成 0%。本机 90 天量级：**36.71B/$31,229 · 1.54B/$12,132 · 0.58B/$5,876**（2026-08-16 实测，新费率表）
> 三档相差如此之大,是因为 `cache_read`(每轮重发完整历史)占 **96%**;而中间那档保留 `cache_write`,因为它是**首次发送并写入缓存的新内容**——没有缓存机制这些 token 照样要发。改动即时同步到菜单栏。

> ⚠️ **订阅「到期」日期后面带琥珀 `*` 时,别当真**。到期日只存在于 id_token 的声明里,而
> **OpenAI 签发新 token 时不重新查计费系统**,只把上次复核的订阅快照原样抄进去(同一个 JWT 里的
> `chatgpt_subscription_last_checked` 就是那次复核的时刻)。所以**续费成功后到期日不会立刻更新,
> 刷新 token 也拉不到** —— 实测强制刷出全新 token,复核时间仍停在 11 天前。带 `*` = 这个日期已过期
> 但那次复核比它还早,结论不可信;此时以健康检查(`服务端:✅活`)为准,等 OpenAI 自己复核。

> ⚠️ **消耗页只有 token 量,没有 Claude 的额度油表**,这是刻意的:Claude Code **不把额度写进任何本地文件**(两次实测,最近一次 2026-08-10 覆盖 Claude Code 2.1.224 / 5648 个 transcript:`usage` 里只有 token 计数;唯一相关的结构化字段 `error.rateLimits` **从未被填过**;`~/.claude` 下也无额度快照。⚠️ 朴素 grep 会因为文件路径和对话正文给出大量假阳性),`/usage` 的额度条是实时从服务端拉的。要拿它就必须用订阅凭证调 Anthropic 端点,而 Anthropic Consumer Terms §3 明文禁止「非 API key 的自动化访问」。codex 那页能有油表,是因为 codex **把额度写进了本地 rollout**——两边没有对等物。

## 安全边界(红线)

全 **loopback(127.0.0.1)**、**单人**、**只轮你自己的号**、保活**串行不并发**、**不对外共享 Base URL**。守住这些,风险与你手动切号同级。⚠️ 用订阅 auth 做池化自动化偏离 OpenAI 官方推荐(官方推 API key),个人自用属灰区。

## 维护约定

- ★ **绝不让 python 解释器由 PATH 或 shebang 决定**。Cloudflare 按 TLS ClientHello 指纹拦截,macOS 的 `/usr/bin/python3`(LibreSSL 2.8.3)对 `GET /backend-api/codex/usage` 恒返 **403**,OpenSSL 3.x 同请求恒 **200**(2026-08-01 受控实验,单一变量,各 3 次,同 token/header/IP)。launchd 默认 PATH 只有 `/usr/bin:/bin:...`,所以 `#!/usr/bin/env python3` 必踩。装服务一律走 `scripts/install-launchd.sh`;CodexBar 侧见 `python_bin()`。
  - 排查提示:用 macOS 自带 `curl` 复现"也被挡"**不算独立证据**——它同样链 LibreSSL,是同一个失败模式。换 TLS 栈才是对照组。
- 改 `launchd` 的日志路径要同步 `codexbar/src-tauri/src/lib.rs` 的 `read_logs`(路径是写死的字面量,`proxy` 那条是 `proxy/proxy.log` 不是 `proxy.log`)。
- 改 `state.json` schema 或凭证逻辑要谨慎:proxy / codex-rotate / autosync / quotad 都读写它(CodexBar 只读)。
