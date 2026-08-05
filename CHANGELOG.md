# codex-rotate · CHANGELOG & BUG LOG

构建于 2026-06-09 ~ 06-10。展示层版本号见 `codexbar/src-tauri/tauri.conf.json` 的 `version`(SwiftBar 已退役)。

---

## 构建里程碑

### 账号池层(单号 swap)— 2026-06-09
- `codex-rotate` CLI:槽位以 **OAuth account_id** 为主键,换号 = 同步回写 live `auth.json` 到原槽位(保住轮换的 refresh_token)再载入目标槽。`config.toml` 共享不动。
- **autosync watcher**(launchd):`codex login` 任意新号秒级自动入池。
- **keepalive**(launchd 04:30):初版用"换 auth.json + 跑 codex exec",后(Phase 1a 后)改为 **OAuth 刷新**(零额度/无 auth.json 竞态)。
- SwiftBar 插件:每号 5h/周**剩余额度**双油表(▓░ + Menlo)、email、订阅到期、久未刷新 ⚠️、点击切号。
- 关键发现:Codex 把限流遥测写进 session rollout(`primary`=5h/`secondary`=周,`used_percent`+`resets_at`);也在响应头 `x-codex-*`。

### 自建轮换代理 — 2026-06-10
- **Phase 0(可行性)**:证实原生 codex 经自定义 `[model_providers.rotateproxy]`(base_url=127.0.0.1)+ `auth.command` → 本地代理注入 OAuth bearer + `chatgpt-account-id` → `chatgpt.com/backend-api/codex/{models,responses}` → **200**。★研究 open Q4 解决:auth.command 对**订阅 token** 生效。
- **Phase 1a(OAuth 刷新)**:`POST auth.openai.com/oauth/token {grant_type:refresh_token, client_id:app_EMoamEEZ73f0CkXaXp7hrann}` → 200 + **轮换的 refresh_token**。固化进 `codex-rotate refresh` + 简化 keepalive。
- **Phase 1b(轮换代理)**:`proxy.py` 升级——读池选**用量最少**号 + 跳冷却 + 过期自动刷新 + 429 冷却 + `previous_response_id` 会话亲和(dormant)。★codex 每请求发完整上下文 → 跨号轮换天生安全,**痛点 2 解决(无感、不重启)**。
- **Phase 1c(日常落地)**:`cxp` = `codex --profile rotateproxy`;代理跑 launchd 常驻;SwiftBar 加代理状态指示。
- **Phase 2(逐请求精确记账)**:代理读 `x-codex-*` 响应头 → 写所服务号的 quota(`source=proxy`)+ `last_aid`/`last_proxy_ts`。
- **Phase 3(健壮性闭环 — 2026-06-10)**:① 401 失效转移——代理对 401 先强制刷一次(可救活陈旧 token),仍失败则标 `auth_dead` + **同请求内换下一个号**,死号永不堵死 cxp;`_pick` 跳过 `auth_dead`/已试号。② 死号 UI——菜单栏红色三角 + “\codex login 复活”提示,`\codex login` 重登经 autosync `_syncback` 自动清 `auth_dead`。③ 只读 `health` 命令——查 access token 寿命 + 死号,**不轮换 token**(取代破坏性的 `refresh` 验证)。④ 并发写安全——state.json 改唯一 mkstemp tmp + 进程内 `_state_lock` 的 read-modify-write,根治多线程/多进程同写损坏。

### CodexBar 桌面应用(取代 SwiftBar)— 2026-07

**v0.1.0 → v0.3.0**。SwiftBar 插件退役,展示层重写为 **Tauri 2 + React** 原生 app(`codexbar/`):菜单栏弹窗 + 1000×660 主窗口仪表盘,Dock 隐藏(`ActivationPolicy::Accessory`),自签证书跨重建保 TCC 授权(`scripts/setup-signing.sh`),`scripts/deploy.sh` 一键构建部署。

- **数据模型改造(Codex 取消 5h)**:2026-07 Codex 把 5h 窗口废弃、改周额度,还残留空槽位 `{window_minutes:0, resets_at:null}`。统一不变量:**只有 `window_minutes ≥ 5000`(周=10080/月=43200)才是真实窗口**,幽灵/遗留 5h 槽全部丢弃——前端 `helpers.ts`、CLI `_qfmt`/`refresh-all`、Rust 托盘标题、SwiftBar 四处同步。窗口标签由 `window_minutes` 动态判定(周/月)。
- **菜单栏弹窗**:当前号 hero(有更优号才显示"建议切到")+ 可用账号列表(周额度油表 + 重置倒计时)+ **失效号默认折叠**(`<details>`)+ 底部刷新 + 齿轮直达设置页;托盘标题 `plusN 周 XX% ↻Nd Nh`(天/时换算)。
- **主窗口**:3 列账号卡(渐变色温 + Ring 低额度脉冲 + 双窗口进度条)+ 死号折叠 + Hero 当前号 + ⌘1~⌘9 快捷键切号 + 日志/设置页。
- **功能**:手动切号(点卡片/⌘N/右键菜单)、账号删除(`codex-rotate remove` + 应用内二次确认)、可选自动切号、订阅/token 到期通知、**开机自启**(`tauri-plugin-autostart` LaunchAgent)。
- **右键托盘菜单**:打开主窗口 / 刷新全池 / 切到最佳号 /(分隔)版本 /(分隔)退出——退出与常用项隔开防误触。
- 多轮 Fable/Codex 交叉评审修:失败静默(catch 显 `✗ 失败`)、⌘Q 销毁窗口(改 `ExitRequested` 拦截 hide)、WKWebView `confirm()` 失效(改内联确认)、冷却 `300:00` 时长格式、未探测号假 `0%`(哨兵 `-1` → `—`)、切号后托盘延迟刷新、字体被脚手架 `index.css` 覆盖。


### CodexBar v0.4.0 — 官方 usage API 取代计费探测 — 2026-07-30

**根因**:显示额度长期与真实值不符(实测 app 显示 39% / 官方真值 64%)。旧机制两条腿都不可靠——① `_probe_quota` 发**真计费**的 `POST /codex/responses` 只为读 `x-codex-*` 响应头(Codex 取消 5h 改小额周窗后,每次刷新都在烧真实额度,于是被迫关掉自动刷新);② quotad 退回 tail plain rollout,但经 cxp 代理/resume 会话/wrapper 的用量**不产生可读的新鲜 rollout**(实测最新 rollout 陈旧 25 小时,期间账号真实用量已从 39% 涨到 64%)。

**修复**:改用 Codex CLI 自己的官方端点——从 codex 二进制中挖出 `GetAccountRateLimitsResponse` / `backend-client/src/client/rate_limit_resets.rs`,验证 `GET https://chatgpt.com/backend-api/codex/usage` 返回
`{rate_limit:{primary_window:{used_percent,limit_window_seconds,reset_at},secondary_window},plan_type,credits}`。

- **零消耗**:GET 元数据端点,不计费、不耗 token(对比:旧探测每号每次扣一次真实额度)。
- **覆盖全池**:活跃号与非活跃号同样可读(旧 rollout 方案只覆盖当前号)。
- **兼带健康检查**:401 = token 被服务端 revoke,直接识别死号(JWT exp 查不出服务端作废,见 B21)。
- **恢复自动刷新**:既然免费,quotad 加第二条循环每 180s 刷全池;CodexBar 启动刷新、每日 refreshquota 兜底一并恢复(此前因计费被停)。
- `source` 新增 `usage-api`;`SERVER_SOURCES` 统一"服务端权威读数"概念,freshest-wins 守卫据此不让旧 rollout 覆盖新读数。
- 实测:全池刷新 5.7s,state 与官方真值逐号一致(plus4 68%==68%,plus6 0%==0%,plus7 401 死号)。

---

### CodexBar v0.5.0 — 设计稿 1:1 改版 + 重置卡可视化 — 2026-07-31

按 `design_handoff_codexbar`(主界面定稿 `#1a` / 菜单栏定稿 `v2`)像素级复刻两个界面,并新增重置卡(reset credit)图层。

**托盘交互(用户指定)**
- **左键、右键都打开弹窗**。macOS 上只要给托盘挂了原生菜单,右键就一定弹那个菜单、无法按键分流——所以**整个原生菜单被移除**。原菜单里的动作各自找到新家:打开主窗口 = 点弹窗里任意账号行;刷新全池 / 检查 token = 弹窗底栏;**退出 = 设置页**(带二次确认——本 app 没有 Dock 图标,误点就找不回来了)。
- 弹窗里**点任意账号 = 直接弹出主界面窗口**(不再是切号)。切号统一收敛到主界面卡片的动作条。

**重置卡图层**(数据源见 v0.4.9 的 `codex-rotate credits`)
- 卡片底部徽章:青色 `重置卡 ×N` / 琥珀脉冲 `重置卡 ×N · M张剩D天`(≤3 天) / 灰字 `无重置卡`。
  **张数在任何状态下都不消失**——稿子的即将到期态只写天数(`重置卡 2 天后到期`),既丢了持有量又和"2 张"读起来同形;而真实数据恰是 plus4 持 2 张、只有 1 张次日作废,所以徽章必须同时给出"共几张"和"其中几张要没"。`cardsExpiring` 因此独立于 `cards`,并 `min(cardsExpiring, cards)` 钳位——两个数来自不同时刻的两次拉取(计数随每次 usage 探测刷新、明细只在 `credits` 跑时刷新),缓存可能还留着服务端已经扣掉的那张。
- 菜单栏顶部琥珀横幅取全池最紧急的一张;命中的行左缘色条同步转琥珀。
- Hero 指标行追加 `🎟 重置卡 ×N · 至 YYYY-MM-DD`。
- **数量与到期分层**:数量随每次 usage 探测免费带回;到期只存在于限流的明细端点,所以 `cards>0 && cardDays==null` 是合法状态(显示"到期未知"而非假装没有)。启动时跑一次 `credits` 补齐日期(12h 缓存,冷启动才真发请求)。

**号间对比 / 刷新时间**
- 非当前号右上角差值角标(`最优` / `-N%`,≤-50% 转琥珀);菜单栏行同款。
- `上次全池刷新 HH:MM · N 分钟前` —— **由各号快照的 `captured_at` 派生**,且只认 `source ∈ {usage-api, probe}`:rollout 快照是本地回声不是"刷新过全池",计进去会把池子说得比实际新。

**修掉的两个自伤**
- **网格顺序**:store 按额度降序排,而 ⌘N 提示按 label 顺序生成,结果格子里读出来是 ⌘1/⌘3/⌘4/⌘2。改为网格按 label 排(与 `#1a` 一致),"该用哪个"交给 Hero + `USE` 徽章表达。
- **弹窗自适应高度**:面板在稿里是 `height: fit-content`,而 Tauri 窗口是固定框 → 用 ResizeObserver 量内容再 `setSize`。两个坑:① `core:window:allow-set-size` 没在 capabilities 里,`setSize` 会被静默拒绝;② `.mb-root` 原有 `min-height:100vh` 会让 `scrollHeight` 被当前窗口高托住,**窗口只能变大不能变小**(闩死在最高的一次)。改为面板 auto 高、由 `.mb-list` 持有 `max-height`。

**验证**:tsc / cargo check / oxlint 全绿;两界面用打桩 Tauri IPC 的真实产物在 Chrome headless 渲染比对(注:`--window-size` 小于 500 会被 Chrome 钳到 500 而截图仍按传入宽度裁,一度伪装成横向溢出——量了 `root.scrollWidth=498` 才排除)。

---

### 未发布(v0.5.1 之后)— 计费探针 + 代理双计费修复 — 2026-08-02 ~ 08-05

**计费探针 `codex-rotate probe`**

`GET /models` 返 200 只证明 token 被接受;订阅到期、模型权限被撤、被限流这些,token 照样有效但号已经不能干活。唯一的证明是真发一次补全:

```
codex-rotate probe plus5 plus7          # 指定号
codex-rotate probe --all                # 全池(必须显式)
codex-rotate probe plus5 --model gpt-5.5 --effort low
```

默认 `gpt-5.4` + `reasoning.effort=low`,问「hi」要求原样答「ok」。实测单次 **Δ+0%**(动不了 `used_percent` 的整数位 ⇒ 成本 <1%,这是上界不是点估计),命令逐号打印「探测前 → 探测后」,成本永远在调用处可见。

- **判据是「模型真吐出字」,不是 HTTP 200**:200 只说明请求被受理,流中途断掉也是 200,报"能用"就是假阳性。`_sse_answer()` 拼 `output_text.delta` 取回原话并打印,空回答判失败。
- 只对 `req err`(连不上/TLS 断)重试一次;HTTP 4xx/5xx 是服务端已判决,重试只白烧额度。实测 plus4 报过一次 `SSL: UNEXPECTED_EOF`,紧接着连测三次全 200。
- **不标记 `auth_dead`**:改号池成员资格是那两个带防抖守卫的检测器的事,测试工具再插一手会把"两端点互相打架→每轮翻转→反复告警"请回来。
- GUI 三个入口(主界面工具栏 / 卡片动作条 / 菜单栏底栏第三格),共用 `ProbeButton`:琥珀 + ⚡ + 「计费」角标 + 两段确认(5s 无二次点击自动退回)。这是全 app 唯一花钱的控件。

**★ 代理:一次用户请求被两个账号各计一次费**

用户报「一个会话消耗两个号的额度」,查实是真的。`_open()` 把 `conn.request()` 和 `conn.getresponse()` 的异常混在一个裸 `except` 里,调用方 `continue` **换号重发同一个请求**,注释还写着 "nothing reached codex yet" —— 那句话只对连接阶段成立。生产日志:6937 次成功 / 228 次换号重发,其中 218 次是 `EOF occurred in violation of protocol`。

修复经三轮迭代,**中间一版比原 bug 更糟**,记录如下以免重犯:

| 轮次 | 做法 | 结果 |
|---|---|---|
| ① | 已送出就 abort,返 **502** | ✗ **更糟**。502 是可重试码 |
| ② | 四方评审(fable/codex/grok/kimi)一致点名 blocker | 实测证实 |
| ③ | 改 **400** + 相位/计费判据全部重画 | ✓ |

**实测的状态码重试次数**(假上游顶掉真代理,一次 `cxp exec` 数 `POST /responses`):

```
502 → 30 次      409 → 6 次      429 → 1 次      400 → 1 次
```

②那一版把「可能两个号各计一次」放大成了「最多 N 个号轮着计费」。**别靠记忆猜哪个码可重试,起个假上游数一次。**

其余四条(全部来自四方评审):

- **相位分界画错了位置**,依据也是错的。`sendall` 抛异常 ⟺ 仍有尾段未写入 ⟹ Content-Length 下 body 不完整 ⟹ 上游永不 dispatch ⟹ 不计费。所以分界是 `request()`(**可证明**未计费,换号安全)vs `getresponse()`(已交内核,到没到不可知)。显式 `conn.connect()` 已删。
- **`_billable()` 白名单改黑名单**:`POST /responses` 白名单一旦漏掉新计费端点,双计费静默复活且计数器无感。改 `command not in ("GET","HEAD")`,误判方向翻到安全侧。实测 228 次错误里 212 次(93%)是 `GET /models` —— 不分类型地 abort 会把大量零成本请求打死。
- `send_error` 两处手抄 → 收进 `_abort()`;不再回显 `str(exc)`(本地路径 / TLS 内部信息)。
- 401 → 强刷 → 429 原本当成功转发,绕过冷却,该号继续排在"用量最少"首位。已改为冷却 + 换号。

**可观测性**:`state.json` 新增 `proxy_counters.{committed_aborts, stream_aborts}`。这个 bug 拖到用户自己发现,正是因为它只在日志里留一行没人聚合的 `upstream err`。`stream_aborts` 带计费闸门 —— 实测 545 次断流里 491 次(90%)是无害的 `GET /models`,无条件累加会让指标九成是噪音。

**代理侧修不掉的一类**:54 次计费断流中,85 次紧跟客户端重试(codex 自己重发到别的号)。响应已部分转发,abort 是唯一正确动作,伪造 `response.completed` 收尾更糟。现在至少可量化。

---

### ★ v0.5.1 — 额度长期不准的真根因:LibreSSL 被 TLS 指纹拦截 — 2026-08-01

**症状**:界面显示 plus3 周额度 **100%**,官方真值 **16%**。用户报"滞后性太严重"。

**一路误诊**:此前把 `GET /backend-api/codex/usage` 的 403 归因为「Cloudflare 对该端点的机器人质询,与账号无关、间歇性发作」,依据是"连 curl 也一样被挡,所以是端点级不是客户端问题"。**这条依据是错的**——macOS 自带的 `curl` 同样链接 LibreSSL,复现的是同一个失败模式,却被当成了独立佐证。

**受控实验**(单一变量=解释器,各 3 次,同 token / 同 header / 同 IP / 同一分钟):

| 解释器 | TLS 栈 | GET /usage |
|---|---|---|
| `/usr/bin/python3` | LibreSSL 2.8.3 | **403 · 403 · 403** |
| `/opt/homebrew/bin/python3` | OpenSSL 3.6.3 | **200 · 200 · 200** |

Cloudflare 按 TLS ClientHello 指纹拦截,LibreSSL 2.8.3 的握手被判为非常规客户端。**403 是客户端二进制的属性,不是端点、账号或请求速率的属性。**

**影响面**(全部 launchd 任务都中招,持续了很久):

| 任务 | 原解释器 | 后果 |
|---|---|---|
| `quotad` / `proxy` | `/usr/bin/python3` 显式 | 所有服务端读数 403,额度只能靠不可靠的 rollout 兜底 |
| `autosync` / `keepalive` / `refreshquota` | shebang `env python3`,而 launchd 默认 PATH 只有 `/usr/bin:/bin:...` | 同上;每天的全池刷新一直在空转 |
| CodexBar | `Command::new("python3")` 走继承 PATH | **侥幸没事**——登录 PATH 里恰好有个 OpenSSL 的 venv 排在前面。这正是手动点「刷新全池」有效、后台却一直不更新的原因 |

**修**:五个 plist 全部显式钉 `/opt/homebrew/bin/python3`;Rust 侧 `python_bin()` 按 `CODEXBAR_PYTHON` → `/opt/homebrew` → `/usr/local` → `python3` 顺序解析,不再听 PATH 摆布。

**防复发**:`_tls_is_stale()` 检测 `ssl.OPENSSL_VERSION` 是否为 LibreSSL,403 分支据此把消息从含糊的「被 Cloudflare 质询」换成「本解释器 TLS 过旧(LibreSSL x.y)被指纹拦截,换 … 跑」。上一次就是那句含糊的日志把排查引向了端点和速率。

### v0.5.1 — 事件驱动刷新(额度只在你用 codex 时才变) — 2026-08-01

定时轮询的两段滞后叠加:quotad → state.json 最长 **300s**,state.json → UI 最长 **30s**。

- **quotad 新增活动驱动回路**:1s 轮询四个廉价本地信号(稳态 0.02ms/次),防抖 3s 后只刷**当前号**(cxp 场景加 `last_aid`)。四路信号刻意冗余,各自补对方的盲区——`history.jsonl`(交互提问,漏 `codex exec`)/ 当天 session 目录 mtime(新会话建文件,漏会话内追加)/ 当前 rollout 文件 mtime(会话内追加,需 60s 重扫才跟得上新文件)/ `last_proxy_ts`(cxp 流量,可能完全绕开前三者)。
- **只刷一个号不刷全池**:该端点对突发答 403,而被消耗的就是当前号,全池扫描换不来新信息。全池扫描留在 300s 兜底。
- **重试阶梯 8/20/45s**:一次 403 原本会把这轮更新整个丢掉。重试**不受 `MIN_GAP` 约束**——被挡的那次没拿到任何数据,重试是"第一次成功读取"而非"重复轮询"。
- **Rust 侧监视 state.json**:每秒一个 stat,mtime/size 变化即 `emit("state-changed")`。原来 UI 只能靠自己 30s 轮询,对另一个进程的写入一无所知。首次观测不触发(否则冷启动会误发)。

**实测**(真实 `codex exec`,非模拟触发):

```
00:40:50  codex 发起
00:40:58  [quotad] activity → plus6:HTTP 200     ← +8s,codex 仍在运行
00:41:18  [quotad] activity → plus6:HTTP 200     ← +28s
00:41:38  [quotad] activity → plus6:HTTP 200     ← +48s
00:41:39  codex 结束
plus6 周已用 9.0% → 10.0%,captured_at=00:41:37
```

首次响应 **+8s**(检测 ≤1s + 防抖 3s + 请求 ~3s),此后每 20s 续刷 —— **运行过程中持续更新,不是跑完才更新**。此前最坏 330s。

日志加了时间戳:没有它就无法从日志判断刷新发生在 codex 运行中还是结束后,而这正是调触发器时唯一要问的问题。

---

## BUG 日志

### B1 · 两个号显示完全相同额度 ✅修
**症状**:main/plus2 菜单栏 quota 一模一样。**根因**:rollout **不带 account_id**,旧 `add` 无脑信任"最新 rollout",把别号用量记到刚登录没跑过的号。**修**:严格时间窗归因——只认"成为 active 之后产生的 rollout"(`active_since`,不可为 0);不可归因时清 quota(自愈泄漏)。

### B2 · token 失效要重登 ✅修(类)
**根因**:ChatGPT refresh_token **一次性轮换**;`codex login` 切号绕过同步 → 旧 token 作废。**修**:syncback-before-switch + launchd watcher 每次 auth.json 变就把最新 token 存回槽位 + keepalive 定期 OAuth 刷新闲置号。**残留**:某号已死的 token 只能重登一次(不可程序化复活)。

### B3 · 误删用户日常 codex ✅已恢复(事故)
清理 codex-multi-auth 试点时,`npm uninstall -g @openai/codex` 把**用户日常 codex 的底层包**删了(`~/.local/bin/codex` 是指向它的包装脚本)。**修**:`npm i -g @openai/codex@0.138.0` 重装恢复。**教训**:清理第三方依赖前先确认是否被别的东西依赖。

### B4 · cxp 没走代理(provider: openai)✅修
`-c model_provider=rotateproxy` 不生效。**根因**:codex `-c` 的值需 **TOML 引号**且放**子命令位**才覆盖(全局位/裸词无效)。**修**:改用 codex 0.138 新 **profile** 系统——`cxp = codex --profile rotateproxy`,读独立 overlay `~/.codex/rotateproxy.config.toml`(继承 base 的 MCP/hooks)。注意:主配置里 legacy `[profiles.rotateproxy]` 会冲突报错,已移除。

### B5 · 菜单栏"看不出更新" ✅修(多轮)
- 代理指示只在下拉、标题没变 → 加版本号(v0.6.0)。
- 版本号浮右对齐(空格 padding)很丑 → 并进 `CODEX · 剩余额度 · vX` 行(v0.7.1)。
- **★根因 bug(v0.7.2)**:插件把"代理**服务**在跑"当"用户**在用**代理"→ 跳过 plain codex 的 `quota --save` + 标题显示代理 last_aid 而非新登的 active 号。**修**:`state.last_proxy_ts`(代理每请求写)区分真用 cxp(`NOW-last_proxy_ts<90`)vs plain codex;`quota --save` 在 `rollout.mtime<=last_proxy_ts+12` 时跳过(避免串号)。

### B6 · test-home 被 codex 灌污染 ✅清
代理隔离测试用的 `proxy/test-home/` 被 codex bootstrap 灌了 skills/sessions/sqlite。**修**:`.gitignore` 排除 `proxy/test-home/*`(留 config.toml)+ 物理清掉。

### B7 · 切换号偶发 "Failed to refresh token: session has ended" ✅修
**根因**:`plain codex`(管 live `~/.codex/auth.json`)与代理/keepalive(管 slot)**同时刷同一号的 token** → refresh_token 一次性轮换 → 两边副本互相作废 → "session ended"。**修**:代理对**当前 active 号**直接读写 live auth.json(与 plain codex 共用一份,refresh 不再让 live 陈旧);inactive 号才走 slot。**建议**:统一走 `cxp`(代理是唯一 token 管理者最安全);加号才 `\codex login`;万一真撞到某号死,`\codex login` 重登那**一个**号即可(autosync 自动入池)。

### B8 · 重度 cxp 使用下偶发某号 token 死亡(需重登)✅修
**症状**:并发 cxp 请求(代理是 ThreadingHTTPServer 多线程)**同时刷同一个号**的过期 token → refresh_token 一次性轮换 → 互相作废 → 该号死。**根因**:代理 `_slot_token` 刷新无并发保护。**修**:加 `_refresh_lock` + 双重检查锁(进锁后重读,若别的线程已刷过就直接用),保证一个号同一刻只刷一次。**残留**:跨进程(proxy vs keepalive vs 手动 `codex-rotate refresh`)仍无锁但低频——别在 cxp 重度使用时手动跑 `refresh all`。

### B9 · `refresh` 验证有破坏性 + 跨进程刷新竞争 ✅修
**症状**:让用户跑 `codex-rotate refresh <号>` 去“验证 token 是否健康”——但 refresh **会轮换** refresh_token(一次性),验证本身就把好号推向 reuse 竞争;且 proxy(04:30 keepalive / 手动 refresh)无跨进程锁,可同刷一号致死。**修**:① 新增只读 `health` 命令(看 access token 寿命 + 死号,不刷新);② `_refresh_slot` skip-if-valid(access token 剩 >1h 不刷)+ `fcntl.flock(.refresh.lock)` 跨进程串行 + 锁内重读重判;③ proxy `_slot_token` 刷新同样套 `.refresh.lock`。**规矩**:验证用 `health`,**别再用 `refresh`**。

### B10 · 一个死号堵死整个 cxp(无 401 失效转移)✅修
**症状**:proxy 选“用量最少”号,若它 token 死(401),每个 cxp 请求都打它 → 全 401,死号把整条管线堵死(违背“失效自动换号”)。旧代理只处理 429,不处理 401。**根因**:`_proxy` 单次 pick + 无失效转移。**修**:`_proxy` 改 failover 循环——401 先 `_slot_token(force=True)` 强刷重试同号(救陈旧 token),仍 401 → `_mark_dead` + `continue` 换下一个号;429 → `_cool` + 换号;`_pick(exclude=tried)` 跳过死号/已试号。**自愈**:即便 `auth_dead` 标记被跨进程竞争清掉,下次命中该死号会 401 → 重新标死 + 转移,系统自纠。**实测**:storm 中 plus3 429→main→plus2 全自动级联;单请求 200(ROTATE_OK)。

### B11 · state.json 并发写损坏(末尾 stray `}`)✅修 ★根因级
**症状**:state.json 解析报 `Extra data: line N`(合法 JSON 后多一个 `}`)→ active 乱飘、行为漂移、cxp 偶发崩。**根因**:proxy 是 **ThreadingHTTPServer 多线程**,`_save_state` 用**固定** `state.tmp` 且无锁;多线程(及 codex-rotate autosync/手动 CLI 同名 tmp 跨进程)同写同一 tmp → 字节交错/残留 → `os.replace` 落地即损坏。**修**:① 两边 `_atomic_write`/`_save_state` 改 `tempfile.mkstemp` **唯一 tmp 名**(永不共享路径,最坏 last-write-wins 仍是完整文档);② proxy 新增 `_state_lock` + `_mutate_state(fn)` 把 load→改→原子写整段锁住(防线程间丢更新),`_cool`/`_mark_dead`/`_record_quota` 全改走它。**回归**:15 进程并发写 + 30 并发读 → 0 损坏。

### B12 · 跨账号额度串号(plus3 的用量显示成 plus5)✅修 ★Fable 评审
**症状**:两号菜单栏额度完全相同(plus3≡plus5)。**根因**:cxp 时代,`quota --save` 读最新 session rollout 归因给 `active` 号,但 rollout 是 codex 进程写的、记录的是**代理实际服务号**(plus3)的 `x-codex-*` 遥测,与 live auth.json 里是谁(plus5)无关——rollout 无 account_id,旧 `active_since`/12s 窗口护栏在 cxp 下不成立(`last_proxy_ts` 在流**开始**盖戳,codex 写 rollout 在 turn **结束**,>12s 即穿透)。**修**:`_rollout_is_proxy(p)` 读 session_meta 首行 `payload.model_provider`,`=='rotateproxy'` 的 rollout **永不归因**(`_live_quota` 返 None,一处修好 `cmd_quota`+`_syncback` 两条路径);`quota --save` 不再覆盖/清除 `source=proxy` 的真实数据;`_syncback` 用 `_activate` 同步 `active_since`。**回归**:连跑 3× `quota --save` → 全号 `src=proxy`、0 串号。

### B13 · 池子被陈旧冷却自锁(5 号全 cooling,main 窗口已重置仍冻 4h)✅修 ★Fable 评审
**根因**:429→`_cool` 固定 300m,无视响应头里的真实 `x-codex-primary-reset-at`;`_used` 读 stale 快照把"窗口已重置=满血"的号当 100% 用量→`_pick` 排序垫底。结果整池可用容量大量损失。**修**:`_cool` 按 `resets_at+60` 封顶;`_used` 对已过 `resets_at` 的窗口返 0;`_pick` 把"窗口已重置但 cooldown 未到"视为可用。**验证**:import 调 `_pick` → 选中已解冻的 main(而非死冷却)。

### 菜单栏标题重设计 v0.7.8 · 消抖 ★Fable 评审 + 用户定
**根因(抖动)**:旧标题用 90s 定时器在 `last_aid`(代理模式)和 `active`(plain 模式)间翻转;且 cxp 逐请求轮换不同号→`last_aid` 每请求变→数字跳。**修**:删定时器,标题改显示**池中 5h 余量最高的活号**(=下个 cxp 会选的号,`pool_title()`,跳过死号/有效冷却、已重置窗口算满)。**只在最优可用号变化时动,不再逐请求/90s 翻转**。周额度仍在下拉油表。用户在 3 个方案(最高余量/最近服务号/全池平均)中选「最高余量」。

### B14~B21 · 三方评审修复(codex gpt-5.5 + gemini + fable,2026-06-11)✅修
评审材料/合并结论:`scratch/review-{brief,synthesis}-20260611.md`;回归:`scratch/verify_review_fixes_20260611.py`(18/18 绿)。

- **B14 [P0] active 号 refresh_token 所有权竞争(B9 类最后一条死亡路径)**:proxy `use_live` 路径会刷新 live auth.json,与 **codex 原生刷新器**(不持我们的 flock)抢同一个一次性 RT;且 `switch`/`_syncback`/`_autosync_live` 拷贝凭证全程无锁,可把已消费的旧 RT 写回槽位覆盖新 RT。**修**:① proxy 对 live 号**只读**——token 有效直接用(每次现读,自动接住 codex 自己的轮换),过期/401 返回 `(None,None)` 由 failover 换号,**绝不刷新**;② inactive 刷新在锁内**复查 active**(switch 竞争窗口关闭);③ CLI 所有凭证移动(`switch`/`ensure`/`add`/`_syncback`/`_autosync_live`/`_refresh_slot`)统一持 `.refresh.lock`(autosync 非阻塞,忙则下个 tick 重试);④ `_refresh_slot` 锁内复查 active → `skip-active`。
- **B15 [P0] state.json 跨进程 RMW 丢更新**:CLI `_state()→改→_save_state()` 与 proxy `_mutate_state`(只有进程内锁)互相覆盖——插件每 10s 的 `quota --save` 可悄悄回滚 proxy 刚写的 cooling/auth_dead/quota。**修**:新增 `.state.lock` flock;CLI 磁盘型命令(`STATE_LOCKED` 集合)整段持锁,网络型命令(refresh/keepalive)改**targeted `_mutate_state`** 回写(不再整体 save);proxy `_mutate_state` 同把 flock。锁序恒为 state→cred,无死锁。回归:3 CLI + 3 proxy 进程并发 150 次增量 0 丢失。
- **B16 [P1] `_cool` 被过期快照封顶失效**:429 不带 `x-codex-*` 头时,旧快照 `resets_at` 已过 → `min(now+300m, ra+60)` 把 cooling_until 写成**过去** = 完全不冷却 → 429 循环。**修**:仅 `ra>now` 才封顶;ra 过期(快照陈旧)→ 600s 短冷却兜底。
- **B17 [P1] auth_dead 假复活(★codex 独家发现)**:proxy 标死后 10s 内,插件 autosync 用**同一个被拒 token** 无条件清 dead → 死号回池 401 循环。**修**:`_mark_dead` 记录被拒 token 指纹(`auth_dead_fp`=末16字符);autosync/_syncback 仅在看到**不同 token**(重登/codex 原生刷新)才清;`uncool` 仍可手动强清。
- **B18 [P1] picker 无视周额度**:`_used` 只看 5h;全员 5h 重置后排序退化为 dict 插入顺序——实测请求全路由到周剩 9% 的 main。**修**:`_used` 返回 `(5h用量, 周用量)` 元组(均 reset-aware),周余量多者优先。
- **B19 [P1] 网络异常不 failover**:上游 TLS RST/timeout → 直接 502 return,其余号健康也不试。**修**:`_open` 阶段异常(还没有字节到达 codex)→ `continue` 换号;`_finish` 已开始回流后异常→中止不重放(防 double-send),`streamed` 标记防 send_error 串流。
- **B20 [P1] 标题长期跟随旧 last_aid**:用过 cxp 后改跑 plain codex(不手动 switch)→ `last_proxy_ts ≥ active_since` 恒真,标题一直显示 proxy 旧服务号(可显示 stale 100%)。**修**:`quota --save` 把 plain rollout 的 mtime 落 `state.last_plain_ts`;标题仲裁改三信号取最近(`last_proxy_ts` vs `active_since` vs `last_plain_ts`)——不用固定 TTL(TTL 会在 cxp 长思考间隙重引入翻转抖动)。
- **B21 [P2/P3] 杂项**:`_affinity` FIFO cap 256(codex 不发 previous_response_id,死特性只涨不命中);删死代码 `.keepalive.lock` 守卫 + `_codex_running` + `_run_codex_ping`;proxy auth 写盘改唯一 mkstemp(原固定 `.tmp`,虽被 flock 串行仅作卫生加固);`switch` 无参/`ensure` 的 `_pick_next` 跳过 `auth_dead`(原会把 live 切到死号)。

### refresh-all 子命令 + 每日 07:00 全池刷新(2026-06-12)
**动机**:SwiftBar 对**非 active 号**天生只能显示"切走那一刻的快照",越用越陈旧——实测 main/plus2/plus5 的周额度旧快照(9%/28%/34%)与真实值(100%/100%/96%)差 60-90 个百分点(周窗早重置了,快照没跟上)。
**实现**:`codex-rotate refresh-all` 逐号用**自己的 access token** 发一个最小 `gpt-5.5` "Reply ok" 请求,从响应头 `x-codex-*` 读实时额度写回 `quota`(`source=probe`)。**只读 token**(绝不 OAuth 刷新)、**不切号**;active 读 live auth.json、其余读 slot;写回走 `.state.lock`;末尾刷 SwiftBar。
**probe 形态(实测定位)**:`GET /models` 不计量(200 但无额度头);`POST /responses` 必须 `model`+`instructions`+`input` 三者齐全才进计量层(缺任一→400 无头);最小合法请求→200 + 全套 `x-codex-*` 头。
**代价**:每号每次 +1% 的 5h 窗,**周额度增量 0%**。
**定时**:launchd `com.doushutangmu.codex-rotate.refreshquota`,每天 **07:00(SGT)** 跑一次——早上打开 mac 即见全池近实时额度。非 KeepAlive,睡眠错过会在唤醒后补跑一次。

### `codex resume` 看不到历史会话修复(2026-06-13)
**症状**:`codex resume`(日常 alias=cxp)的 picker 里历史会话全空,要手敲 `\codex resume`(plain)才看得到。
**根因**:`codex` alias→`cxp`=`codex --profile rotateproxy`。Codex 给每个 session 记录运行时的 `model_provider`,而 **resume/fork 的 picker 只列出与当前 provider 匹配的 session**。实测:90 个交互 session 里 89 个 `openai`(plain 跑的)、仅 1 个 `rotateproxy`——cxp(provider=rotateproxy)的 picker 只匹配 1 个="会话都不见了";plain(openai)匹配 89 个=历史全在。(诊断绕路:codex TUI 在 pty/script 下一律秒退,无法非交互捕获 picker;靠 session_meta 的 source=cli + model_provider + cwd 统计定位,help 只文档化 cwd 过滤、未提 provider 过滤。)
**修**:`cxp` wrapper 对 `resume`/`fork` 子命令绕过 `--profile rotateproxy`、走 plain codex(= `\codex resume` 的自动化,省手敲 `\`)。全新会话 / `exec` 仍走代理轮换。**权衡**:resume 出来的会话跑在单个 live 号、**不轮换**——但这与用户原本手敲 `\codex resume` 的行为完全一致,非新增损失。
**未做(可选)**:若想让某个 resumed 会话也走代理轮换,可 `cxp resume <session-id>`(显式 id 跳过 picker 过滤、在 rotateproxy 下恢复)——但 picker 浏览态无法同时"既列全 openai 历史又路由代理"(codex 不暴露"选完返回 id")。

### 菜单栏一直显示 100% · 已重置 修复(v0.8.1,2026-06-17)
**症状**:菜单栏标题卡在 `⚡ 100% · 已重置`,看着像不更新。
**根因(三层)**:① 最近没跑 cxp(`last_proxy_ts` 55h 前)→ proxy 停止逐请求实时记账,标题退回显示 active 号每天 07:00 探测的快照;② **标题只取 5h(primary)窗**;③ 5h 窗每 5h 重置,`resets_at` 一过,`win_remaining` 就把"过了重置时间"读成"已重置满额 = 100%",于是真正吃紧的**周额度**(plus3 42%)被藏掉 → 标题卡 100%。**数据本身更新正常**(07:00 refreshquota 全池 + 用账号时 proxy/quota--save 实时);不用账号时额度不变是**正确的**(无消耗)。
**修(v0.8.1)**:标题改显示**两窗里最吃紧的那个**(`min(5h剩, 周剩)`)+ 对应窗的重置时间。实测:plus3 标题 `100% · 已重置` → `42% · 1h18m`(周窗)。
**追加(v0.8.2,用户定)**:最吃紧窗(周 42%)和下拉里各号的 **5h 行**(99%)视觉上"对不上"——用户扫下拉先看到 5h,顶部 42% 反而困惑。用户在三方案(5h+周并列 / 只看 5h / 池子下个号)中选**只看 5h**:**优先顶部与下拉一致**,接受 5h 重置后显 100%(那是真实的——5h 窗确实满额重置了)。标题改回 `win_remaining(primary)`,周额度看下拉 `周` 行。教训:菜单栏单数字宁可"和明细一致、可被验证",也别为了"更有信息量"而和用户的主参照系(5h 行)错位。

### 重启后菜单栏不自启 修复(第 5 个 launchd,2026-06-17)
**症状**:断电重启后"项目没自启动"。
**实测真相**:后端 4 个 launchd 服务(proxy/autosync/keepalive/refreshquota)**全部重启自启成功**(proxy 有 `RunAtLoad`+`KeepAlive`,登录时由 `~/Library/LaunchAgents` 自动加载;实测重启后 proxy 在听 8011)。**只有 SwiftBar 菜单栏没起**——它是 GUI App、macOS 登录项里没注册,后端服务起来也带不出菜单栏,用户遂以为"整个项目没自启"。
**修**:新增第 5 个 launchd `com.doushutangmu.codex-rotate.swiftbar`(`RunAtLoad` → `open -g -a SwiftBar`),把 SwiftBar 自启纳入项目 launchd 体系(与"一切走 launchd"一致,SETUP 可复现)。`open` 秒退,故只 `RunAtLoad` 不 `KeepAlive`(否则空转重启)。**实测**:杀掉 SwiftBar → bootstrap 该 plist → RunAtLoad 自动拉起 SwiftBar,重启自启验证通过。文档:SETUP §6 + RUNBOOK §1/§3 同步。

### 三方评审:全员"7天未刷新·可能需重新登录"误报 + keepalive 保鲜失效(B22~B25,2026-06-17,v0.8.3)
**症状**:菜单栏 5 个号全部 `⚠️ 7 天未刷新 · 可能需要重新登录`。
**三方评审**(omc ask codex gpt-5.5 + gemini + 我,brief/synthesis 在 `scratch/review-*-20260617`):**根因一致**——`last_refresh` 被插件当成"凭证健康"信号,但 B9 的 skip-if-valid(access 剩 >1h 不刷)让 `_refresh_slot` 在 token 健康时跳过,`last_refresh` 不再等价于 token 新鲜度。**JWT `iat` 铁证**:token 06-10 签发、06-20 过期(**有效期 10 天**),`auth.last_refresh==state.last_refresh==06-10` 一致无 divergence,token 实际**还有 70h**——警告**纯误报**。
- **B22 [P1] 误报警告**:插件警告改基于 **access token 实际 `exp`**(解 `auth/<id>.json` 的 JWT,`access_left_h()`),不再用 `last_refresh` 年龄。`auth_dead` 仍是唯一"需重登"信号;access 过期只提示"跑一次 codex/cxp 自动刷新"(自愈,非告警)。顺带:插件改读 auth 文件后,**proxy 刷新不回写 state.json 的问题被绕过**(插件不再看 state.last_refresh)。
- **B23 [P1] keepalive 保鲜失效 + idle coverage gap**:`cmd_keepalive` 原用 `last_refresh>4d` 判定(被 skip-if-valid 架空,从不触发)。改为按 **access token 剩余时间**:`_refresh_slot` 加 `min_valid_seconds` 参数,keepalive 用 **48h**(> 24h daily cadence)→ token 在过期前一天的 04:30 被刷,**关闭"idle token 14:00 过期→次日 04:30 才刷"的 ~23h 缺口** + 让 `last_refresh` 保持新鲜。手动 `refresh` 仍保守 1h、proxy on-expiry 仍 60s(分层有意)。
- **B24 [P1] active 号 last_refresh 不落 state**:`_autosync_live` 的 `changed` 原不含 `last_refresh` 变化 → codex 刷新 active token 后 state.json 不更新。修:`lr_changed` 纳入 `changed`。
- **B25 [P2] log 把 no-op 写成刷成功**:`_refresh_slot` 返回 "still valid" 时原进 `refreshed=[...]`,现进 `skipped=[...]`(log 不再假装刷新)。顺带删死代码 `_age_days`。
**不改(设计权衡,三方认同)**:active 号不由 keepalive 刷(codex 拥有 live token,强刷抢一次性 RT = B14 红线);三处刷新阈值分层(proxy 60s / 手动 1h / keepalive 48h)是有意的。
**验证**:误报警告 0 条;`access_left_h` 实测每号 ~70h;`keepalive --dry-run` → `70h-left > 48h → 不刷`(明天 <48h 才刷);AST + 渲染通过。

---

## 已知待办 / cleanup
- ~~`_run_codex_ping`/`_codex_running`/`CODEX_BIN`/`LOCK` dead code~~ → B21 已删。
- ~~代理刷新与 keepalive 并发刷同一号~~ → B9 已加 `.refresh.lock` 跨进程串行解决。
- ~~`auth_dead` 被 autosync 竞争清掉~~ → B17 指纹门控 + B15 state 锁双重解决。
- SwiftBar 额度归因:plain 模式靠 rollout 时间窗、代理模式靠 `x-codex-*` 头——两套已对齐,但跨模式快速切换的边界(±10s)可能短暂不准。

## 插件版本史
- `v0.6.0` 加版本号显示
- `v0.7.0` 版本号右对齐(padding,已废弃)
- `v0.7.1` 版本号并进 CODEX 头部行
- `v0.7.2` 修"代理服务在跑 ≠ 在用代理"(plain codex 号不刷新额度)
- `v0.7.3` 窗口过重置时间 → 显示 100% 余量
- `v0.7.4` 软化"遥测为空"警告(仅活跃号);配合 B7 代理 live-token 同步修
- `v0.7.5` 配合 B9——新增只读 `health` 命令(取代破坏性 `refresh` 验证)
- `v0.7.6` 配合 B9——proxy `_slot_token` 跨进程 `.refresh.lock`
- `v0.7.7` 配合 B10——死号红色三角 + "\codex login 复活"提示(`auth_dead`)
- `v0.7.8` 标题消抖——删 90s 翻转定时器(Fable 评审);曾短暂改显示"池中最高余量号",v0.7.10 按用户要求改回"当前在用号"
- `v0.7.9` 冷却显示 reset-aware——`effectively_cooling()` 单一真源,修"冷却中"+"5h 已重置"自相矛盾(选号器/标题/显示三处统一)
- `v0.7.10` 标题改回**当前正在用的号(last_aid)的额度**(用户:"在用什么号就显示对应号额度");仍无 90s 定时器(消抖保留),proxy KeepAlive-up 下直接跟随服务号,选号器粘最少用号→分段稳定
- `v0.7.11` 修"手动切号后标题不更新"——根因:`shown=last_aid` 只跟 cxp 服务号,手动切号改的是 `active` 不是 `last_aid`(实测 last_proxy_ts 2h 前=plus2,active 刚切 plus4,标题错显 plus2)。改:标题跟**最近一次选号事件**——`last_proxy_ts`(cxp)vs `active_since`(手动切号)谁更近显示谁。切号即时反映,跑 cxp 时跟服务号
- `v0.8.0` 配合 B20——标题仲裁加第三信号 `last_plain_ts`(plain rollout mtime,quota --save 落):cxp 用过之后回去跑 plain codex(不切号)标题也能跟回 active 号;无固定 TTL,无抖动回归
- `v0.8.1` 标题改显示**最吃紧窗**(`min(5h剩,周剩)`)而非只看 5h——修"5h 窗过 resets_at 被读成 100% 把周额度藏掉"导致的"卡 100%·已重置"
- `v0.8.2` 标题改回**只看 5h(primary)**——用户优先顶部与下拉 5h 行一致(v0.8.1 最吃紧窗虽有信息量但和下拉 5h 视觉对不上,顶部显周 42%/下拉看 5h 99% 让人以为不同步);周额度仍在下拉 周 行
- `v0.8.3` 配合 B22——下拉的 token 健康警告改看 access token 真实 `exp`(`access_left_h` 解 auth JWT),不再用 `last_refresh` 年龄;删死代码
- `v0.8.4` 下拉顶部加 **🔄 立即刷新全池额度** 一键按钮(跑 `codex-rotate refresh-all` 逐号探测,各号 +1% 5h;refresh-all 完成后自动回刷菜单)
- `v0.8.5` 给刷新按钮加**可见反馈**——`refresh-all --notify` 弹 macOS 通知「✅ 额度已刷新 N/5 + 各号周额度」。根因:按钮 v0.8.4 其实在工作(实测 captured_at 即时更新),但 SwiftBar 点击即关下拉、标题(5h~99%)又不变→看着"没作用"。通知是点击的可见 ACK;cron(refreshquota)不带 --notify 保持静默
- `v0.8.6` **修额度虚高**(用户报"账户没那么高了")——`win_remaining` 原对 `resets_at<=now` 的窗口无脑返 100%,**丢弃了真实 `used_percent`**:实测 plus3 used=39%(剩61%)但 resets 名义过期→显 100%(虚高 39 点)。ChatGPT API 常返回「新鲜 used + 过期 resets」(窗口边界延迟),"过了重置时间"≠"已重置满额"。改 **captured_at 感知**:快照晚于 resets→用 `100-used`(真实);仅快照早于 resets(重置后无数据)才乐观 100%。单元测试 4 例全过(含 plus3 场景 →61%)。⚠️ 这只治"显示逻辑";数据本身仍靠探测,**不走 cxp 时仍会陈旧**——根治见三方评审的「统一计量」方向
