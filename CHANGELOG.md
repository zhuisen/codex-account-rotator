# codex-rotate · CHANGELOG & BUG LOG

构建于 2026-06-09 ~ 06-10。展示层版本号见 `codexbar/src-tauri/tauri.conf.json` 的 `version`(SwiftBar 已退役)。

---

## 已知验证缺口（长期）

（2026-10-01 从 memory.md 搬来，逐字未改）

⏳ v1.8.0 本批留下的（别当已验）：
  1. **真机没点过**：装机版上真点一次「接入」——harness 四态像素已验，但
     `apply` 的 `services` 那一步会真跑 `install-launchd.sh` + `launchctl`，
     **测试里一律没选它**（只有静态闸验「失败必须如实上报」）。
  2. **安装包场景的运行时复制没在真 `.dmg` 上跑过** —— 本机是 clone 装机（`inplace=True`），
     走的是「原地用」那条分支；复制那条只在沙箱夹具里验过。
  3. Windows 侧 Connector **完全没验**（`install-launchd.sh` 是 macOS 专属，
     Windows 要走 `install-windows.ps1`，`connector.py` 目前只调前者）。
  4. 上一批遗留仍开着：外链端到端没点过；Clipsync 那 10 具僵尸未查。

> 2026-09-14 从 `memory.md` §1a **整段搬来，逐字未改** —— 它们是「已发版但某一面没验到」的
> 长期状态，不是进行时。里面有几条带当时的实测数字（`67501 行里各 0 次`、`谷底 ~1037px`、
> `Δinput 98 与 4681`…），摘要会把那部分磨掉，所以只搬不压。
> **判「这个验过了吗」先搜这一节。**


- **额度未知的号会饿死**（机制已写进 `CLAUDE.md` §8「续期只剩代理」）：**未做**根治 —— 要给这类号留一条最低限度的探测配额，否则「过期→读不到→排最后→更不被挑中」这个环不会自己断。
- **`tick_usage` 用 `redirect_stdout(StringIO())` 吞掉 `cmd_refresh_all` 的每账号结果**。
  「plus5 连续两百多次刷新失败」本该是个信号，却一个字都没留 —— 18 小时无人知晓。未修。
- **plist 被谁改写的仍未查明**（现象与判法已进 `CLAUDE.md` §3.1）。重跑脚本能修，但会被再次改写。

- **v0.12.9 的根因是强推断，不是实证**：受影响机器上 100% 那一帧的 `quota` 快照**没拿到**。
  一个问题即可定案 —— 跳变时那张卡上**有没有出现「5h」标签**（Pro 号本无 5h 窗口，
  出现即证明 `codex_bengalfox` 那套被写进去了）。本机数据只能证明机制存在、能产生那两个数。
- **`proxy.log` 对额度写入零留痕**（67501 行里 quota/primary/secondary/window/x-codex 各 0 次）。
  proxy 每个请求都写 quota 却一个字不记，事后无法复盘"当时写进去的是什么"。
  这次全靠恰好抓到一次实时写入。`quota_marks` 也只记 primary 的**整数**变化 ——
  secondary 被写 null、window_minutes 翻转、resets_at 变化**统统不可回溯**。

- **「名字被截断」这类缺陷 harness 结构上抓不到**：`make_harness.py` 的探针对
  `textOverflow: ellipsis` 的元素直接 `continue`。v0.12.8 里紧凑格名字被截成 `Anti…`
  就是**肉眼**发现的，不是探针。只能靠宽度采样 + 人看，别以为 sweep 绿就没截断。
- **紧凑区列宽随窗宽呈锯齿波**，谷底在 ~1037px（rail 展开）与 ~913px（折叠），
  每格只剩 264px、名字仅余 68px，`Antigravity` 余量近零。已把这两档加进 sweep，
  但**没有把"余量"本身做成断言** —— 换一个更长的平台名进注册表，谷底会先破。

- **v0.12.7 的像素验证全在 Chrome headless**，线上是 WKWebView。本仓库为此栽过一次
  （`zoom` 在 Chrome 干净、真机炸）。本次逐版本地构建交给用户真机看过，但**没有自动化的
  WKWebView 闸** —— 抓屏被 TCC 挡住（CLAUDE.md §2），这条缺口是结构性的。

- **小时桶只有形状闸（AST），没有行为闸**。grok 给了做法且**不需要改生产接口**：
  测试里 `patch.object(scan.time, "time", …)` + `TZ=Pacific/Chatham`，把「今天」钉在 DST 切换日，
  写一条本地 02:50 的行真跑 `scan()`，assert 小时键是 `T02` 不是 `T03`。
  （小时桶只对「今天」建，所以必须能控时钟。）
- **AST 闸的固有上限**（grok 实测，非本轮新引入）：日桶仍用 `bisect_right`、小时桶改走
  赋值别名 / `bisect.bisect` / `//3600`，或把 `strftime("%Y-%m-%dT%H"` 只留在注释里 —— 仍会绿。
  形状闸拦得住诚实改动，拦不住刻意绕过；真要钉死只能上行为闸（见上一条）。
- **单实例闸门未经真实脏关机重启验证**（需重启机器）。已验:并发竞态、崩溃后无陈旧锁、fail-open。
- **`_scan_dsh_file` 一条真实数据都没跑过**：`~/.dsh` 不存在、dsh CLI 未装。它的口径是外部贡献者的实测**转述**。
  第一次真扫到数据时，照 `_scan_openclaw_file` 的做法先做一次「朴素求和 vs 去重后」交叉核对再信。
- **入场动效的运动过程没验过**：headless 的 virtual time 会跳到终态，`.cb-wipe` 与数字滚动的**动感**只能真机看。
  已验的是最终值正确、无负数、无卡 0、零报错、零溢出。
- **`codex-rotate add <label>` 仍不校验重名**（只堵了 rename）。重名会让 `switch`/`probe` 静默操作到错的号上。
- **菜单栏高度那个 bug 的真因没能区分**（RO 没触发 / 隐藏窗口 setSize 失败 / 只量了一次）。
  修法在三种假说下都成立，真机也验过（空跑 12 小时无数据后首次弹出正常），但**机制仍是未知**。
  ⚠️ **harness 判不了这件事**：RO 在 headless 虚拟时间下投递不确定，同配置连跑 3 次结果不同 ——
  以后再碰 ResizeObserver 驱动的行为，别拿 harness 当判据。
- **增量解析未覆盖 `/compact` 与 resume/fork 是否原地重写** transcript —— 那正是锚点守卫要挡的场景，
  本轮没触发到。真发生时会退回全量重解析（不会算错），但**「守卫真的挡住了」这件事没有实证**。
  判别实验：跑一次 `/compact` 后看 `scan.py` 的 `scanned` 是否为该文件 +1（而不是走 incr）。
- **增量只对 claude 启用**。grok/kimi/openclaw/agy 逐行无状态、可加但只占热数据 3%；
  codex/reasonix/dsh **不可能加**（跨行状态 / 整文件解压）。别看到 `lines` 就以为是通用能力。
- **agy 覆盖率仍是上界**（主源换 SQLite 后 95.2%，见 CHANGELOG B41）：分母来自
  `transcript.jsonl`，agy 清理过旧会话的话分母也偏小，缺口补不回来。
  ⚠️ **额度序列（`agy_quota`）是另一本账**：单位是额度% 不是 token，
  **不可相加、不可相减、不可折算成钱**。两本账并存这一点没变。
- **agy 的 CLI 自报 usage 与线上 wire 对不上**，n=2 且差值不稳（Δinput 98 与 4681）。会话累计语义解释掉了
  output 那一项，input 仍差一截。判别实验：连开 3 个全新会话各跑一轮，看 Δ 是否稳定在同一个小常数。
  不影响记账（记的就是 CLI 自报值，差分自洽），但**别拿它当"精确到 token"用**。
- **`model=unknown` 若再出现 = 回填坏了，不是正常态**：wrapper 在 agy 退出后立刻读日志，正常必取得到。
  真出现只可能是日志目录不可读、或 agy 改了日志格式。回填脚本范式 `scratch/backfill_agy_model_20260819.py`
  （已做变异测试：日志查不到的会话如实留 `null`，不瞎编）。

- **Reasonix 日志自带厂商真实费用**（`cost_amount`），我们按峰价上界估，对调价前的历史记录高估 3.2 倍。
  已知取舍不是 bug —— 要算准得让 row 多带一位成本并贯穿到前端，当前量级（单请求 $0.003）不值得。


## 构建里程碑 → 已分卷

> 2026-09-14 整段移到 [`docs/CHANGELOG-archive-2026H1.md`](docs/CHANGELOG-archive-2026H1.md)（**逐字未改**）。
> 主文件只留 BUG 日志与最近的批次；查早期构建史去那一卷。

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

### B26 · 会话粘性建在 codex 从不发的字段上,两年一次没命中 — 2026-08-09 ✅修 ★根因级

**症状**:用户报「一个会话一个问题请求了两个账号」,多个号的 `used_percent` 长期被拉平到同一个值。

**根因**:`proxy.py` 的 `_affinity` 用 **`previous_response_id`** 做 key,而 codex **从不发这个字段**(实测 2291/2291 次请求全无,选号原因 100% 是 `new`)。于是粘性代码写在那儿却**一次都没命中过**,每个请求都重新 `_pick`;叠加 `_pick` 的「最少使用者优先」+ 服务端只回**整数** `used_percent`,几个号一打平就来回横跳。

**正确的 key 在请求体里**:实测 codex 每个 `POST /responses` 的 body 键为
`client_metadata, include, input, model, parallel_tool_calls, **prompt_cache_key**, reasoning, service_tier, store, stream, text, tool_choice`
—— `prompt_cache_key` 是 OpenAI 标识 prompt cache 血缘的字段,同一会话恒定。

**修**:选号优先级改为 `conv(prompt_cache_key) > affinity > 迟滞(PICK_HYSTERESIS,默认5点) > 最少使用者`,每一层都先过 `ok()`(dead/冷却/本轮已试过一律不粘,粘性永远挡不住 failover)。回退开关 `CRP_PICK_HYSTERESIS=0`。

**验证**:6+7 条不变量单测全绿;仿真 A/B(`scratch/picker_ab_20260809.py`,跑生产 `_pick` 本体)合计换号 H=0→78 · H=3→13 · H=5→6 · H=10→3;现场实证 —— 修复前 15 分钟窗口 98 个 POST 换号 4 次,修复后 61 个连续 POST 换号 **0** 次,2 个会话 6 请求跨号 **0**。

**★ 两条被本轮推翻的旧结论(别再照着它们推理)**:
1. ~~「实测 `cached_tokens` 恒 0,该端点没有 prompt cache 可失去」~~ —— **错**。全量 rollout 实测 `cached_input_tokens/input_tokens` 逐月 **95%~99%**(2026-03 至 08 全覆盖)。当年那次测量大概率只覆盖了会话首轮(首轮本就是 0)。
2. ~~「换号 ⇒ 冷缓存 ⇒ 整段历史全价重算 ⇒ 浪费额度」~~ —— **也错**(这是我在修复过程中推的,被用户当场纠正后实测证伪)。`total_tokens` **本就包含**缓存命中部分,冷启动改的是这些 token 的**价格**不是**数量**;订阅制下只有额度百分比、没有价格。按 token 对齐后 plus3/5/6 的缓存命中率 **92~98%**,与 pro1 的 95.3% 无差异 —— 切过去根本没冷启动。
   **「6 次请求比 139 次还贵」的真因是分母不同**:实测 **Pro 周预算 ≈1.85B token、Plus ≈250M,差 7~8 倍**。
   ⇒ **多号轮换在额度上是中性的**:它只决定"谁被扣",不决定"扣多少"。conv 粘性的价值是**可预测性**,不是省额度。

### B27 · 死机重启后开两个 CodexBar — 2026-08-11 ✅修 ★根因级

**症状**:脏关机重启后菜单栏出现两个 CodexBar 图标。平时手点复现不出来。

**根因**:**两条启动路径在开机时并发**——① autostart 插件建的 `~/Library/LaunchAgents/CodexBar.plist`(`RunAtLoad` + 直接 exec `…/Contents/MacOS/codexbar` **裸二进制**);② macOS 脏关机后由 LaunchServices 恢复。实测 app 已在跑时 `open -a CodexBar` **会**正确去重、只发 `Reopen`,但**那个去重要求第一个进程已在 LaunchServices 注册完毕**;开机时裸二进制还没注册完,恢复那条 `open` 就已经发出去了。去重不是原子的,于是漏过。修法不能指望 LaunchServices 的时序,只能落在 app 自己身上。

**✗ 弯路:`tauri-plugin-single-instance` 的闸门自己就有竞态**,而竞态恰恰是本 bug 的触发条件。读 2.4.x 源码:`connect 失败 → socket_cleanup() 删文件 → spawn 异步任务里再 bind`。两个进程同时启动时 B 的 connect 早于 A 的 bind,于是 B 也走进这个分支,**B 的 cleanup 把 A 刚建的 socket 删掉**,两边各自 bind、各自存活。用它做 GUI 压测"5/5 通过"只是没撞进那个窗口,不是没有窗口。

**修**:`flock(LOCK_EX | LOCK_NB)`,在 `tauri::Builder` **之前**(晚一步就会先把托盘和两个 webview 建出来再退出,开机瞬间照样闪两个图标)。内核级原子操作,两个进程同时抢**保证恰好一个拿到**;锁随 fd 由内核释放,`kill -9`/panic/断电重启都不留陈旧锁。锁文件放 app 数据目录**不放 `/tmp`**——`/tmp` 会被系统清理,文件一旦在持锁期间被删,新进程会在**另一个 inode** 上加锁,两个又都活了。

**★ 三态,不是二值**:`Acquired` / `HeldByOther`(退出) / `Undetermined`(**照常启动**)。只有 `EWOULDBLOCK` 才算"被别人占";打不开锁文件(HOME 缺失/磁盘满/权限异常)或该卷不支持 flock(`ENOTSUP`/`EINVAL`/`ENOLCK`)一律 fail-open。**把"判定不了"和"确实被占"合并成一个值,会让 app 静默地一个都起不来**——没有窗口、没有托盘、没有报错,比原 bug 严重得多。这是本仓库那条老规矩的同一形态:「这一枪没打中」绝不能和「确实没有」返回同一个值。

**验证**:flock 在本机 APFS 上 30 抢 1 恰好一个 · 改动前二进制并发拉起确实变成 2 个(缺陷复现) · 修复后真实二进制并发拉 3 个 ×3 轮均只活 1 个 · `kill -9` 后锁自动释放且冷启动正常 · 锁文件 `chmod 000` 时照常启动。**未验:真实脏关机重启**(需重启机器)。

**★ 一次无效对照的教训**:第一次 A/B 用 `cargo build --release` 产物做对照组,得出"程序坞图标是我引入的回归"。**结论是错的**——那条命令不开 `custom-protocol` feature,前端根本加载不起来。换成两个 `tauri build` 产物重测,有无插件都一样,即该现象改动前就存在。**对照组必须和实验组同一条构建命令。**

### B28 · 菜单栏刚自动刷新,进主界面又扫一遍 — 2026-08-11 ✅修

**根因**:两个 webview 各跑一份 `useTraffic`,却用**两套新鲜度标准**——主窗口 `revalidate:true`(进页面无条件重扫)、菜单栏 `revalidate:false`(超过 10 分钟才补扫)。两边渲染的是同一个 `.traffic-latest.json`,独立只可能产生分歧,而一次扫描要 ~1.4s CPU + stat 8500 个文件。

**修**:三层,缺一层还会重复。① 删掉 `revalidate`,两边共用同一条 `FRESH_MS`(挡"对方刚扫完");② 扫完 `emit("traffic-updated")`,对方**读盘**(~1ms)而不是重扫(两个 webview 是独立 JS 上下文,localStorage 都不互通,只能走 Tauri 事件);③ Rust 侧 `SCAN_LOCK` + 新鲜度双检(`SCAN_COALESCE_SECS = 90`),拿到锁后再看一眼快照岁数。**第③层不能省**:前端只能挡住"对方已经扫完",挡不住两边**同时**判定要扫。

**口径修正**:`CLAUDE.md` 里「新鲜度判断故意留在展示层,写进 Rust 会把两种策略焊死成一种」这句随之作废——策略仍在展示层,但**并发合并在 Rust**。

### B29 · 订阅续费成功,到期日永远不更新 — 2026-08-11 ✅修(我方部分)· ★真因在上游

**症状**:三个 plus 号已续费成功,CodexBar 仍显示「到期 2026-08-05 / 08-08 / 08-10」——全是过去时,而同一个界面的健康检查说这三个号**是活的**。

**真因(不在我们这边)**:`sub_until` 唯一来源是 id_token 的 `chatgpt_subscription_active_until`。同一命名空间里还有 **`chatgpt_subscription_last_checked`** —— **OpenAI 签发新 token 时不重新查计费系统,只把上次复核的订阅快照原样抄进新 JWT**。

实测:对两个非活跃号 `refresh --force` 刷出**全新** id_token(`iat` 就是当天 06:2x),里面的 `last_checked` 仍是 **11 天前的 07-30**,`active_until` 纹丝不动。**刷新拉不到新订阅状态,也没有办法强制它复核。** 对照组 pro1 的 `last_checked`(08-08)晚于其订阅起始日,所以它的日期是准的。`GET /codex/usage` 只回 `{rate_limit, plan_type, credits}`,没有订阅期。

**★ 但顺带查出我方两个缺陷,独立成立** —— 不修的话,OpenAI 哪天真复核了,你**照样看不到**:

1. `_refresh_slot` 拿到新 id_token 后写进 `tokens.id_token`、更新 `last_refresh`,却**从不调 `_stamp_identity`**。其余四条写槽位的路径(`_syncback` / add / autosync / 933)都调了,唯独刷新这条漏了。
2. 就算调了也存不下来:两个刷新调用点(手动 `refresh` / keepalive)为避免覆盖并发写入,**只做定向 RMW 回写 `last_refresh` 一个字段**,`_stamp_identity` 写进内存 `slot` 的 email/plan/sub_until 全被丢弃。抽成 `_refresh_patch(slot)` 一并落盘 —— **两处形状完全相同,各写一份迟早只改一处**。

⇒ 在此之前,**刷新从来没有把任何身份变化写进 `state.json`**;订阅续费、Plus→Pro 升级都一样刷不进来。新增 `sub_checked` 字段(进 `IDENT_FIELDS`)让 UI 能区分「真的过期」和「快照太旧」。

**教训**:同一个字段有五条写入路径时,漏掉的那条不会报错,只会安静地永远不更新。加字段时 `grep` 全部写入点,别只改你正在看的那条。

3. **未定**:额度计量到底算不算缓存命中的 token。方向性证据(n=3,Δ% 只有 2~3,整数量化 ±50%)是「每 1% 对应的 **total**」离散 1.5 倍 vs「对应的**未命中**」离散 6.6 倍 ⇒ 更像按 total 计。已加 `state.json.quota_marks`(跨整数百分点时记 `{aid,t,from,to}`,上界 400)攒每请求级样本。**有结论前别用"省缓存=省额度"做决策。**

---

### B30 · Codex token 统计虚高,自 v0.7.0 起一直显示在界面上 — 2026-08-12 ✅修

**症状**:消耗页的 Codex 数字系统性偏高,且**少量抽查看不出来** —— 重复呈重尾,单个文件就贡献了全部重复量的 38%。

**根因**:`_scan_codex_file` 原来直接把每条 `token_count` 事件的增量求和,而 codex 会把**同一个 `token_count` 事件成对重复写入** rollout。旧注释「codex 实测均无重复,不需要去重」正是据此写下的,**该结论作废**。

**修法**:按累计值 `total_token_usage.total_tokens` 去重 —— **不按内容哈希**(两轮恰好用掉一样多 token 是常事);取不到累计值时**保留该条**(fail-open)。旁证:去重后「Σ增量 == 最终累计」181/181 零例外。

**★ 倍数离开窗口就没有意义**(重尾所致,别引用单一数字)。测法是拿 git 里的**旧解析器与新解析器各跑一遍真代码**,不是另写一个「朴素求和」来对比 —— 后者测出来是 2.73x,错的:

| 窗口 | 旧/新 | Codex 下调 |
|---|---|---|
| 全量 3619 个 rollout(含历史) | 1.421 | −29.6% |
| **90 天(app 实际显示的档)** | **1.069** | **−6.5%** |
| 早先 300 个抽样 | 1.124 | −11% |

**教训**:`SOURCES` 里 codex 的 `dedup: False` 只是说**跨文件**不合并,不代表文件内没有重复 —— 两个概念用了同一个词,旧注释就是这么写偏的。

### B31 · 每天 00:00–00:59 两个图表整块空白 — 2026-08-13 ✅修

**症状**：过了午夜、当天只有一个小时桶时，菜单栏「今日」小时图与主窗「今日」档**整块空白**，SVG 仍占满高度。

**根因**：一条堆叠带至少要两个采样点。`MenuBarToday.area()` 在 `vals.length < 2` 时直接 `return ""`；`StackedArea.bandPath()` 产出 `M x y L x y Z`（零面积）。实测 6 层 path 的 `d` 全是空串。

**修法**：单个采样点画成**柱**。不补成横跨全宽的面积 —— 那会把「这一个小时」画成一整天。

---

### B32 · MiMo 费用恒显示 $0.000 — 2026-08-15 ✅修

**症状**：MiMo 102M token，费用列一直是 `$0.000`，且没有任何「未定价」提示。

**根因**：`rates.ts` 的 `FALLBACK` 里**没有 mimo/deepseek 档**，`priceOf` 返回 `{0,0,0}`。**「真的没花钱」和「我不知道多少钱」显示成了同一个值。**

**修法**：补齐两档并标 `est`。真价 $32.78。

---

### B33 · Codex / Kimi 费用被严重低估 — 2026-08-15 ✅修

**症状**：本机实际在跑的 `gpt-5.6-sol` / `gpt-5.5` / `kimi-code/k3` **都不在费率表里**，全走兜底价。

**根因**：兜底价是旧型号的（codex $1.75/$14，kimi 是明确标注的占位数 $0.6/$2.5）。实测 Codex 低估 **2.61x**、Kimi 低估 **5.09x**。

**修法**：按各家官网重取（2026-08-15），逐个登记真实型号。

---

### B34 · 未登记平台的图表整片变灰 — 2026-08-15 ✅修

**症状**：MiMo / DeepSeek 的详情页「总量」档整张图是灰的。

**根因**：`PlatformPage` 取平台色用 `platformColor(pk)`，只查 `theme.ts` 静态表；这两家不在表里 ⇒ 兜底灰 `#5b6472`，而总量档整张图就是这一个色。**绕过了 scan 下发色与用户设置色。** 分模型档用 `modelColor()` 散列，所以一直没暴露。

**修法**：改走 `colorOf(data, pk)`（已把用户偏好折进 `platforms[k].color`）。

---

### B35 · 浮层被自动刷新弄脏，会描述另一天 — 2026-08-15 ✅修

**症状**：停着的图表浮层，过一段时间后描述的不再是鼠标所指那天。

**根因**：`StackedArea` 的 `key` 只有档位，不含数据身份。`useTraffic` 每 2 分钟**原地换 labels/layers 不换实例**，而日线档窗口是「截止今天的连续 N 天」，**一过午夜整窗滑一格**。组件内的钳位只防越界，滑动后索引仍在范围内，一个字都拦不住。

**修法**：`key` 带 `labels[0]`。用它而不是 `labels.length` —— 今日档按小时**追加**，长度变但索引不移位，不该因此丢 hover。

### B36 · `codex resume` 的会话烧完一个号就停，自动切号救不了 — 2026-09-07 ✅修

**症状**：用户报「开了自动切号，CLI 跑一半还是额度过了，然后停止，我还得结束会话重新开启新的会话才能用」。

**排查路上被证据否掉的四个假设**（都写出来，免得有人再走一遍）：

1. 「池子耗尽、代理返 503」—— `no usable account` 日志里**零次**（`grep -c 503` 得 125 是 hex id 子串，假阳性）。
2. 「用户在用 resume 绕过代理」—— 当天 280 轮里 272 轮走了代理（97%）。★ 这个论证**本身是错的**：全天总数比证明不了某个**具体会话**走没走代理，是 codex 评审指出来的。
3. 「SSE 流内错误事件」—— 当天全部 rollout 里 `error/stream_error/turn_failed/...` **零条**。
4. 「会话粘性钉死在耗尽的号」—— `_pick` 的 `conv` 分支确实先过 `ok()`。

**真因（两层，缺一层都解释不通）**：

① codex 有一条 **WebSocket 响应通道** `codex_api::endpoint::responses_websocket`，它**硬编码 `wss://chatgpt.com/backend-api/codex/responses`、不认 `base_url`**。实测 `~/.codex/logs_2.sqlite`：近 3 天 **124 次 WS 连接，124 次全部直连公网、0 次到 127.0.0.1:8011**；抽样 10 个 WS thread，**8 个 provider 写着 `rotateproxy`**。这些 turn 从没经过代理 ⇒ 没有轮换，只烧 `auth.json` 那一个号。近 7 天 `You've hit your usage limit` **29 次**。

② 关掉它的开关是 provider 的 `supports_websockets`（闸在 `client.rs::responses_websocket_enabled()`：`if !info().supports_websockets { return false }`），但**内置 provider 把它硬编码成 `true` 且不可覆盖** —— `merge_configured_model_providers` 对非 Bedrock 的 key 用 `entry(key).or_insert(provider)`，内置 id（`openai`/`ollama`/`lmstudio`/`bedrock*`）配了也被忽略。

⇒ **「不走代理」本身就等于「WS 必开」**。而 `cxp` 自 B37 那次改动起把 `resume`/`fork` 排除在代理之外，两者叠加就是「resume 会话钉死一个号、烧完即停」。

**修法**：`cxp` 恢复成**所有子命令一律 `--profile rotateproxy`**（即 2026-06-13 之前的原始形态）。`[model_providers.rotateproxy]` 上的 `supports_websockets = false` 于是生效，轮换与关 WS 一并解决。

**⚠️ 一个被自己的注释误导的教训**：`cxp` 里那段解释 resume 例外的注释被我当成了不可动的设计约束、反复引用。**一条 `git log -S 'resume|fork' -- proxy/cxp` 就能看到它是三个月前的一次权衡，附带当时的实测数据（89 个 openai 会话 vs 1 个 rotateproxy）**，而那个数据早已过期（2026-09-07 实测：最近 50 个里 rotateproxy 占 **76%**）。本仓自己的优先级规则是「代码 > 带实测数据的 CHANGELOG 结论 > 文档」，我没按它做。

### B37 · 换默认 provider id 让 `codex resume` 列表**直接清空** — 2026-09-07 ✅已回滚

**症状**：用户报「不是列表变短了，是直接没有了」。

**根因**：为绕开上面那条「内置 provider 不可覆盖」，我新建了一个 `openai-nows` provider 当默认、只关 WS 不走代理。但 resume picker 按 provider **逐字**过滤：

```rust
fn matches(&self, session_provider: Option<&str>) -> bool {
    match session_provider {
        Some(provider) => self.filters.iter().any(|c| c == provider),
        None => self.matches_default_provider,
    }
}
```

filters = `[当前默认 provider]`，而**存量会话没有一个带 `openai-nows` 戳记** ⇒ 匹配数必然 0 ⇒ 列表空。

**⚠️ 教训**：我读到了正确的源码，却**没把它的后果算到底** —— 还把它说成「列表会变短」。换 provider id 就等于清空 picker，**别再试这个方向**。

**已回滚**：`~/.codex/config.toml` 恢复（备份 `config.toml.bak-20260907-152043`）。改动留档 `/tmp/cfg-nows-keep.toml`。

★ 顺带记下两个**验证**层面的坑：
- 第一次「验证配置是否生效」我塞了个虚构键 `zzz_bogus_key_probe`，**codex 也不报错** ⇒ 它对未知配置键静默忽略，「没报错」什么都证明不了。真正有判别力的对照是**写一个不存在的 provider id**，那会报 `Model provider not found`。
- 第二次用 `codex exec` 验「WS 是否还发生」，实验组 0 条 —— 但**对照组（内置 provider）也是 0** ⇒ `exec` 这条路本来就不用 WS，测试**两边都没有判别力**。WS 只在交互式会话里发生（331 条记录 / 69 个进程，其中 30 个有 TUI 日志，`exec` 一条都没有）。

### B38 · codex 升 0.154 后「本地工具全废」，真因是 `cxp` 给每个子命令都塞 `--profile` — 2026-09-08 ✅修

**症状**：用户报「甚至现在 codex 的本地工具都用不了了」。`codex resume` / `codex exec` / 裸 `codex` **完全正常**，
但 `codex doctor` / `update` / `plugin` / `features` / `completion` / `apply` / `agents` 一句话就死。

**根因不在本仓，在上游**：npm 的 `@openai/codex` 当天 12:02 自动升到 **0.154.0-alpha.6**，
0.154 起对非运行时子命令带 `--profile` 从「静默忽略」改成**硬报错**：

```
Error: --profile only applies to runtime commands and `codex mcp`: `codex`, `codex exec`,
`codex review`, `codex resume`, `codex queue`, `codex archive`, `codex delete`,
`codex unarchive`, `codex fork`, `codex mcp`, `codex sandbox`, and `codex debug prompt-input`.
```

而 `alias codex=cxp` 对**每一个**子命令无条件注入 profile。运行时那半不受影响，所以症状恰好是
「会话能开、工具全废」—— 极易误判成本仓的 resume 改动弄坏了什么。

**修法**：`proxy/cxp` 按子命令决定是否注入。**必须是黑名单不是白名单** —— 白名单会把裸 prompt
（`codex 修一下这个 bug`，首个非选项 token 是 `修一下这个 bug`）判成「未知子命令」而丢掉 profile，
等于**静默退回单号直连、不轮换**；那个方向的失败不出声，比报错危险。

**★ 一个让你以为没事的坑**：`codex <sub> --help` 探不出这个 —— clap 在 `--help` 上短路，
profile 校验根本没跑到，**26 个子命令会全绿**。我第一轮扫描就是这么扫出「全部 ok」的，与事实相反。

**✅ 顺带堵上一个空守卫**：profile 曾恒占 `$1`，而 PATH wrapper 的拦截写的是 `[ "$1" = "logout" ]` ——
那条「`codex logout` 会在服务端 revoke 当前号」的守卫**一直没生效**。去掉 profile 后才真命中。

**闸**：`tests/test_cxp_profile_scope.py`（11 tests / 27 subtests，用 PATH stub 打印真实 argv；
已变异验证：把黑名单改成永不命中 ⇒ 21 红，还原 ⇒ 全绿）。

---

### B39 · 打补丁的 codex 二进制炸掉**全部工具调用**，而 `codex doctor` 全绿 — 2026-09-08 ✅弃案

**症状**：`codex exec` 里模型一个工具都调不动。`codex doctor` 全绿、`config.toml parse ok`、
auth ok、MCP 8 个都在 —— **没有任何「配置坏了」的迹象**，于是第一反应去翻配置，白查一轮。

**真因**（只有真跑一次 `codex exec` 看 stderr 才拿得到）：

```
OpenAI Codex v0.153.4+codexbar.1
ERROR codex_core::tools::router: error=failed to spawn code-mode host
  …/native-codex/codex-code-mode-host: No such file or directory (os error 2)
```

codex 按**自己可执行文件的同级目录**解析辅助进程。官方 vendor 是 4 件套
（`codex` / `codex-code-mode-host` / `codex-resources/` / `codex-path/`），而
`scripts/native-resume/build.py` 只 `shutil.copy2` 了 `codex` 一个文件 ⇒ **残缺安装**。
`code_mode_host` 是 stable/enabled，spawn 不到就 **fail closed**。

**★ 判据教训**：`codex features list` 的第三列是**默认值不是有效值**（`--disable X` 之后仍显示 `true`）。
我一度据此推断 `unified_exec = false` 是元凶 —— **方向完全相反**。

**处置：整条路弃案**（用户拍板：「不要弄补丁的，改为官方版」，理由是它挡后续官方版更新）。
除 ① 之外还有两条独立理由：② 补丁对 0.153.4 而 npm 已到 0.154，`codex update` 更新 npm 那份、
跑的却是被钉住的补丁，**无声**越差越远；③ 每次官方发版都要重 apply + 重编 + 重验。

`proxy/cxp` 现在**只有一条 `exec command codex`**。闸 `tests/test_resume_routing.py::NoPatchedBinaryEntry`。
二进制归档 `~/archive/codex-account-rotator/native-codex-dropped-20260908/`；`scripts/native-resume/` 仅存档。
⚠️ 拆补丁时我把 `CODEX_ROTATE_STORE` 也一起删了 —— 它是**全仓统一的数据目录变量**，不是补丁残留。
闸里现在**断言它必须在**。

---

### B40 · 「rotateproxy 占比只增不减」是错的 — 2026-09-08 ✅已改正文档

B36 修 B 系列老注释（89:1 过期三个月）时，我写下的替代数据「实测 2026-09-07，最近 50 个里
rotateproxy 占 **76%**、最近 500 个占 64%、往后只增不减」**本身就是错的**。

**2026-09-08 只读复核**（picker 口径 `archived=0` + `has_user_event=1` + `source in ('cli','vscode')`）：

| provider | 总量 | picker 可见 |
|---|---|---|
| `openai` | 2677 | **238** |
| `rotateproxy` | 1553（其中 1344 是 `codex exec`） | **2** |

最近 50 条里 rotateproxy 只有 2 条；**2026-08 及以前每月都是 0**。

**两个都能解释同一份数据的假说，分不干净，别当已知事实用**：① wrapper 里那个已删的
`repair_codex_session_visibility()` 一直在把 DB 的 rotateproxy 改写成 openai（238 这个数
基本就是它的产物）；② 69 条 VS Code 会话那条路根本不经过 cxp。
**可确认的只有**：repair 移除后新交互会话稳稳戳 rotateproxy（当天 14:22 / 14:30 两条已验），
所以 238 是**存量、不再增长**。
✅ 删 repair 不伤官方 picker：openai 的 cli / vscode 会话**自然带 `has_user_event` 的比例是 98.3% / 94.2%**。

**★ 这条错误是「结论要带证据和日期」那条规矩的最好例证** —— 它带了日期，所以才被查出来。
规矩管不住写错，只管得住「错了没人发现」。

---

### 定稿 · 两条入口的会话列表分裂**不统一** — 2026-09-08

用户问「能不能让 `codex resume` 同时看到 2 + 238」。**答案：不能（无补丁），且这是终态。**

| 入口 | provider | 行为 | picker 里能看到 |
|---|---|---|---|
| `codex`（alias→cxp） | `rotateproxy` | 逐请求轮换、WS 关 | 新会话（持续累积） |
| `\codex` / `cx` | `openai`（内置） | 单号直连，`/usage` 有意义 | 238 条存量档案 |

**用户主动选择保持分裂**，理由是**「需要单号入口跑 `/usage` 看重置卡」** —— 走代理时每个请求
可能落在不同号上，那个数就没意义了。技术上**能**统一（profile 与 provider 解耦，两个 profile 可指向
同一个 `model_provider`；`env_http_headers` 在 0.154 二进制里确实存在，可让单号入口也走代理但按 header
钉号），**用户否了**。

**「让一个 picker 同时列两个 provider」= 不可能（0.154 实测）**：
- 真渲染实测（`scratch/picker_render_probe.py`）：cxp `1 / 5`；官方 `1 / 25` → `1 / 75` 仍在加载。
  picker 顶栏筛选器只有 `Cwd / Status / Sort`，**没有 provider 这一维**。
- SQL 仍是 ` AND threads.model_provider IN (`；二进制里所有含 `provider` 的键都列过一遍，
  唯一沾边的 `allow_provider_model_fallback` 是选模型不是选列表。
- `--all` 只解 cwd；0.154 新增的 `--include-non-interactive` 只解 `has_user_event`。
- 仍不能把自建 provider 命名为 `openai`：`model_providers contains reserved built-in provider IDs:`。

**⚠️ 探针陷阱**：pty 不设窗口大小（`TIOCSWINSZ`）时 TUI 什么都不画，**和「列表真的是空的」长得一模一样**。
我第一次就得到了「两边都 0 条」的假结论。探针与坑留在 `scratch/picker_render_probe.py` 文件头。

---

### B41 · 接入「中转站」路由 + 分账 + agy 额度实时（Phase 0–5） — 2026-09-09 ✅

用户要在 CodexBar 里接第三方 OpenAI 协议中转站：监控用量 · 人工增改 key/base_url ·
一键把 codex 切过去。用户明确**接受**"多一个 provider = 多一份、且一开始为空的 resume 列表"。

**★★ 实测单次成本 $0.0863**（一句 `reply with exactly RELAY_OK`，tokens used 39,513 ——
系统提示 + 工具定义就这么大，prompt 多短都没用）。我事前估 $0.001，**差 86 倍**。

**Phase 0/1（引擎 + 路由）**
`relay/store.py` 托管区标记（codex **也往 profile overlay 回写** 12 行 hooks 信任哈希 /
项目信任 / NUX 计数器 —— 整文件覆盖会抹掉）· `relay/relay-key` 走 `auth.command`
（`env_key` 下中转站回 401 会让 codex **去刷账号池 active 号的 refresh_token** 并喊
"log out and sign in again"，而 `codex logout` 在本仓是杀号）· 六态路由 ·
`cxp` 读路由 + **profile 文件硬检查**（codex 对缺失**不报错**、静默退回 base 配置 ——
闸必须在 exec 那一刻，不能只在 UI）· `health` 的 `relay_route_gate()`。

**★ 三重核验的真实计费实验**：`provider: tokendun` → `RELAY_OK`；10:20 后走账号池的
`POST /responses` = **0 条**；中转站 `today.requests` 0→1；新会话戳记 `provider=tokendun`。
**tokendun 确实支持 `/v1/responses`** —— 这是唯一只能靠真请求回答的未知量。
⚠️ 判据我第一次也判错了：数 proxy.log **总行数**，多出的 4 行其实是 `GET /models`（免费、
且早于那次 exec）。换成数 `POST /responses` 才有判别力。

**Phase 2（CLI + Rust + 打包）**
`relay-ctl`（key 走 **stdin 不走 argv**、退出码恒 0、payload 只出指纹）· 3 个 Rust 命令
（NET/STORE 两把锁 —— 一把的话中转站不可达时 25–100s 的网络调用会堵住"保存"，
而那**恰恰是用户最想改配置的时刻**）· 打包清单 + `test_bundled_scripts.py`
（从 `lib.rs` 正则解析所有 `script_dir()` 引用，09-05 同款事故的闸）。
★ `command` 是**可执行文件路径不是 shell 字符串**，参数必须走 `args = [...]`；
写错时报 `failed to start: No such file or directory` —— **看起来像脚本不存在**，而路径完全正确。

**Phase 3（RelayPage）**
六态路由卡（每个非正常态都含可执行动作 + 生效范围声明）· 两个成本口径**分列**
（`cost` 牌价 / `actual_cost` 实扣，实测差 3.85 倍）· 日实扣柱状（稀疏离散用柱不用面积）·
模型表 · 表单（key `type=password`、编辑留空=沿用）· **「切到此中转站」是全 app 第二个
花钱控件**（第一个是 ProbeButton），两段确认 + 💰按量付费角标。

**Phase 4（分账，消除双重计价）**
经中转站的会话**照样写 rollout**，那批 token 既进「AI用量」的 Codex 桶（按 OpenAI 牌价折算的
**等效**成本），又在中转站**真金实扣过一次** —— 同一批 token 以两个价出现在两页上。
`_scan_codex_file` 按 ordinal 跟踪 `cur_provider`（**一份 rollout 可有两条 `session_meta`**）·
row 加第 8 位 · `PARSER_V` 8→9 · `by_provider` **旁挂，总量一个字节不动** ·
`PlatformPage` 加路由行 + 费用口径脚注。
**★★ 跨源对账**：`by_provider.tokendun.total` 与中转站 `/usage` 的 `today.total_tokens`
**逐 token 相等（39,513 = 39,513，0.00%）** —— 两个完全独立的来源。
⚠️ 我第一版把累加放在窗口判断**之前** ⇒ `days` 119M 而 `by_provider` 9,004M。
**同一页上的两个数必须同窗口。**

**Phase 5（agy 额度实时）**
改之前是**两个独立轮询者**打同一个 RPC，而 app 那条**只在有人看着那一页时才前进**
（切走再回来最坏等 2.5 分钟，两个 webview 各看各的）。现在：采样器是**唯一抓取者兼唯一写者**
（同一份响应写账本 + sidecar，带 `--prev` 让 last_good 跨进程连续）· Rust 1s 循环看 mtime →
`emit("agy-quota-updated")` · 前端监听后**只读 sidecar 不发 RPC、不受 `enabled` 约束** ·
跨重置立刻取 · app 在锁文件不存在时**补拉采样器**（从 IDE/VS Code 起的 agy 没有 wrapper ⇒
原本根本没有采样器，而 UI 只知道"数据旧了"，看不出"没人在采"）。

**★★★ 我先写错了一条结论，已更正（留档防再犯）**
我写的是「agy 不在任何地方落 token 计数」，依据是"扫遍 261 个 db 只有 3 处命中"。
**那是假阴性**：`gen_metadata.data` 是 **protobuf wire format，里面根本没有字段名**，
`grep promptTokenCount` 永远 0 命中 —— **用一个看不见目标的探针得出"目标不存在"**。
盲解后逐条比对 69 个 conv：`f5`=cache_read **69/69**、`f9`=thinking **69/69**、
`f2`/`f3` 63/69，`f1.f19`=模型名。=>「agy 交互式 token 永久拿不到」**被推翻**；
另有 192 个 db、约 **2.59 亿 token** 可追溯回收（覆盖率 15.9% -> ~100%，不依赖 wrapper）。
**尚未接入**，Phase 5 本身只做了额度% 的实时化。

**★★ Phase 5 我还亲手造了一个永续空转**（Fable 抓到）：agy 没在跑时 app 每 60s 补拉采样器，
它快轮询 90s、**每次失败的 fetch 照样写 sidecar** => 广播 => 两个 webview 各读一次，
**每 ~4.5 分钟约 40 次 python 起停**。已两道堵住（起手探活 0.00s 退出 + 写前比内容，
**比较时剔掉每次都变的 `fetched_at`/`pid`**）。

**测试**：全量 **751 passed / 397 subtests**（本批新增 ~120 条）。
每个 Phase 都做了变异验证；**其中三轮各抓到我自己一个空守卫**：
① 「页面不许渲染完整 key」——夹具里根本没有完整 key（已加诱饵 `sk-DECOY-…`）；
② 「路由行存在」——断言的字符串在**组件定义**里，删掉调用点照样绿（已补调用点断言 + 真 DOM 闸）；
③ `auth_command`/`auth_args` 进比对——前面几条其实都被"文件存在性"抓到的（已补 2 条）。

### v1.5.0 — 2026-09-10

**新增** · 中转站页按设计稿重建：「当前出口」两张同权卡（一眼看出走哪条路）、中转站表格
（操作收进 `✓`/`···` 图标）、用量改为**每模型一张小图卡**（每卡独立 y 轴 + 走势线 + 峰值/实扣），
新增**按站筛选**与**聚焦**（点卡片其余变暗）。

**改进** · agy 时间戳改用 `last_step_index` **精确 join**（原为序数猜测，实测 4.4% 拿的是别人的
时间戳）· agy 的 7 个模型登记专属颜色（原来散列撞了 3 对，两条同色的带子在图上是一条）·
中转站泳道有了自己的失败计数器 · 同一个 sidecar 的多个实例共享一次取数（原来各起一次 python、
各打一次外网，两块最多差 5 分钟）· 改完中转站配置立刻重取用量。

**修复** · **中转站 api key 的两个泄漏面**：`urllib` 跟随重定向时原样带上 `Authorization`
（对端一句 302 就能把 key 骗走）、临时文件在 chmod 之前有个 0644 窗口 · 远端明文 http 一律拒发 ·
指纹不再露明文尾巴 · **数据目录脑裂**：`proxy.py` 认 `CODEX_ROTATE_STORE`，且两个安装器
**每个任务**都注入它（此前一个都没带，CI 装的包上 app 与服务会用两个目录，两把跨进程锁因此失效）·
环比拿子集当上期（实测显示过 ↑148757.6%）· 档位按「有数据的天」切导致日均虚高 3.3× ·
读失败被缓存成「0 token」· 截断的 protobuf varint 交出一个假数 · 币种读不到时默认 `$`、
多币种直接相加 · 页头显示刷新时刻而下面全是旧数据 · 登记表损坏会抹掉整份用量历史 ·
"只删我们写的"删掉了整个文件 · 逐日模型明细冻结半天数据 / 预算永远轮不到今天 / 对端挂掉时
最坏占用网络锁 17 分钟 · 切到已停用的中转站显示「未知错误」· `launchctl bootout` 的竞态会把
服务留在停用状态。

⚠️ **升级后 `.traffic-cache.json` 会全量重解析一次**（`PARSER_V` 10 → 11），首次扫描慢几十秒。
⚠️ 中转站表单的「模型」输入框**已去掉** —— 它从来没有生效过（代理不读它），
`relays.local.json` 里的键保留，老配置不受影响。

详见 B42。

### B42 · 评审驱动的一整轮：P0/P1/P2 清零 + 中转站页按设计稿重做 — 2026-09-10 ✅

Fable 评审 40 条 + 四方评审 9 条，全部处理完。17 个 commit 未发版（见「已知待办」）。

**★★★ 安全（两条，都不出声）**

① **`urllib` 跟随重定向时原样带上 `Authorization`**（只剥 Content-\* 头）。中转站回一句
`302 Location: https://别人家/`，按量付费的 key 就送出去了，而调用方只看到 200 ——
不需要对端有恶意，一个被接管的域名就够。`monitor._get` 改走自建 `_OPENER` +
`_SameOriginRedirect`：**跨源直接拒绝**，不是"跟过去但删 header"（后者拿到的响应与
「key 失效」长得一模一样，把安全事件伪装成凭证问题）。同源判据**带端口**。
② **`_atomic_write` 有个 0644 窗口**：`Path.write_text` 按 umask 建文件、之后才 chmod 0600，
其间这份含明文 key 的临时文件全局可读。原 docstring 承诺的「chmod 要在 rename 之前」
是对的也做到了，但它挡的是 rename 之后的窗口 —— **一条只覆盖一半的规则读起来和覆盖全部一样**。
改用 `os.open(O_CREAT|O_EXCL, 0600)`。
③ 顺带：`fingerprint()` 原来露首 7 + 尾 3 明文 + sha256 前 12 位。那 12 位是个 **48 bit 验证
预言机**，配上 10 个明文字符，一把 18 字符的 key 只剩 8 个未知位。尾巴是多余的那份（哈希已经
能区分同前缀的两把），已去掉；前缀跟长度收缩。
④ `store.validate` 只校验「是不是 http(s) 开头」，**远端明文 http 一路放行**，而
`proxy.py::_relay_upstream()` 一直要求 https —— 同一条规则三处实现，宽的说了算。
现在配置侧与发送侧都只放行 https 或**回环** http（自建 one-api 跑 127.0.0.1 是正常用法）。

**★★ 数据目录脑裂（critical，本机永远看不见）**

`proxy.py` 的 `STORE` 是全仓第 9 个入口里**唯一**不认 `CODEX_ROTATE_STORE` 的。
更要命的是**改完之后没人喂它**：`install-launchd.sh` 与 `install-windows.ps1` 的**四个任务
一个都没带这个变量**，而 `grep proxy.py lib.rs` **零命中**（app 根本不 spawn 代理）。
本机看不出来，是因为 `deploy.sh` 把仓库路径烧进 `CODEXBAR_STORE_DEFAULT`，于是 app 与服务
碰巧同一个目录；CI 出的安装包没有那个烧录值 ⇒ `route.local.json` / `state.json` / `auth/` 全部分叉，
且 `.refresh.lock` / `.state.lock` 落在两个路径上 = **等于没有锁**，两侧会同时刷同一个号的
一次性 refresh_token。两个安装器现在按 Rust `store_dir()` 同一条优先级链注入**每个**任务；
`proxy.py` 在 `__main__` 里建目录 + 打 `store=` + `state.json` 缺失时 exit 78。

⚠️ **`launchctl bootout` 是异步的**，紧跟的 `bootstrap` 撞 `Bootstrap failed: 5: I/O error`；
配合 `set -e`，脚本停在那一行 —— 该服务已 bootout、未 bootstrap，**就那么停着**（本轮 quotad
真停了），后面的任务连 plist 都没重写。`emit` 已改成轮询等它消失 + 重试 + **按"真的加载上"判**。

**★ 数字说谎（六条）**

- 环比 `slice(max(0,len-2n), len-n)`：`len-n` 为负时 JS 把负数 end 当**从尾部倒数**
  ⇒ "上一窗口"落在当前窗口**内部**（拿总量和自己的子集比）。实测真快照 7d 档「环比 ↑148757.6%」。
  现在按自然日回退等长窗口 + 零交集 + **整段可观测**三条。
- 档位按「最近 N 个**有数据**的日子」切，而中转站 `daily` 只含有请求的日子 ⇒ 7d 档实测跨了
  **23 个自然日**、页面却标 7d，「日均」虚高 **3.3×**。改成自然日补零。
- `_scan_agy_db` 读失败返回 `[]`，而 `scan()` 把结果**连同签名一起写进缓存** ⇒ 一次瞬时失败
  （sqlite 被锁、2s 超时）把该会话**永久固化成 0 token**。改为抛 `ScanReadError`，缓存保留旧值
  **连同旧签名**（好让下轮重试），并在 stats 里报 `read_failed`。
- `_pb` 的 varint 截断时交出**部分值**：`b"\x08\xff\xff"` → `f1=16383`，一个长得完全像 token
  数的数字，而这些库正在被写入。另有无位宽上限（20×0xff → ~2.8e42）与长度前缀越界
  （python 切片静默截断，调用方当成完整嵌套消息解）。三处都改成停止解析。
- `money()` 在币种读不到时打 `$`，与 `monitor.py` 明写的「读不到就 None，不许默认 USD」直接矛盾
  （国内中转站不少按 CNY 或额度计）。KPI 还把多家的钱**直接相加**、币种取第一家 ⇒ 一家 USD
  一家 CNY 时那个数**不属于任何货币**。现在 `currencyOf()` 把 `null` 也当一类，混币显 `—`。
- 页头 `↻ 上次刷新` 直接渲染 `fetched_at`，而 `collect()` **取失败也写**它 ⇒ 整屏都是旧数据时
  页头照样显示当前时刻，与正下方的 stale 横幅互相矛盾。改成三态（全新/部分旧/全旧）。

**★ 只增不减 / 只删自己的**

- `collect()` 只遍历登记表 ⇒ `relays.local.json` 损坏时快照里零个中转站，**已滑出上游窗口的
  日子永久消失**。现在按 `store_corrupt` 判据把上一份里的中转站带过来标 `registry_corrupt`
  （用户**真的删掉**的仍然消失 —— 判据是"登记表坏了"，不是"这个 id 不在表里"）。
- `cleanup` / `remove()` 命中托管标记就 `unlink()` **整个文件**，把用户写在我们那段前后的内容
  一并删掉。两处各写了一份判据所以同时错，现在合成 `store.drop_managed_profile()`，
  三态返回 `removed` / `stripped` / `kept`。

**★ 逐日模型明细（三条）**

「历史日不可变」被套在**当时还是今天**抓的那份上，一旦它变成历史日就永久冻结 ⇒ 同一天里
按模型加起来 ≠ 总量。现在打 `models_partial` 标记、变成历史日后重取一次，`merge_daily`
**连标记一起搬**。`MAX_DAY_FETCH=40` 的预算按日期升序从**最老**的花，今天永远排在预算之外
（而今天是唯一每轮都在变的）—— 改成今天优先。对端整个挂掉时没有熔断，最坏 41×25s ≈ **17 分钟**
占着网络锁，UI 上表现为"刷新键点了没反应" —— 连续失败 3 次停手。

**★ agy 时间戳精确 join（PARSER_V 10 → 11）**

原来是「第 k 个 `step_type=15` ↔ 第 k 条 gen_metadata」，一个**猜测**。实测 263 库 3758 条：
`gen.f1.f20` 是一串 kv，其中有 `last_step_index`，而 `last_step_index + 1` 落在一个
`step_type=15` 上的比例是 **3758/3758 = 100%**，时间戳也 100% 解得出；与序数猜测
**有 164 条（4.4%）不一致** —— 那 4.4% 拿的是别人的时间戳，足以把用量记到错的日子。
序数猜测保留为兜底。⚠️ **这条我探错了两次**：`inner.get(20)` 是 bytes 不是 int（用
`isinstance(v[0], int)` 过滤数出 0 条，差点判"字段不存在"）；且 f20 是**重复字段**，
只取 `[0]` 拿到的是 `request_id`。★ PARSER_V 一变，`.traffic-cache.json` 会全量重解析一次。

**★ agy 模型撞色**

7 个 agy 模型 id 全部落进散列兜底，10 色盘上**撞了 3 对**，撞的恰好是最需要区分的
（`gemini-3.7-flash` vs `-tiered`、`gemini-3.8-flash` vs `gemini-3.6-flash-tiered`、
`gemini-pro-c` vs `gemini-3.1-pro-low`）。两条同色的带子在堆叠图上是一条，**不报任何错**
（`assign_colors` 早为泳道加了线性探测，`modelColor` 这侧没有）。散列兜底本身没错，
错在**同时在场**的模型一多必然撞（7 进 10 撞车概率近 9 成）。agy 的模型集合可枚举，已手工登记。

**★ 中转站泳道的计数器分家**

`stream_aborts` / `committed_aborts` 的**存在理由**是量化账号池那条路上的**双计费**
（有 failover ⇒ 同一次生成可能被两个号各计一次费）。中转站单上游、没有 failover，
一次断流的含义完全不同。混在一个键：账号池的指标被稀释，中转站自己的失败率无处可查。
改为 `relay_stream_aborts`。

**★ 两处过期的因果（改结论容易，改**理由**才要紧）**

- `route_corrupt` 的 detail 写着「cxp 会直接 exit 78，codex 一条都跑不起来」——「一个 provider，
  两种上游」定稿后 `cxp` **根本不读** `route.local.json`。真实后果是代理**退回账号池**：
  codex 照常跑，但用户选的按量付费被无声忽略、扣的是订阅额度。**照着过期理由做判断，
  下次会诊断到错误的组件上。**
- 「生效范围」把 **VS Code** 列在"走本地代理"一侧，实测不成立：扩展自带 codex 二进制、
  从 `extensionUri` 拼路径启动、**根本不查 PATH**（唯一覆盖项 `chatgpt.cliExecutable` 自标
  "DEVELOPMENT ONLY"、默认 null）；且它跑的是 `app-server`，而 `app-server` 在
  `codex-profile-scope.sh` 的黑名单里。两条独立理由任一条成立就够。
  ⚠️ 2026-09-09 的 B41 与 memory.md 都写过「四个入口已统一，含 VS Code」—— **那句是错的**。

**★★ 中转站页按 `design_handoff_codexbar/中转站-交接说明.md` 1:1 重做**

- **账号 Tab**：`当前出口` 两张同权卡（46px 环 + `在用` 角标 + `✓当前`/`切到…`）→ 生效范围 →
  中转站**表格**（站点 / endpoint·key / 余额 / 还能撑 / 日均实扣 + `✓`/`···` 图标钮）→ 虚线新增行。
  新组件 `relay/OutletCards.tsx` + `relay/RelayTable.tsx`。
- **用量 Tab**：工具行（实扣口径牌 + ↻ + **按站筛选** + 今日/7d/14d/30d）→ KPI 条 →
  **模型小图阵**（3 列，每卡独立 y 轴 + Catmull-Rom 走势线 + 峰值/实扣 + 相对 Top1 胶囊条，
  点卡聚焦其余变暗）。新组件 `relay/ModelSparkCard.tsx`。
- **随之取消**（都是 2026-09-09 定的、被这份稿取代）：分模型/总量两档、四类 token 图例、
  模型表、「全部」档、点行摘除、牌价参考列。旧契约的测试**改写并在原地说明是被取代不是被违反**。
- **两处没照抄，都写在代码注释里**：① 稿子把 VS Code 列在生效侧（见上）；
  ② 稿子的样例数据一切正常所以没画异常态，但六个路由态仍走 `relayRouteNote()` 渲染 ——
  那四个异常态是静默失败**唯一**会出声的地方。
- **一处按稿去掉了**：切到中转站的**两段确认**（稿子 §6 是点行即切 + toast）。
  代价是误点一行就开始花钱；补偿是成本在同屏三处可见。删除仍保留二次确认。
- ⚠️ 交接包 `design_handoff_codexbar 6` 的四张 relay 截图是**同一份 5926 字节纯白 PNG**
  （暗像素 0/4000），没有任何设计信息；真源是 `prototypes/CodexBar 中转站 原型.dc.html`
  （渲染它取稿）。`8` 那份截图正常，两份说明文档逐字相同。

**★ 孤儿字段：中转站的 `model`**

表单能填、store 落盘、`_relay_upstream()` 装进 `up["model"]`，但代理**从没有任何读者**
（`_open()` 把 body 原样透传），而提示语「留空 = 沿用 config.toml 里的 model」反过来暗示
填了会生效。用户 2026-09-10 拍板**从 UI 去掉**；`relays.local.json` 里的键保留（老配置不该
因一次 UI 改动被静默丢弃）。★ 将来真要做「按站覆盖模型」，必须同时在页面标出「已被 X 覆盖」——
悄悄改掉用户要的模型 = 行为与计费都变了却看不见。

**★★★ 我自己的 17 次错误，15 次是同一个形状**

**测量工具坏了，而坏掉的样子长得像「通过」。** 判断失误只有 2 次。所以要防的不是"想错了"，
是"量错了却以为量对了"。已做成两件东西：

- **`tools/mutate.py`**（新）把六个**流程漏项**变成做不到的事：基线未验绿 / 选择器 0 命中
  （`-k world_readable` 对 `WorldReadable` 选中 0 条而退出码是 0）/ 锚点不存在 / 锚点多处
  （`replace(...,1)` 命中第一处而被测的是第二处）/ 文件没真变 / 还原未复跑。任何一项不过就
  `SystemExit` —— **不许跑出一份看着完整的报告**。
- **`CLAUDE.md` §7.-1「仪器自己会撒谎 —— 动手前的六问」**收判断类的那一半。
  ⚠️ 那一节写完的**同一轮**里我又犯了第 ① 条（protobuf 字段类型过滤错），是六问的自检抓住的，
  而那条结论正好反转成了上面「agy 时间戳」那个真 bug 的修复。

**其它**：`useQuotaSidecar` 现在按 `runCmd` 共享一次在途取数并广播结果 —— 两个
`useRelayUsage()` 实例原来各起一次 python、各打一次外网，手动 ↻ 时 `force:true` 让 Rust 的
300s 合并窗口失效，两块最多差 5 分钟；新增 `invalidateSidecar()` 让改完配置立刻重取
（原来「已停用」与仍在加它余额的 KPI 会同屏共存最长 5 分钟）；切到已停用的中转站原来显示
「✗ 未知错误」（原因在 `route.detail` 里，前端只读顶层）。

**测试 784 → 879 passed。** 新增闸 8 份：`test_relay_key_transport` / `test_relay_key_at_rest` /
`test_degradation_is_visible` / `test_store_root_agreement` / `test_installers_pass_the_store` /
`test_relay_day_models_budget` / `test_p2_last_batch`，以及 `?relay=sparse` / `?relay=mixed`
两份夹具（**稠密夹具下新旧实现结果完全一样，那些闸恒绿**）。

---------

## 未发版（main）— 2026-10-17

**新：刘海额度条（macOS，默认关，设置页「刘海额度条」开）。**

- 刘海下沿多出 7pt 黑边，里面一段一条细线：Codex 在用那个号的每个额度窗口 + agy 的 5h / 周（**同日改成光晕，见下**）。
  鼠标移上去展开额度环面板，点面板打开主界面。只显示 Codex 与 agy（用户 2026-10-17 定），
  只在带刘海的屏幕上显示，外接屏 / 合盖不显示。
- 样式是用户从 demo 里挑的（收起 B「底边细线」+ 展开 2「只看额度」），demo 留档
  `~/Downloads/codexbar_notch_demo_20261017.html`。
- 实现是 Tauri 第三个 webview（`notch.html`）+ `src-tauri/src/notch.rs`：层级 `NSStatusWindowLevel+1`
  盖过菜单栏、`fullScreenAuxiliary` 全屏可见；悬停判定用系统鼠标事件监听 + 进区后才起的 60ms 跟踪线程，
  不靠 WKWebView 的 mouseenter（CodexBar 几乎从不在前台）。关掉 = 销毁窗口，不常驻进程。
- 独立验证程序实测（2026-10-17，13 寸 Air M4）：窗口顶边与屏幕顶边间距 0；全屏可见、悬停展开正常
  （用户确认）；纯轮询版空闲主进程 0.30% CPU、webview 进程 0 —— 正式版换成事件监听就是为去掉这 0.30%，
  **事件监听版的空闲开销尚未实测**。
- 闸 `tests/test_notch_hud.py`（11 条，16 个变异全部符合预期）+ `notch.rs` 里 3 条几何单测。
- **合并前四方评审修掉 9 类问题**（agy 读到 24 天前的旧数、合盖后黑块留在外接屏、无刘海时开关静默、
  混合 DPI 坐标减半、收起态吞点击 / 抢焦点、开关竞态、window-state 记住展开尺寸、0.x% 显示 0 却是琥珀、
  权限过宽）。设置页那一行现在会说「现在没有检测到刘海屏」。见 B87。
- **刘海网页改成只听推送**（用户 2026-10-17）：原来借用 `useStore` / `useAgyQuota`，自带 30s 读 state + 全部 token、
  1s 冷却倒计时、过期还会 `run_agy_quota` 起 python —— 实测打开刘海条时它的 WebContent 60s 平均 0.25%。
  现在走 `hooks/useNotchData.ts`：启动读一次，之后只在 Rust 推 `state-changed`（限流 2s）/ `agy-quota-updated` 时重读；
  随时间变的部分（窗口过重置点、冷却结束）按「下一个时间点」定一次闹钟，面板开着才每 30s 走倒计时。
  agy 仍走池（`useAgyPool(false)`，只收 `agy-pool-updated` / `agy-live-changed`），本机那份只作 `snapshotOf` 的归属候选。
  「在用哪个号」的判据抽成 `helpers.ts::inUseAid`，`useStore` 与刘海条共用（`test_menubar_follows_proxy` 跟着改）。
  闸 `test_notch_hud.py::PushNotPoll`（9 个变异）。**改完后的开销尚未实测。**
- **活动光晕**（用户 2026-10-17）：Codex 在跑亮 Codex 平台色、agy 在跑亮 agy 蓝、同时跑左右各一半，光晕 2.4s 快呼吸；
  空闲时只剩细线 6s 慢呼吸。「在跑」= 45s 内写过：Codex 看最近 3 个日期目录的 rollout，agy 看对话库的 `-wal`；
  Rust 每 2s 看一次、**变了才推** `notch-activity`。检测线程只在**刘海窗口存在**时跑（`ensure_window` 起，窗口没了就退；
  没有刘海屏时不扫文件），新起的一条直接接管、旧的按 `WATCHER` 号与 `ENABLE_GEN` 代次自己退出 —— 快速关了再开不会丢线程（PR #1 评审意见）。
  收起态窗口两侧 / 下方多留 28 / 24pt 给光晕；收起时整窗不收鼠标沿用 main 的 `pass_clicks`。
  ⚠️ 中间版本曾用 `state.json` 的 `last_proxy_ts` 判 Codex：codex 会定时 `GET /models`，代理照样刷新它，**停手后仍显示在跑**（实测）。
  ⚠️ 实测细线慢呼吸让刘海网页进程常驻约 0.18% CPU（不是纯合成层动画）；用户看过数字后仍要空闲呼吸。
  闸 `test_notch_hud.py::ActivityGlow`（16 个变异）+ `notch.rs` 6 条单测。
- **收起态从细线换成光晕**（用户 2026-10-17 真机看过：「这个额度条效果不明显」）。去掉细线和刘海下沿 7pt 黑边，
  刘海周围一圈光晕：**平时颜色 = 额度**（每个窗口一段，剩余 ≥50 绿 / <50 琥珀 / 0 红 / 读不到灰，段间渐变）、6s 慢呼吸；
  **有平台在跑 = 整圈平台色**（Codex 青绿、agy 蓝、同时跑左右各半）、2.4s 快呼吸，停下恢复额度色 —— 用户从三种含义里选的这一种。
  窗口透明边加到 34 / 30pt，装下光晕 + blur（不够会被裁出硬边，有闸）。悬停触发区只剩刘海本身。
  闸 `ActivityGlow` / `SizesAgree` 改写（11 个变异）。实测刘海网页进程常驻约 0.28% CPU（细线版 0.18%）。
- **光晕改成两层、放开范围**（用户 2026-10-17：「散的太整齐规则了，明显看出你限制了他的范围」）。
  根因是透明边只按 blur 的 1σ 留，模糊边缘被窗口裁成一圈直边；blur 要往外 ~2σ 才淡到 2%，透明边加到 60 / 60pt，闸改按 2σ。
  光晕拆成贴边一层（窄、亮、blur 7）+ 散开一层（宽、淡、偏下、椭圆底、blur 20），两层呼吸周期错开（6s / 7.4s，在跑 2.4s / 3.1s）。
  闸 `SizesAgree` / `ActivityGlow`（9 个变异）。

### 修复
- **在隔离 HOME 下跑测试会弹「Keychain Not Found」并把测试卡住**（用户 2026-10-17 实报）：直接起 Headless Chrome 的 16 处
  全部加 `--use-mock-keychain`，并加闸。只动测试与 harness 工具，不影响 app。见 B86。

---

### B87 · 刘海额度条（PR #1）合并前四方评审 — 2026-10-17

评审：Opus 5.5 high / gpt-6.1-sol high / gemini-4-argon-high / grok-4.7 high，**4/4 判「修完才能合」**
（grok「not mergeable」，其余三家「mergeable after fixes」）。原文在
`~/Downloads/codexbar_pr1_notch_review_20261017/`（`opus.md`、`codex_final.md`、`agy.md`、`grok.out`）。
本机是 Mac17,14 + 4K 外接屏、**没有刘海** —— 有刘海那半（悬停唤醒、穿透、位置）本机测不了，见末尾。

| # | 缺陷 | 谁抓到 | 证据 | 修法 |
|---|---|---|---|---|
| 1 | agy 段只读本机 RPC 快照 | 本会话 + gemini（另三家漏） | 本机 `.agy-quota.json` 恒 `csrf_required`，`last_good` 停在 24.5 天前（2,119,211s） | `agyPool.snapshotOf(当前号, 本机RPC)`，与菜单栏同一条；`useAgyPool(false)` 不起子进程 |
| 2 | 刘海屏消失不拆窗、合盖时打开则开盖不出现 | 4/4 | `geometry()` 为 `None` 直接 return；`set_enabled` 无刘海时在装监听前就返回 | `reconcile()`：None ⇒ 销毁、Some 且无窗 ⇒ 建；监听无论有无刘海都装 |
| 3 | 跟踪线程坐标 | 4/4 | tao 0.35.3 `util/mod.rs:105` 按**主屏** scale 转物理坐标，PR 除以**刘海窗口**的 scale | 唤醒与跟踪同用 `NSEvent mouseLocation`；后台线程不再碰 NSWindow/NSScreen，`place` 派回主线程 |
| 4 | 无刘海时开关静默「成功」，错误被 `.catch(() => {})` 吞掉 | 4/4 | 无刘海走 `Ok(())` | 命令回 `{active, reason}`；设置页 `notchRowDesc` 说原因；失败回滚开关 |
| 5 | 收起态吞菜单栏两侧 / 下沿点击；`show()` 抢 key | 3/4 | tao `show` = `makeKeyAndOrderFront` | 收起 `setIgnoresMouseEvents: YES`；`orderFrontRegardless`；`accept_first_mouse` |
| 6 | 开关 / 收起动画竞态 | 3/4 | 关掉后旧线程仍可 `set_open(true)`；旧收起计时裁掉新一轮动画；`TRACKING` 无条件清 | `ENABLE_GEN` / `OPEN_GEN` 代次；跟踪线程只清自己那一号 |
| 7 | `notch` 不在 window-state 黑名单 | gemini | `with_denylist(&["menubar"])` | 加 `"notch"` |
| 8 | 剩 0.x% 环上写 0 却是琥珀；stale 提示一律「agy 没在跑」 | 3/4 | `pct <= 0` 判原值、`Math.round` 显示 | 判显示出来的整数；旧数按原因分两句 |
| 9 | `notch` 并进 default capability | 3/4 | 顺带拿到 autostart / 通知 / 窗口操作 | 独立 `capabilities/notch.json`，只给 `core:default` |

还修了：首个 `notch-open` 可能早于前端 listen（注册后再问一次 `open`）；改分辨率后前端刘海尺寸不跟（`notch-geom` 事件）；
刘海屏不是主屏时 x 依赖 auxiliary 矩形的坐标系（改成只用宽度 + 屏幕 origin，单测覆盖）；面板空时说「暂无可显示的额度」。

**没做**（评审提了、不阻塞）：刘海窗口仍挂完整 `useStore`（30s `read_state` + 1Hz 冷却计时，刘海不用后者）；
`counts.live` 含暂停 / 额度未知的号（与菜单栏同口径，没单独改）；事件监听版的空闲 CPU 仍未量。

**闸**：`tests/test_notch_hud.py` 11 → 30 条。`notchSegs.ts` 是纯函数、node 真跑（读不到 ≠ 满格、旧数的两种原因、
「当前号未知」不借别号的数、0 边界颜色、设置页文案），其余每类缺陷一条结构闸；`notch.rs` 几何单测 3 → 6。
变异 17 个全红（评审指出原测试下 5~8 种变异能活）。

⚠️ **有刘海那半零真机验证**：收起态穿透后全局 `mouseMoved` 监听能否在刘海区叫醒（opus 认为穿透反而修好唤醒，**推断**）、
`orderFrontRegardless` 在全屏 Space 的表现、刘海屏非主屏的实际坐标 —— 需要 PR 作者在带刘海的 Mac 上复验。

---

### B86 · 假 HOME 跑测试 ⇒ Headless Chrome 弹「Keychain Not Found」模态框、测试无限阻塞 — 2026-10-17 ✅（未发版）

**现场**（用户在另一个会话里抓到进程链）：v1.10.4 发版时，为了模拟干净的 CI runner，我跑了
`T=$(mktemp -d); HOME=$T python3 -m unittest discover -s tests -p 'test_*.py'`。07:33:12 跑到
`test_card_uniformity.py:161` 起 `Google Chrome --headless=new --disable-gpu … --dump-dom http://127.0.0.1:3304/uniprobe.html?nav=home`（PID 62280）。
Chrome 要读「Chrome Safe Storage」钥匙串 → 在 `$T/Library/Keychains/login.keychain-db` 找不到 →
SecurityAgent（PID 60330）弹出 **Keychain Not Found** 模态框，测试停在那里等人点按钮。

**我这边看到的样子**：这一轮全量跑了 25 分钟还没出 `Ran`（平时 7 分钟），日志每 30s 只长 ~33 字节，
我判断成「空 HOME 让某些测试变慢」、超过 10 分钟上限后按 PID 杀掉。**实际是阻塞在一个用户看得见、会话里看不见的弹窗上**。
⚠️ 「慢」与「卡在弹窗」在日志上长得一样 —— 都是不出新行。判别要看**卡在哪个进程上**（`ps` 里有没有 SecurityAgent、Chrome 的 etime），不是看日志。

**根因**：直接 `subprocess.run([CHROME, "--headless=new", …])` 的 16 处（14 个文件：13 个测试 + `codexbar/uishot/sweep.py`）
都没带 `--use-mock-keychain`。Playwright 的 13 处不受影响 —— 它默认就带 `--use-mock-keychain` 与 `--password-store=basic`
（读 Playwright 起的 Chrome 进程命令行实测，n=1）。

**修**：16 处全部加 `--use-mock-keychain`。实测假 HOME + 该参数：无 SecurityAgent、页面完整渲染（DOM 1.2 MB、3 个卡片网格，n=1）。
不加参数的对照组就是用户撞上的那一次（n=1）—— **刻意没再复现**，复现一次就是再给用户弹一次窗。

**验证途中我自己的仪器撒了一次谎**：第一版探测用 `ps -axo command | grep -q "[S]ecurityAgent"`，而同一条命令里的
`echo "SecurityAgent seen=…"` 让**我自己的 zsh 命令行**被匹配上 ⇒ 三次实验（含正常 HOME 的对照）都报「出现了」，
并且一「出现」就杀 Chrome，所以 DOM 全是 0 字节 —— 一度得出「这个参数不够」的错误结论。改用 `pgrep -x SecurityAgent`
（按进程名精确匹配）后才拿到真结果。是本仓已记过的「`pgrep -f` 自匹配」同一类，换了个形状：`[S]` 技巧只防 grep 匹配自己，
防不了**同一条命令行里别处写着这个词**。识破它靠的是对照组：正常 HOME 也「出现」，就说明探针坏了。

闸 `tests/test_headless_chrome_mock_keychain.py`：AST 扫 `tests/`、`codexbar/uishot/`、`tools/` 里每个含 `--headless…` 的
list/tuple 字面量，必须同时含 `--use-mock-keychain`；先断言扫到 ≥16 处（探针自证）。变异：去掉 `test_card_uniformity.py` 那一处 ⇒ 红、指名该行。
⚠️ 闸只认**字面量**参数表 —— 动态拼的参数列表它看不见。

---

## v1.10.4 — 2026-10-17

**修：GitHub `.dmg` 装机后终端入口与后台服务读写两份数据；Codex 压缩会话漏算；agy 周额度变灰。新：总览 ⌘1/2/3 切档、设置页「数据源状态」。**

v1.10.3 之后的一批（B83 / B84 / B85）。

### 修复
- **agy 卡片 Gemini 周额度变灰**（用户 2026-10-16）：周改从生产 host 的额度摘要读，不再沿用 05:06 的旧读数。见 B83。
- **Codex 历史 token 大量漏算**（外部用户 2026-10-16）：压缩过的会话 `rollout-*.jsonl.zst` 现在计入。见 B84。
  ⚠️ 有 `.zst` 的机器首次打开 90 天 / 年度视图会慢一次（外部用户实测 1,895 个文件解压 + 解析约 36s），之后按签名命中缓存。
- **`.dmg` 装机后终端入口读写另一份数据**（四方评审 2026-10-16）：`codex-rotate` / `agy-rotate` / cxp / cxd / wrapper 等不设变量时都落到 `<store>/runtime/`。见 B85。
- **`cxd` 写死作者路径**，找不到判据文件时 logout 守卫放行；现在按自身位置找、找不到 exit 78。见 B85。
- `codex-rotate tokens` 同样漏 `.zst`；`connector.remove()` 漏卸 `agydawn`；GUI 选 python 时真跑一次 OpenSSL 检查。见 B85。
- **设置页「数据源状态」**：每个已注册源这一轮读成了什么样（少算了琥珀、没找到 / 空灰色），来自常规扫描、不用点按钮。
  用户 2026-10-16 从两版 demo 里选的 A（设置页常驻；B = 用量卡角标，未采用）。见 B85。
- CI：守卫在 macOS 上也跑一遍；release 对构建出的 `.app` 做 `.dmg` 布局冒烟（不起 GUI）。
  首跑即抓到一条：`test_resume_routing::CxpRouting` 继承真实 HOME，作者机上恰好有 `~/.codex/rotateproxy.config.toml` 所以恒绿，
  干净的 macOS runner 上 8 条子用例全红（ubuntu 上该类按平台跳过，从没真跑过）—— 改成自带临时 HOME。包冒烟在真构建的 `.app` 上 7 条全过。

- `agy-rotate login --help` / 未知选项会直接开始加号流程（先把当前号收编进池、再等回车）；现在打印用法或报错退出，池不动（2026-10-17 实际踩到）。

### 变更
- **总览 ⌘1/⌘2/⌘3 切 Codex / Gemini / Grok 档，不再切号**（用户 2026-10-16）。取代 2026-09-14 / 09-19 的「⌘N 切第 N 张卡」；
  卡片左上角的 `⌘N` 角标随之撤掉（切号走卡上的「切换」），快捷键写进档位 Tab 的悬浮提示。别的页面按 ⌘+数字不再有作用
  （原来在任何页都会切 codex 号）。闸 `tests/test_overview_shortcut_switches_tab.py`（真 bundle 端到端，变异 10 个全中）。

---

### B85 · `.dmg` 装机：终端入口的数据目录与后台服务分裂 — 2026-10-16 ✅（v1.10.4）

四方评审（Fable 5.1 / gpt-6-astra / gemini-4-argon / grok-4.7，4/4 一致）+ 沙箱实跑确认。汇总在
`~/Downloads/codexbar_install_parity_review_20261016/synthesis.md`。

**现场**（沙箱 `.dmg` 布局、不设任何 store 变量，各 1 次）：终端 `codex-rotate` 的 `STATE = <store>/runtime/state.json`，
后台服务读 `<store>/state.json`——两份状态、两把锁；`agy-rotate` 的池文件 = `<store>/runtime/.agy-pool.json`。
既有的闸全都**显式传了** `CODEX_ROTATE_STORE`，所以永远是绿的。作者机是 clone 装机，两条路碰巧相等。
这是外部用户「不轮换、切号进不去」的一个**不需要 keyring 假说**的候选解释 —— **仍未在他机器上取证**。

**不变量**：每个外部位置只有一个求解规则。数据目录 = 环境变量 > 代码在名为 `runtime` 的目录里则取父目录 > clone 取代码根。
落到 12 处：`codex-rotate` · `agy/pool.py` · `proxy/proxy.py` · `traffic/{scan,rotation,quota_anchors,agy_quota_sampler,agy_rotation}.py` ·
`grok-quota-sampler` · `proxy/cxp` · `proxy/cxd` · `scripts/codex-wrapper-with-logout-guard.sh`。

同批：
- `cxd` 原来默认 `~/Projects/tools/codex-account-rotator` + `~/.local/npm-global/bin/codex`，判据文件不在就跳过（`if [ -f ]`）⇒
  `.dmg` 机器上 logout 守卫 **fail-open**。现在代码根从自身解析，真 codex 从 PATH 里跳过我们自己的 wrapper 找，找不到 exit 78。
- wrapper 删掉作者路径兜底：判据文件按自身 → 数据目录 → `runtime/` 找。⚠️ 本机 `~/.local/bin/codex` 是 HEAD 版的**副本**，
  要重装 wrapper 才换成新版。
- `codex-rotate::_scan_tokens` 收 `.zst`（同 B84 的 keep 规则）、读失败不进缓存并打 ⚠️；本机 30 天总数改前改后相同（1,260,938,418）。
- zstd 候选 `/opt/homebrew/bin` · `/usr/local/bin` · `/opt/local/bin`（两处同表），Python 3.14 内置 `compression.zstd` 优先；不打包 zstd（评审 2:2，选 A）。
- `connector.remove()` 按 `SERVICES` 卸，原来写死 4 个漏 `agydawn`。
- `lib.rs::python_bin()` 对候选真跑 `ssl.OPENSSL_VERSION.startswith('OpenSSL')` 并缓存；全不合格仍回落 `python3`
  （**刻意偏离评审**：扫描器不需要 OpenSSL，回落比整个 app 不工作好；额度 403 仍由 `health` 报）。

闸：`tests/test_store_root_dmg_layout.py`（`.dmg` / clone 两种布局 × 9 个 Python + 3 个 shell 入口、`env -i` 实跑；
发布脚本禁作者路径字面量；两处 zstd 候选表相同）—— 变异 18 个全中，其中一个「注释里出现路径」的良性变异起初假红，已修。
`test_bundled_scripts_get_their_store` 的正则跟上链式写法（现识别 7 个脚本）。

**P1 · 读不到要一路说到屏幕上**（数据层已做，UI 待选）：
- `scan.sources[k] = {state, root, name, files, read_failed, no_decoder, unparsed}`，六态
  `not_found / empty / ok / partial / read_failed / disabled`。零行源不再从诊断里消失（`platforms` 形状不动，30+ 处消费者不受影响）。
- 普查（`_unparsed`）**只认压缩后缀**：本机 grok 根下 127 个 `updates.jsonl.lock`，按任意后缀算就是一盏永远亮着的灯。
  同名 `.jsonl` 已收的 `.jsonl.zst` 不算漏（那是去重）。实测普查多花 ~60ms（claude 43ms），热路径 ~1.4s。
- `NoDecoderError(ScanReadError)`：「这台机器没有解压器」与「文件坏了」分开计，文案才能说「装一个」。
- `codexbar/src/scanHealth.ts::sourceNotes`（零 import）把状态说成人话：少算是 warn，没找到 / 空是 info（没装那个 CLI 是常态，不告警）。
- 本机实测：8 个源 7 个 `ok`、OpenClaw `not_found`，`unparsed` 全空。
- 闸 `tests/test_scan_source_health.py`（17 条，变异 14 个全中；起初两条是空的 —— `.lock` 夹具旁边有同名 `.jsonl` 被去重规则兜住、
  没解压器那条没断言级别 —— 已补）。
- UI 两版 demo（真 bundle 注入、未改源码）：A = 设置页「扫描新数据源」下常驻一块「数据源状态」；B = 用量卡名字旁一枚琥珀角标
  （与 Antigravity「覆盖 100%」同位，卡高不变）。B 的第一版是卡内一行副标题，卡被撑高、与同排错位，已弃。
  **用户选 A**，已实现（`SettingsPage.tsx::SourceStatusBlock`）：旧快照没有 `sources` 时整块不画（不说「全部正常」）；
  全部正常时只一行「N 个源全部正常」（停用的不计）。本机实测只有一行灰色「OpenClaw：未找到 ~/.openclaw/agents」。
  闸 `tests/test_settings_source_status.py`（真 bundle、IPC 拦截换夹具，3 条，变异 4 个全红）。

**P2 · CI**：`ci.yml` 加 `invariants-macos`（同一条 pytest 命令）、ubuntu 确保有 zstd；`release.yml` 在 macOS 构建后用
`CODEXBAR_BUNDLE_SCRIPTS=<.app>/Contents/Resources/scripts` 跑本闸 —— 本机对 `/Applications` 里的包实测绿，
删掉包里的 `dawn_sched.py` 或换回 HEAD 版 `codex-rotate` 都变红（后者正是 `store/runtime` 那个原始缺陷）。
⚠️ **两个新 job 都还没在 GitHub 上跑过**，第一次推送后看结果。

---

### B84 · Codex 压缩过的会话（`.jsonl.zst`）全部漏算 — 2026-10-16 ✅（v1.10.4）

外部用户：v1.10.3 下 Codex 30 天只显示 ~125.7M，长期重度使用应在数十亿。附 Antigravity 初版排查 + Claude Code 核实交接（`~/Downloads/交接说明.md`、`verify(1).py`、`verify-output.txt`）。
**实测（他的机器，2026-10-16）**：`~/.codex/sessions` 下 1,675 个 `.jsonl.zst`、37 个 `.jsonl`、20 个 `.jsonl.bak-namespace*`；同名并存 0 对。
用仓库解析器按窗口算：30 天 125.9M → 193.4M（漏 35%）、90 天 143.4M → 4.03B（漏 96%）、全部 173.3M → 4.23B。
**根因**：codex 源 `glob` 只认 `**/rollout-*.jsonl`，`_scan_codex_file` 用文本 `open()` 读不了 zstd。
**交接说明对 Antigravity 原报告的三处更正，核过、成立**：
① 下跌与 `PARSER_V` 11→12 无关 —— `scan()` 只汇总 glob 当前匹配到的文件，旧 `.jsonl` 的缓存条目留着也不进总数；
② SQLite `threads.tokens_used` 不能当真值 —— 56 个分叉会话第一条累计值就带着父会话的 6.44B，直接加总会重复；
③ 原 diff 不能照抄：宽 glob 会收 `.bak-namespace*`（+841M）、zstd 失败 `return rows` 会把会话钉成 0、升 `PARSER_V` 让别家白白全量重扫。
**修**（`traffic/scan.py`）：
- `glob` 放宽为 `**/rollout-*.jsonl*` + 新钩子 `keep: _codex_keep`：只收 `.jsonl` 与 `.jsonl.zst`，同名并存只收 `.jsonl`（压缩中途 `.zst` 可能没写完）。
- `_zstd_text`：先试 Python 3.14 的 `compression.zstd`，再走 `zstd` 命令行；读不成抛 `ScanReadError`。
  `_scan_codex_file` 两种来源喂同一个逐行循环，跨行状态一字未改；`.jsonl` 打不开也改成抛错（原来 `return rows`）。
- 同一类缺陷顺带修：`_scan_dsh_file` 解压失败原来静默 0 行，现在同样抛错。
- 不升 `PARSER_V`（row 结构没变，`.zst` 是新缓存键，本来就会解析）。
**本机核对**（本机 0 个 `.zst`，4538 个 `.jsonl`）：改前/改后 codex 30 天 1,051,065,943、90 天 8,772,863,913，逐 token 相等，`read_failed` 0；
最近 40 个真 rollout 压成 `.zst` 后逐文件解析，40/40 rows 完全相同（2,596 行）。
**闸**：`tests/test_scan_codex_zst.py`（8 条：同内容同 rows / 备份不收 / 并存计一次 / 坏文件进 `read_failed` 且不进缓存 / 真 zstd 坏文件抛错 / `.jsonl` 打不开抛错 / dsh 抛错），变异 8 个全红。
**待外部用户定**：`~/.codex/archived_sessions`（163 个 `.zst`，90 天 625M）要不要作为第二个扫描根计入；`.bak-namespace*` 本轮不计入。
**还没解释的**（交接说明 §8）：51 个会话扫描结果比 SQLite 最终累计大，合计 1.38B，疑似会话中途累计值重置，未核实。

### B83 · agy Gemini 周额度变灰 —— 周从生产 host 补 — 2026-10-16 ✅（v1.10.4）

用户：「gemini 卡片周额度的字体显示变灰了，是有点问题的」。
**现场**：B82 之后周没有来源，只能沿用 05:06 的读数（`seenAt` 已 13h），卡片按设计把那一行降到 62% 不透明度；而「这是旧读数」只写在悬浮里，看上去就是渲染坏了。
**实测（~18:40 SGT，零计费，只读）**：
- `daily-cloudcode-pa` 摘要对 3 个号仍只回 Claude/GPT 组。
- **生产 host `cloudcode-pa` 同一个请求回了 Gemini 组，且周不再是 B69 的空账本**：A 号 98.41%（daily 最后读数 98.42%）、B 号 98.64%（98.65%）、C 号 38.76%（39.8%）；
  A / B 号 的周 reset 与锚点账本钉住的 **Δ = 0 秒**。一次性 agy 的 `/usage` 状态栏（当时登录 B 号）显示 `⏱ 2% (20:53) · 📅 1%`，对得上。
- **生产 host 的 5h 不能信**：同一份响应里 B 号 5h 是「1.0、reset = 现在+5h」，模型端点与 agy 状态栏都说已用 2%。
**判断**：Google 可能在把 Gemini 额度挪回生产 host —— 推断，未证实。周是否完整跟进最新消耗仍是 n 很小的观测；能判别的是周已用多的号（C 号），要切号对照 agy 状态栏。
**修**（`agy/pool.py`）：摘要缺 Gemini 组时，`fetch_quota` 除了从模型端点补 5h，还从生产 host 摘要只取 `gemini-weekly`（`gemini_weekly_from_prod`，桶上带 `source`）。两道闸防它退回空账本：
reset ≈ 现在 + 7 天 ⇒ 不采信；锚点账本里本窗口已 anchored ⇒ reset 差超过 600s 不采信。桶在、`remainingFraction` 缺席 ⇒ 读不到（不补 1.0）。
`agy-rotate` 两个写 `quota_summary` 的调用点（`cmd_quota` / `cmd_health`）把 `quota_anchor` 传进去；探针那两处只看 5h，不传。
已知代价：真号的周窗口刚重置、闲置时也长「reset = 现在+7天」，那时周显示沿用值或「—」，不冒充满格。
**真数据**：改后跑 `agy-rotate quota`，3 个号的 `gemini-weekly` 都来自 `cloudcode-pa`、不带 `seenAt`；C 号 原来没有周读数，现在 38.8%。
**闸**：`tests/test_agy_gemini_weekly_from_prod.py`（9 条），变异 9 个全红；抓到一条空断言（夹具里周桶排第一，「连 5h 也收」照样绿），已把 5h 排到前面。

---

## v1.10.3 — 2026-10-16

**修：agy 卡片 Gemini 5h 显示「上游没给数」。**

v1.10.2 之后 2 个 commit。

### 修复
- **agy 卡片 Gemini 5h「上游没给数」**（用户 2026-10-16）：2026-10-16 起云端额度摘要对每个号都不再回 Gemini 组，5h 改从模型列表现读；
  周没有别的来源，沿用最后一次读数并标龄，超过一天改说「旧读数已过期」（不再说「上游没给数」）。见 B82。

### 文档
- README / RUNBOOK / credentials 规则：agy 额度来源改成「摘要 + 模型列表兜底」；README 不再说 agy 额度读本机 RPC（B68 起已不可用）；RUNBOOK 加「旧读数已过期」排障条。

---

### B82 · 摘要不再回 Gemini 组，5h 显示「上游没给数」— 2026-10-16 ✅（v1.10.3）

用户：「现在 gemini 5h 显示上游没给数是什么意思？」
**实测**（11:47 SGT）：`retrieveUserQuotaSummary` 对 3 个号**全部**不回「Gemini Models」组，从 ~05:06 起持续；
换 3 种客户端身份（`antigravity/1.11.5 windows/amd64`、本机 `1.3.6 darwin/arm64`、不带 `Client-Metadata`）结果相同。
同时 `fetchAvailableModels` 照常给 Gemini 5h：12 个 gemini 模型同一个 `remainingFraction`、同一个 `resetTime`（**只有 5h，没有周**）。
本机 `agy-quota` 走本地 RPC 需要 CSRF token（B68），不可用。
**为什么摘要不回了：未判别** —— ① Google 撤了 Gemini 周限额；② 服务端灰度/故障。组重新出现即为 ②。
**根因（显示面）**：B81 的沿用只认**整组缺失**；5h 补上之后 Gemini 组在了、周桶不在，周就不再沿用。
另一处：沿用桶过了重置时刻会删数，卡片落到「上游没给数」——话不对，那是「上游这一格缺数」的说法。
**修**：
- `agy/pool.py::fetch_quota` 摘要里没有 Gemini 组 ⇒ 调 `gemini_group_from_models` 从模型端点补一个只含 5h 的组（只认带 `resetTime` 的 gemini 模型；有一个缺数 ⇒ 整格读不到，不拿别的冒充）；补失败不影响摘要。
- `carry_missing_groups` 改成**桶级**：同名组在、缺某个桶也沿用；沿用超过 `CARRY_MAX_SECS`（24h）⇒ 读不到。
- 前端 `AGY_EXPIRED_TITLE`：带 `seen_at` 的读不到格说「旧读数已过期」，卡片与菜单栏同一句。
**拒绝的方案**：「没给数 = 100% 未启动」。周没有来源，默认满会把最后一次周读数只剩 39.8% 的号当满号挑走；
5h 是现读，闲置窗口已经按锚点账本显示「100% · ↻未启动」。
**真数据核对**（12:03）：三个号 5h 来自模型端点（99.0% / 99.8% / 99.0%），周沿用 05:06–05:09 的读数（98.4% / 98.7% / 39.8%）并带 `seenAt`。
**闸**：`tests/test_agy_gemini_from_models.py`（模型端点取组 / 兜底接进 `fetch_quota` / 桶级沿用 / 过一天读不到 / 前端文案），变异 13 个全红；
顺带修了 `test_agy_realtime` 解码闸被一条 `status: ERROR` 账本行打红（agy 自报 thinking=output=1183，db 是 35821 —— 自报错，不是字段号变了）。
harness `?agyodd=expired`。

---------

## v1.10.2 — 2026-10-16

**修：agy 号的 5h / 周额度偶尔显示成 Claude/GPT 组的 100%。**

v1.10.1 之后 2 个 commit。

### 修复
- **agy 第二个号的 5h / 周额度不对**（用户 2026-10-16）：云端额度摘要偶尔整组不回 Gemini，卡片把 Claude/GPT 组的 100% / 100% 画成了它的 5h / 周。
  现在缺的组沿用上次读数并标「HH:MM 的读数」（卡片与菜单栏同样降级显示），选号也不再因此把号排到最后。见 B81。
- 菜单栏 agy 行缺格时的说明还在说「只有当前登录的号读得到」（B53 早已证伪），改成「这次没读到，下次刷新补上」。

### 文档
- RUNBOOK / SETUP：服务数 3 → 5（含两个定时探针）；**加号改为 `codex-rotate login`**（原文写的 `codex logout && codex login` 会在服务端吊销当前号）；
  去掉已取消的「每天 07:00 自动刷新」；补 `next` / `integration` / `dawn-probe` 用法与三条排障（装机版更新后不轮换、续航条单位、定时探针没跑）。
- `codex-rotate` 的 usage 行补上 `dawn-probe` / `integration` / `next` / `pin` / `priority` / `borrow`。

---

### B81 · agy 号的 5h / 周额度显示成 Claude/GPT 组的 100% — 2026-10-16 ✅（v1.10.2）

用户：「我用 agy 第二个账号，现在的 5h 和周额度都是不正确的」。
**实测**（`agy.log`，最近 ~200 次读数/号）：云端 `retrieveUserQuotaSummary` 对**同一个号**几分钟内一会儿带「Gemini Models」组、
一会儿不带 —— dbk 6 次、sam 3 次、tomyhuohuo 1 次；dbk 01:40 有（98.1%）、01:43 无、01:47 又有。
**根因**：`_store_quota`（以及 `health` 那条路）把摘要**整份替换**。缺组那一刻 Gemini 两个桶消失：
卡片 `agyWinRows` 按窗口取各组最小值 ⇒ 画出 **Claude/GPT 组的 5h 100% / 周 100%（周重置 10-22）**；
总览续航条只认 Gemini ⇒ 同一个号显示「—」；选号投影 `quota.gemini` 也没了 ⇒「读不到排最后」，自动切号会无故挪走这个号。
违反的是 CLAUDE.md §7.0b 第 3 问「这次没返回的子字段沿用旧值」—— 本仓第四次撞同一个形状。
**修**：`agy/pool.py::carry_missing_groups` —— 新读数里没回来的组沿用上次那组，每桶标 `seenAt`（连续缺失保持第一次的时刻）；
沿用桶的重置时刻已过 ⇒ 改成「读不到」，不拿重置过的窗口的旧数冒充。两条写入路径都过它。
前端 `seenAt → seen_at`，AgyCard 与菜单栏 AgyRow **同一画法**降级（菜单栏原来不认这个标记）。
**真数据核对**：修后连续 5 次刷新，01:53:23 那次 Gemini 组又缺，dbk 卡上保持 01:53:00 的 97.9% / 99.5% 并标旧，不再变成 100%。
**未修、未判别**：dbk 的 Gemini 值在两组数之间来回（周 98.98/99.45、5h 96.99/97.90，5h 重置时刻相同）。
两个假说都能解释：① 云端副本不一致；② agy 滚动窗口的回升与消耗交错（tomyhuohuo 同期回升 18 次）。
判别实验：agy 闲置时一分钟内连读 dbk 10 次 —— ① 仍来回，② 不来回。
**闸**：`tests/test_agy_missing_group_carried.py`（9 条：沿用并标龄 / 读到的照常覆盖且不重复 / 过重置变读不到 / 连续缺失不刷新时刻 /
失败不写数 / 两条写入路径都过它 / 前端带标记 / 卡与菜单栏都降级），变异 9 个全红；harness `?agyodd=carried`。

---

## v1.10.1 — 2026-10-16

**修：账号卡点「删除」后动作条乱掉（「取消」折两行、「探针」被挤截断）；修 v1.10.0 的 CI 红。**

v1.10.0 之后 3 个 commit。

### 修复
- **删除确认态**（codex 与 Gemini 卡）：点垃圾桶后整条换成「删除 X？· 确认删除 · 取消」，不再把两个按钮硬塞进已经满的一行；
  动作条高度不变，确认旁边也不再挨着「切换 / 探针」。见 B80。
- **v1.10.0 的 `ci` 红**（`release` 是绿的，安装包不受影响）：5 条测试本机绿、CI 红 —— 被测的纯函数写在 import 了 `react` 的 hook 里
  （CI 不装 `node_modules`），以及 tauri 的 `cargo test` 在 ubuntu 上缺 gio 开发库。见 B79。
- UI 测试夹具：路由分账的中转站夹具改为无条件注入（原来活快照自带 `by_provider` 时就不注入，闸会随当天数据红）。

### 文档
- README 文件骨架补齐（Connector、`<store>/runtime/`、`dawn_sched.py`、`portalock.py`、`grok-quota`、`agy-quota`、`bin/agy`、harness、CI 等），
  `install-launchd.sh` 的服务数 3 → 5。

---

### B80 · 账号卡点「删除」后动作条乱掉 — 2026-10-16 ✅（v1.10.1）

用户截图（codex 卡 `mou`，并说「各 AI 总览卡片都是一样」）：点垃圾桶后「探针」被挤成半个、「取消」竖着折成两行。
**复现**（harness、860 与 1200 两档实量）：确认态用「确认删除」65px +「取消」~44px 顶替 34px 的垃圾桶 ⇒ 整行超 ~80px；
flex 把「探针」从 61px 压到 30px（截断）、「取消」没写 `nowrap` 折两行、整条 46px → 60px。Gemini 卡同一段代码，同样。
**为什么会犯**：v1.9.x 把动作条压成一行时量的是常态，确认态是点了才出现的形态，从没被任何一次布局验证覆盖（同 `?click=` 那条教训）。
**修**：确认态整条只剩「删除 X？/ 确认删除 / 取消」，三块定高 28（= 探针按钮高）⇒ 整条高度不变；四个图标缩到底也差 ~80px，所以没走压缩那条路。
**闸**：`tests/test_delete_confirm_one_row.py`（真 bundle、codex + Gemini × 860/1200：只有三块、不折行不截断、高度不变、点取消回到完整动作条），变异 5 个全红。

---

### B79 · v1.10.0 的 ci 红而 release 绿 — 2026-10-16 ✅（v1.10.1）

推 tag 后 `release` 绿（四个安装包都挂上了），`ci` 红：`test_resize_less_work` / `test_overview_one_row_header` 4 条 `ERR_MODULE_NOT_FOUND`，
`test_window_zoom` 的 `cargo test` 报 `pkg-config … gio-2.0 >= 2.70`。
**根因**：① `quantizeDown` / `nextCompact` 写在 `hooks/useFillHeight.ts` / `hooks/useOneRowHeader.ts` 里，测试用 node 直接加载那个文件，
而它顶层 `import … from "react"`；本机有 `node_modules` 所以绿，CI 不装依赖。② ubuntu runner 没装 gtk/gio 开发库，tauri crate 编不过。
**为什么会犯**：发版收尾只核了 `release` workflow（CLAUDE.md 当时只写了那一条），`ci` 是收尾后才看的。
**修**：两个纯函数搬到零 import 的 `codexbar/src/resizeMath.ts`（模拟无 `node_modules` 实测：旧路径 `ERR_MODULE_NOT_FOUND`、新路径能加载）；
Linux 缺 gio 时 `cargo test` 那条 skip（Rust 真编译在 ci.yml 的 macOS/Windows 构建 job）。CLAUDE.md §3.6 加「两条 workflow 都绿才算收尾」，§4 加「node 测的 TS 放零 import 模块」。

---

## v1.10.0 — 2026-10-16

**修好 GitHub 安装包「更新后不轮换」；续航条改成「现在能连续用多久」；agy 的 5h 倒计时分真假、能定时探针；窗口缩到最小也一屏放下。**

v1.9.6 之后 2 个 commit（10-14 ~ 10-16 一整批）。按规则是 minor：含多项新功能。

### 修复
- **装机版（`.dmg`）更新 App 后轮换不生效**（外部用户报「自动轮换不轮换、切号进不去」）：接入时运行时被**复制**到数据目录，
  App 更新从不刷新它，Connector 却报「已完成」。现在逐字节比对，不一致就把「准备运行时」「装常驻服务」两步转回待做，
  总览接入检查新增第 ⑦ 项「运行时与 App 同版本」标红。另修：装机版恒误报「入口 cxp 不存在」；运行时漏带 `dawn_sched.py`。见 B77。
- **续航条「全池还能撑 98.6 小时」与实际「半小时几个号见底」对不上**：分母是钟点跨度（含空闲），改成连续使用时间。见 B78。
- `agy-rotate login` 先清钥匙串再起 agy（不再进程内 `/logout` 换号），没登成自动装回原号。
- agy 某个额度桶缺 `remainingFraction` 时显示 `—`，不再丢掉这一桶、拿另一桶冒充最紧。
- agy 用量账本：`agy -p` 报全 0 usage 的行标 `usage_missing`，不再当真 0 计入；模型名归一（一个 Flash 曾画成三条）。

### 新增
- **续航条 = 连续使用时间**（codex 档）：「现在能连续用 ≈ N 分钟 · X 后有号回满」+「本周 ≈ N 小时」+「5h 一窗≈4m」。
  依据是历史上 5h 用完的次数（≥3 次）与 5h↔周换算比；请求间隔 >5 分钟算闲置；样本不足显示 `—` 并说明「不是撑不了多久」。
  每张卡上的单号预测已去掉，只在续航条展示。`quota_marks` 现在两个窗口都记（带 `w`），5h 用完写 `exhaust_log`。
- **agy 5h 倒计时真假**：从没用过的窗口标「↻未启动」；卡片计费探针探前探后各免费读一次，额度真降了才算启动。
- **定时探针搬到总览**：Codex / Gemini 各一个「定时 开/关」胶囊，选时间后 3 分钟内随机触发；新增 launchd 服务 `agydawn`
  （两份安装器同步）。⚠️ 会花钱，默认关闭。
- **Gemini 档位**：Ultra 号标 ULTRA。取额度被 Google 要求验证时显示「需验证 →」。
- **grok**：套餐名徽章（如 SuperGrok）；HTTP 429 单列并按 `Retry-After` 退避；总览卡页脚常显读数时刻、改为一行（卡底不再多一截空白）。
- **AI 用量**：页面底部平台卡按今日 token 降序（列表与图例仍按你的排序）；Claude 1h 缓存写按 2× 输入价计（`PARSER_V` 12，30 天等效费用 +12.9%）；
  定价补 Gemini 4 Argon（介绍价，11-30 到期）与 Claude 5.5 档位 id；代理轮换 Gemini 版按号拆 token。
- **一屏仪表盘**：最小窗口 860×560 下各页不滚（KPI 让格 / 缩数字、图表撑满、紧凑卡片、总览顶栏放不下换图标+短名）。
- **窗口放大**：超过 1200×740 时整页按比例放大（1.0–1.6），拖动中不变、松手 150ms 后调一次；拖动缩放时不再逐像素重算图表与 KPI。

### 已知未解
- 外部用户机器上**未取证**：wrapper 未装 / PATH 顺序、`Ctrl+Z` 挂起后 `fg`、`CODEX_HOME` 或钥匙串凭证同样能产生那组症状（排障文档已写）。
- WKWebView 真机未验：窗口缩放手感、拖动帧率、后台线程 `set_zoom`。
- 5h↔周换算比只有 2 个号约 2 小时的数据；agy 的连续使用预测没做（Gemini 档仍是旧续航口径）。
- agy 真探针、agy 定时（默认关）、云端入账延迟都没在真机跑过；「需验证」链接在错误体里的位置无实测样本。
- `cargo test` 的两条 doctest（`build_number` / `LOG_SOURCES`）在 v1.9.6 上就红，未修。

---

### B78 · 续航「全池 98.6 小时」与「半小时几个号见底」— 2026-10-15 ✅（v1.10.0）

用户：「codex 的全池续航≈98.6 小时，为什么还是那么多？实际使用下来会出现不到半小时几张账号额度都没了」。
**根因**：99.5h = 周窗共剩 570pp ÷ 5.7pp/h，而 5.7pp/h 的分母是 2.1h 的**钟点跨度**，里面大半是空闲。单位写的是「小时（含空闲）」，
算术没错，但回答的问题不是用户在问的「我坐下来干活能干多久」；同时 Plus 号 5h 窗口实测几分钟就见底，周窗剩多少对「下一个小时」几乎没约束力。
**为什么会犯**：10-15 上午刚把「活跃小时」改成「小时（含空闲）」—— 修的是**名字与公式不符**，没回头问这个量本身对用户有没有用。
**修**：`codex-rotate::_burst` —— 现在 = Σ 可用号 min(5h 剩余分钟, 周剩余分钟)，每号分钟数用 5h 用完事件的连续使用配速（≥3 次，本号不够借全池）；
本周 = Σ 周剩余换算成 5h-pp 的分钟数（换算比 `_wk_per_5h`，≥50 个 5h-pp 才给）。实测此刻 ≈16 分钟、本周 ≈2.4 小时。
只改显示，代理挑号不动（用户选「改续航显示」）。Gemini 档仍是旧口径。
**闸**：`tests/test_burst_runway.py`（11 条，变异 10）+ `tests/test_runway_hero.py` 重写 + `tests/test_exhaust_eta.py`（18 条，变异 25）。

---

### B77 · 装机版更新 App 后轮换不生效，Connector 却报「已完成」— 2026-10-15 ✅（v1.10.0）

外部用户（GitHub 下载版）：codex 自动轮换不轮换；切号后 `Ctrl+Z` 退出再进还是原号。用户怀疑「更新后配置没到位」—— 对了一半。
**沙箱复现**（`scratch/sim_dmg_update_20261015.py`）：v1.9.6 的 `connector.plan()` 对一份 v1.8.0 的旧运行时报 `done` ——
它只看文件**在不在**，不看是不是这一版的。而 09-21 起「置顶」只有新代理认，旧代理照旧按老规则挑号。
同时接入检查对每台装机版都误报「入口 cxp 不存在」（只在数据目录根找，没找 `runtime/`），`RUNTIME_FILES` 漏了 `dawn_sched.py`。
**为什么会犯**：开发机是 clone 装机（`inplace=True`），走「原地用」分支，复制分支只在夹具里验过 —— v1.8.0 的「已知验证缺口」第 2 条写着它。
**修**：`connector.runtime_drift(src, runtime)` 逐字节比，缺文件/读不了都算漂移；有漂移时 runtime 与 services 两步都回到待做；
`codex-rotate integration` 新增 ⑦。已核实 v1.9.6 自带的 connector `apply --steps runtime` 能刷新文件，所以老用户一行命令即可（TROUBLESHOOTING 第 4 条）。
**未取证**：用户机器上的真因仍可能是另外几条（wrapper / `Ctrl+Z` 挂起 / `CODEX_HOME`），见 TROUBLESHOOTING 第 5 条。
**闸**：`tests/test_runtime_follows_app_update.py`（11 条，变异 10；「缺文件不算」为等价变异，标 green）。

---

## v1.9.6 — 2026-10-03

**重置卡「还剩多久」只有一种说法：角标、确认弹窗、菜单栏横幅统一向下取整（剩 1.3 天 = 「1天」，不够一天说小时）。**

v1.9.5 之后 1 个 commit。

### 修复
- 卡片页脚角标写「剩 2 天」、点进弹窗同一张卡却是「还剩 1 天」：三处各算各的取整，现在共用一个函数。
  最后一天角标会写「剩 N 小时」。
- 测试夹具不再依赖真实 `state.json` 里恰好有「停用轮换」的号（真状态里一个都没有时两条测试会红）。

---

### B76 · 重置卡「还剩几天」角标与弹窗对不上 — 2026-10-03 ✅（v1.9.6）

用户截图：角标写「1张剩2天」，点进弹窗同一张卡是「还剩 1 天」，口径要统一，**剩一天才是对的**。
**根因**：同一个量三处各算各的 —— `CardBadge` 与 `MenuBar` 横幅是 `Math.ceil`（注释理由：「10 小时不能标成 0 天」），
`UseCreditDialog` 是 `Math.floor`。剩 1.3 天的卡，角标说 2 天、弹窗说 1 天。
**修**：唯一实现 `helpers.ts::cardLeftText`（向**下**取整，不够一天说小时、至少 1 小时，所以「不能标成 0」那条顾虑也保住了），
三处都调它。副作用：角标最后一天会写成「剩5小时」而不是「剩1天」，菜单栏横幅同理（「5小时后作废」）。
**没动**：`useExpiryWatch` 的「订阅还剩 N 天」—— 那是**订阅**到期不是重置卡，另一个量、另一个口径，没有人报它不对。
**闸**：`tests/test_card_left_wording.py`（6 条：边界值 / 三处必须走同一个函数且不许手写取整 / 渲染后同一张卡角标与弹窗说法相同）；
3 个变异（helper 改回 ceil / 角标手写 ceil / 弹窗手写 ceil）全红。
**顺带修**：全量测试发现 `test_connector_oneclick` / `test_runway_hero` 两条闸红了 —— 与本次改动无关，是 harness 夹具取自真 `state.json`，
而用户把所有号放回轮换后真状态里**0 个**停用，这两条依赖「有停轮换的号」的闸一起失去判别力。改为夹具自己保证至少 3 个（从末尾补，不动前面的号），
不再靠真数据恰好长成那样。

---

## v1.9.5 — 2026-10-02

**账号卡可以直接用重置卡：点页脚「重置卡 ×N」→ 弹窗列出每一张、默认选最近到期的 → 确认用卡。**

v1.9.4 之后 4 个 commit。版本号按用户指定为 `v1.9.5`。

### 新增
- **使用重置卡**（`codex-rotate use-credit <号> [--card <id>]` + 界面）：入口只有页脚「重置卡 ×N」角标，点开确认弹窗，
  列出该号每一张卡（到期各不相同，按到期先后排，最近的默认选中，可改选），确认后用掉所选那张。
  额度没见底也能用（用户实测）；用掉不可逆，所以必须弹窗确认（默认焦点在「取消」、回车不确认）。
  成败只认服务端的「重置了几个窗口」；重试复用同一个请求号，不会多用一张。

### 修复
- 价格表补上本机新出现的 `gpt-6.1-sol`（新增的「CLI 能跑的模型都得有价」测试当场抓到）。
- 一条偶发红的 Rust 测试（并行时两条测试可能拿到同一个临时目录）。

### 已知未解
- agy token 统计的真库检查两条红（字段漂移还是 agy 没走缓存，未判别）；5 个号 `refresh_token_reused` 需要重登。

---

### B75 · 账号卡新增「使用重置卡」（用最近到期的那张）— 2026-10-01 ✅（v1.9.5）

**需求**（用户）：在账号上新增功能，使用重置卡，用最近日期的那张。
**端点（实测，不是猜的）**：`strings` codex 二进制找到 `/api/codex/rate-limit-reset-credits/consume`，与读明细同族 ⇒
`POST /backend-api/codex/rate-limit-reset-credits/consume`，请求体 `{"credit_id", "redeem_request_id"}`（第一次只给
`credit_id`+`idempotency_key` 被 400 `redeem_request_id: Field required` 纠正），回 `{"code","credit","windows_reset"}`。
**零花费的判别实验**：对一个**当时没有可重置窗口**的号发一个**不存在**的 credit_id ⇒ `200 {"code":"no_credit","credit":null,
"windows_reset":0}`。该号有 3 张真卡，若服务端忽略 credit_id 就不会报 no_credit ⇒ credit_id 被认了；不存在的卡不花任何东西。
**这是全 app 唯一不可逆的花费动作**，所以：
- `codex-rotate use-credit <label>`：~~只在 `applicable > 0` 时才发~~ **同日用户实测「额度没见底也能用卡」并要求放开，闸已撤**
  （服务端是最终裁判，成败只认 `windows_reset`，前后张数核对；服务端若对「没窗口」也扣卡不重置会白花一张，张数对比就是证据）；
  选**最近到期且有到期日**的那张（没日期的不选：不知道多久过期 ≠ 最近）；
- `redeem_request_id` **先落盘再发**，没确认成功就复用同一个 —— 网络在发出后断了，重试不会换新号多用一张；
- **成败只认 `windows_reset > 0`**；200 但没重置窗口是「没生效」，请求结果未知既不报成功也不清请求号；发完再免费读一次核对张数。
- 界面：（最初做过动作条里的 `用卡 MM-DD` 按钮 + 两段确认，已因**很容易误触**取消。）
  ★ **入口只有页脚「重置卡 ×N」角标**（用户提议；动作条里的「用卡」按钮因**很容易误触**已取消）。点角标弹**确认弹窗**
  （`UseCreditDialog`：**列出这个号的每一张卡**（到期各不相同，按到期先后排，最近的标「最近」并默认选中，可点选 / 上下键改选；还没取到到期日的几张只说「另有 N 张到期未知」、不可选），确认时把选中那张的 id 用 `--card` 传给 CLI——CLI 会用**新取的明细**核对它仍可用，不可用就不发、绝不退回去用另一张；写明用后剩几张、不可逆；默认焦点在「取消」、回车不会确认、Esc / 点遮罩 / ✕ 都是取消；
  不用系统 `confirm()`——WKWebView 里不可用）；点角标不触发卡片选中。结果原话（用了哪张、重置几个窗口、剩几张）进 toast。
**验证**：用户 2026-10-01 真用过，「效果不错」；服务端成功时 `code` 的取值我仍不知道（所以成败不看 `code`）。
**闸**：`tests/test_use_credit.py`（23 条：选卡 / 结果分类 / 流程 / 白名单 / 弹窗全流程——点角标不发、回车不确认、取消三路都关、点确认恰好发一次）。
变异 9 个全红 —— 其中 2 个**第一次是绿的**（`a.cardsUsable > 0` 这几个字在不可点分支的 title 里也出现，只查子串等于空守卫），已收紧到三元条件本身。

---

## v1.9.4 — 2026-09-29

**修复 v1.9.2 起就存在的四个接入 / 安装缺陷（v1.9.2、v1.9.3 都带着它们）。**

### 修复
- 「一键接入」报 Python Traceback：安装脚本里 `$rc，`（变量后紧跟全角逗号）在 macOS 自带 bash 3.2 下变成 `unbound variable`，
  真错误被乱码取代；`connector.py` 读脚本输出时对非法 UTF-8 也不再抛异常。
- 「撤销接入」会误删用户自建、只是指向仓库内某个路径的命令入口：归属判断改成与安装时逐字节相同的精确比较。
- 从 GitHub 更新 CodexBar 后账号「全丢」、无法刷新：安装包没有构建期写死的数据目录，落到了空目录；
  现在会接上已经在用的那个（自己已有数据 > 已安装代理正在读的目录 > 约定的仓库位置 > 新建）。
- 服务被 `launchctl disable` 过时 `bootstrap` 报 I/O error：安装前先 `enable`；一个服务装不上不再挡住其余，最后统一报错。

### 新增
- 4 组测试守住上述四点（shell 脚本变量后紧跟多字节字符扫描、有状态 launchctl 桩、入口归属、Rust 数据目录选择）。

### 已知未解
- 5 个号 `refresh_token_reused` 无定论，需要重登；agy token 统计的真库检查两条红（字段漂移还是 agy 没走缓存，未判别）。

### B74 · 「一键接入」报 Traceback / remove 误删入口 / 从 GitHub 更新后账号「丢失」/ 服务装不上 — 2026-09-29 ✅（v1.9.4）

来源：`~/Downloads/mimo-incident-20260926/`（mimo 会话记录 + 一份归因整理）。**那份整理声称修复已提交（`8faf3c6` / `e4635a1`），
本机所有仓库里都没有这两个 commit —— 修复根本没落盘，所以 v1.9.3 里四个缺陷全都还在。** 逐条独立复现后重修：
① **`install-launchd.sh:125` 的 `$rc，`**（v1.9.2 起）：bash 3.2 在 UTF-8 下把全角逗号首字节吞进变量名，实测
  `rc�: unbound variable`。只在「服务装不上」时才走，真错误被换成乱码，stderr 的非法 UTF-8 又让 `connector.py`
  `text=True` 抛 `UnicodeDecodeError` ⇒ 设置页里是一份 Python Traceback。→ `${rc}` + `connector.py` 两处
  `subprocess.run` 加 `errors="replace"`。
② **`connector.remove` 子串判归属**：`str(store) in tgt`，而 `plan()` 是精确比较。→ 精确比较，目标与 `apply()` 逐字节相同
  （用 `_runtime_dir`，clone 装机时 store 自己就是运行时；第一版收紧后**一个都撤不掉**，加了反向闸）。
③ **CI 出的 .dmg 没有构建期烧录值 ⇒ `data_dir()` 落到空的 `app_data_dir()`**：clone 装机的机器从 GitHub 更新后账号
  「全丢」，其实数据还在原仓库目录、launchd 的代理还在读它，app 与服务分叉。→ 新增 `pick_data_root`：
  自己已有 `state.json` > 已安装代理 plist 里的 `CODEX_ROTATE_STORE` > 约定位置 > `app_data_dir()`；**只认含 `state.json` 的目录**。
④ **服务被 `launchctl disable` 过就 `Bootstrap failed: 5: I/O error`**，且 `set -e` 让一个失败挡住其余。
  → bootstrap 前先 `enable`（只动我们自己的 label）；`emit … || FAILED=…` 收集失败、其余照装、最后非 0 退出。
**没做**：#6（5 个号 `refresh_token_reused`）无定论，需要重登；79 项 LaunchAgent 的 disabled 是本机状态，仓库改不了。
**闸**：`test_shell_var_before_multibyte`（扫全部 shell 脚本，先证扫描器对已知坏行会响）· `test_installers_pass_the_store`
（有状态的 launchctl 桩，`/bin/bash` 3.2 + UTF-8：验 disabled 会被 enable、一个失败不挡其余且报错可严格解码）·
`test_connector`（外来 symlink 不删 + clone 装机撤得掉）· `test_rust_store_pick`（6 条 Rust 单测接进 unittest，CI 只跑 `cargo check`）。
各闸的变异全部变红。

---

## v1.9.3 — 2026-09-29

**四家牌价按官方页重取，费用列不再有「兜底价」的模型。**

### 修复
- 费率表补齐并更新：Claude Fable 5.1 / Opus 5.5 / Sonnet 5.5 / Mythos 5.1，Codex `gpt-6-astra` / `gpt-6-sol` / `gpt-6-luna`
  以及降价后的 `gpt-5.6-sol`（$5/$30 → $4/$20），Gemini 3.8 Flash，Grok 4.7。此前这些在跑的模型全走平台兜底价。
- 缓存读折扣不再一律按输入价 10%：Fable 5.1 是 2.5%、Opus 5.5 是 5%。
- 真快照全窗口按当前牌价重算：合计 $42,585 → $40,963（历史日的等效成本随牌价整体移动）。

### 新增
- 测试守「本机 CLI 能跑的模型都得在费率表里」（读 `agy models` / codex 模型缓存 / `grok models`）。

### 文档
- README / `traffic.md` 里「缓存读一律 10%」的说法更正；两处 2026-08-16 的费用量级标注为旧牌价。

### B73 · 费率表落后于各家牌价：7 个真在跑的模型全走兜底、gpt-5.6-sol 用着旧价 — 2026-09-29 ✅（v1.9.3）

用户：「搜索下 claude、codex、gemini、grok 不同模型的价格，一并更新去 AI 用量」。四家官方定价页 2026-09-29 逐家取回，
再拿**真快照里出现的模型**对表 —— 修前 `claude-fable-5-1` / `claude-opus-5-5` / `claude-sonnet-5-5` / `gpt-6-astra` /
`gpt-6-sol` / `gemini-3.8-flash(-high)` / `grok-4.7-build` **都不在 RATES 里**，走平台兜底价、费用列标 `*`。
**牌价变动**：Fable 5.1 缓存读 $0.25（2.5%，不是 10%）· Opus 5.5 $4/$20、缓存读 $0.20（5%）· Sonnet 5.5 $2/$10 ·
`gpt-5.6-sol` **$5/$30 → $4/$20** · `gpt-6-astra` $10/$50 · `gpt-6-sol` $2/$10 · `gpt-6-luna` $0.1/$0.5 ·
Gemini 3.8 Flash 与 3.7 同价同促销（2026-12-31 后翻倍）· `grok models` 默认已是 4.7（$2/$6，缓存读 $0.5）。
**影响（真快照全窗口，按当前牌价重算）**：合计 **$42,585 → $40,963**。逐项：`gpt-5.6-sol` $6,426→$4,997（旧价过高）·
`claude-opus-5-5` $1,777→$957（兜底按 Opus 5 高估）· `gpt-6-astra` $500→$978（兜底按 sol 低估）·
`claude-fable-5-1` $1,058→$1,272（缓存读 2.5% 拉低了兜底的高估，但 Fable 输出价更高）。
费用是**当前牌价 × 历史 token**，所以历史日的数字会跟着牌价整体移动 —— 这是牌价变了，不是数据变了。
**没做**：长上下文档（OpenAI/Grok/Gemini 3.1 Pro 提示词 ≥200k 整单进高档）—— 我们按天分桶、看不到单次提示词长度，
长会话仍会低估，已写进 `rates.ts` 各家标题注释。Kimi / MiMo / DeepSeek 不在本次范围。
**闸**：`tests/test_rates_cover_live_models.py`（6 条，3 个变异全红）—— 以 `agy models` / `~/.codex/models_cache.json` /
`grok models` **自己列出的可用模型**为准，谁不在表里就红（本机没装则 skip）；另守「兜底价 = 它声称的那一档」。
顺带：`test_agy_model_names` 的真值表补上 3.8 三档（原表停在 3.7，是它没跟上 `agy models`）。

---

## v1.9.2 — 2026-09-24

**Gemini 账号版块与 Codex 统一。**

### 修复
- Gemini 档补上顶栏「最近刷新 · N/M 新鲜」一行（数 Gemini 池各号的读取时刻，文案与 Codex 档共用一份实现）。
- Gemini 卡补上停用轮换的 ⊘ 角标。
- Gemini 卡底部多出的 23px 留白（页脚折成两行，179px → 156px，与 codex 卡等高）。
- CHANGELOG 里 v1.9.1 一节放错位置（在 v1.9.0 之下）。

### 文档
- README / AGENTS.md / CLAUDE.md 补上代理轮换 Gemini 版块的口径与 `traffic/agy_rotation.py`。

### B72 · Gemini 账号版块三处与 codex 不统一 — 2026-09-24 ✅（v1.9.2）

用户点名（「这些都是 gemini 账号版块做不到位、不统一的地方」），修前 harness 1300×900 实测：
① 顶栏右侧「最近刷新 · N/M 新鲜」只在 Codex 档有 —— Gemini 档补上同位同形的一行，数的是 **Gemini 池**各号的
  `quota_at`，阈值同一条 `QUOTA_STALE_SEC`；文案抽成 `helpers.ts::freshnessLine` 两档共用（两处各写迟早只改一边）。
② 停用轮换的 ⊘ 角标只画在 codex 卡上 —— `AgyCard` 补上，同位同色（琥珀）。
③ **Gemini 卡 179px vs codex 卡 156px**：页脚写成 `flexDirection: column`，隐形占位徽章自成第二行，
  多出来的 23px 全是底部空白。改成与账号卡同构的单行页脚后三张都是 156。
闸 `tests/test_gemini_overview_parity.py`（5 条，渲染后的页面上量；3 个变异——页脚改回两行 / 去掉 ⊘ / 去掉新鲜度行——
每个都重建 bundle 后变红）。三条旧闸的锚点跟着文案搬家（判据不变：`unknown` 进分母、codex 那行只数 codex 池）。

---

## v1.9.1 — 2026-09-24

**Gemini 额度读数恢复真实、轮换规则与 codex 对齐；日志页「代理轮换」分成 Codex ｜ Gemini 两个版块。**

v1.9.0 之后 6 个 commit。版本号按用户指定为 `v1.9.1`。

### 新增
- **Gemini 轮换按 codex 的规则**：每次启动 agy 挑容量最高（5pp 迟滞）、置顶插队、池子空时借用开关、「下一个」单一实现；
  Gemini 总览换成 `RunwayHero`（B70）。
- **日志页「代理轮换」Codex ｜ Gemini 切换**：Gemini 版 = 会话泳道 + 换号 / drift 事件，不按号记 token（B71）。

### 修复
- **Gemini 额度恒 100%**：云端额度摘要改读 `daily-cloudcode-pa`（agy 1.2 实际用的后端）（B69）。
- **Gemini 额度刷新不及时**：后台保鲜 + 各号并行拉取（8.4s → 2–3s）+ agy 1.2 本机接口 `csrf_required` 如实分类并退避（B68）。
- **代理轮换页闲置时刷出「200 断流」**：免费的 `GET /models` 挂断不再算已计费断流；代理对 `/models` 向上游要 gzip（B67）。
- **Connector 对手写 provider 表补 `supports_websockets = false`**（B66）。
- 测试隔离加固：一次测试把夹具写进真钥匙串的事故，源头拒写非 Google 签发凭证 + 每个起子进程的测试模块强制导入隔离（B70）。

### B66 · 横幅喊「WS 没关」、Connector 说「已接入」—— 发版修不到的老用户 — 2026-09-23 ✅（v1.9.1）

用户转来的反馈：「更新后还是提示 WS 没关」。原理本身属实（WS 端点硬编码 `wss://chatgpt.com`、不认 `base_url`），
但问的是**为什么发版修不到**。三层叠在一起：
① v1.0.0~v1.6.1 的 `docs/INSTALL.md` 给的 provider 块只有 name/base_url/wire_api，**没有** `supports_websockets = false`
   （v1.7.0 才补）—— 照旧文档手工接入的人全缺；
② 更新只换 bundle，`~/.codex` 原样不动；v1.7.0 加的是**检测**不是修复；
③ Connector 只看「有没有 `[model_providers.rotateproxy]` 这个标题」，有就报 `external`（"它在工作，不碰"）⇒
   **同一台机器上两处说法相反**，一键接入无事可做。形状：**`external`（你自己写的）被当成了「它在正确地工作」**。
修：Connector 多一步 `ws` —— 只在存在用户自写的 provider 表时出现，缺这一行即 `todo`，apply 只往**那张表**
补一行（或把显式 `true` 改成 `false`），表外一个字节不动；profile overlay 里的同名表一并处理。
顺带抓到**闸自己的假绿**：接入闸把 profile **整份文件**当干草堆，而 Connector 写在 profile **顶层**的
`supports_websockets = false` 不在任何 provider 表里（codex 二进制里该键只出现在 provider 字段组中，顶层大概率
被当未知键忽略）⇒ provider 表没关也报绿。现只认两份文件里 `[model_providers.rotateproxy]` 表内的值，任一张表显式
`true` 即判没关。闸：`test_connector.py::AHandMadeProviderWithoutWsIsNotDone`（8 条，含「Connector 与接入闸必须
同答」的不变量，夹具是旧 INSTALL.md 的原样块）+ `test_codex_integration_gate.py` 3 条；5 个变异全红。
⚠️ 「profile 顶层那一行无效」是按二进制 `strings` 的字段分组推断，**没做对照实验**（交互式会话里开/关看 WS 连接数）；
   修法在两种情况下都成立（只认表内值 ⇒ 顶层行有效与否都不会误报）。

### B67 · 「我明明没用，为什么一直 200 断流」—— 免费的模型列表刷新被标成「已计费断流」— 2026-09-23 ✅（v1.9.1）

**现场**：6h 窗口「断流 60 / 请求 0」，全在一个号的泳道上，每条事件写「已 200 后断流,**已计费**」。
**来源**（codex 自己的 `logs_2.sqlite` 与 proxy.log 逐条对齐，137/137）：一个开着没关的 `codex --profile rotateproxy resume`
（0.156.0，08:51 起、11:50 之后闲置）后台 `list_models{refresh_strategy=online}`，**固定 270.0±0.1s 一次**
（0.154.0 也一样，不是新行为）。codex 给它的预算 **5 秒**（59 个超时样本全落在 5.00–5.05s）；代理 ~2s 回头、
body **522 KB 明文**还在传，codex 自己关连接 ⇒ 代理写 EPIPE ⇒ `stream err … Broken pipe`。当天 136 次里 80 次（59%）；
0.154.0 历史上 2.3% 且从不报 ERROR。为什么 0.156.0 高一个数量级**未定**（预算缩短/去掉容错/上游时段吞吐都能解释；
上午 0/30、13 点 13/13、18 点 7/13），旧二进制已被 npm 覆盖、无法对照。
**两层修**：
① **显示**（真正的 bug）：`traffic/rotation.py` 看到 `stream err` 一律算计费，而代理自己早按 `_billable()`（非 GET/HEAD）
   过滤了计费计数 —— **同一条规则两处实现不一致**。现按 `#rid` 回查请求方法，GET/HEAD 的断连不进 KPI/泳道/事件/「断流 → 轮换」归因；
   认不出方法仍按计费算。
② **减少超时**：假上游抓包实测 codex 0.156.0 请求 `/models` **不带 Accept-Encoding**（10/10；POST 30/30 也不带），
   代理的 http.client 替它发 `identity`。现对 `GET …/models` 向上游要 gzip（103 KB）、本机解压后交明文；SSE 的 POST、
   其它 GET、客户端自己要了 gzip 的一律不动；坏 gzip ⇒ 干净 502（还没发头、GET 免费可重试）。
   实测（修前，经代理）明文 3.1–3.7s / gzip 2.6–2.9s，首字节 ~2s 占大头 ⇒ **只降概率、不保证根除**。
闸：`test_rotation_free_hangups.py`（11 条，当天原样行作夹具，含与 `proxy._billable` 逐方法同答的不变量）+
`test_proxy_models_gzip.py`（7 条，真起代理 + 假上游）；10 个变异全红。

### B68 · 「gemini 的额度刷新不及时」—— 本机实时源随 agy 1.2 失效 + 云端只在看着时才前进 — 2026-09-23 ✅（v1.9.1）

**① 本机实时源死了 22.5 小时没人发现**：`.agy-quota.json` 自 **09-22 22:32** 起每分钟 `HTTP 401`，与 agy CLI 1.1.x→1.2.x
自动升级同夜（今天 19:22 又到 1.2.9）。起一个临时 agy 实测（交互态不发 prompt、零额度）：不带 token ⇒
`401 missing CSRF token`；用二进制里出现的 `ANTIGRAVITY_CSRF_TOKEN` 自设 ⇒ `invalid CSRF token`；日志、进程环境、
`presence/`（全是空锁文件）里都没有它。**短期修不回来。** 而 UI 对这个 401 说的是「下次刷新会自动重试」—— 修不好的状态上
挂着一句"会自愈"，于是没人去看。
**② 云端（`retrieveUserQuotaSummary`，零额度、按号）只在 Gemini 档开着时才前进**：当天 01:24 刷过一次，下一次是 20:46 用户打开时。
**修（用户逐项拍板 1/2/3 全做）**：
1. **后台保鲜**：菜单栏 webview（开机即建、从不卸载）按同一个 10 分钟阀在后台取，不看 Gemini 档、不看可见性；仍受「后台自动刷新」开关约束。
   ⚠️ 这**反转**了「没人看就不联网」的旧设计（用户 2026-09-23 拍板）。成本：零额度，只联网。
2. **各号并行**：`agy-rotate quota` 实测 **8.4s → 2.1–3.0s**（3 个号，3 次）；落盘仍一次、持锁。
3. **如实分类**：`agy-quota` 把含 `csrf` 的 401 落成新 reason `csrf_required`（不再混进「会自动重试」的 `rpc_error`），
   文案说明「已改用云端读数、↻ 可立即刷新」；采样器见 sidecar 一小时内刚确认过就**起手退出**
   （app 每 60s 看锁补拉它 —— 只在循环里 break 等于每分钟重生一次），每小时仍真试一次以便 agy 哪天放开时自愈。
闸：`test_agy_quota_timely.py`（9 条：恰好一个 webview 驱动 / 后台不看可见性 / 并行总耗时≈最慢者且不串号 / 退避与锁序）
+ `test_agy_degrade_contract.py::test_csrf_401_is_its_own_reason_not_rpc_error`；7 个变异全红。

### B69 · 「5h 配额都没减少，数据不合理」—— 额度摘要一直打的是旧后端 — 2026-09-24 ✅（v1.9.1）

**真因**：agy 1.2.x 的后端换成了 **`daily-cloudcode-pa.googleapis.com`**，而我们一直打 `cloudcode-pa`。
两边同 token、同请求、都回 200、形状一模一样 —— 旧 host 只是**永远回「四桶 1.0 + resetTime = now + 窗口」**。
自 09-21 17:35 起 54/54 次如此；44 次真实运行（2.3M token）与一次受控探针（13,934 token，身份已证）之后都纹丝不动。
**怎么找到的**：codex（gpt-6-astra/high）建议先拿 agy 自己的 `/usage` 做对照。驱动一个一次性 agy（设 pty 窗口大小，
只发 `/usage`、零生成），状态栏显示 `⏱ 77% (05:32) · 📅 96%` ⇒ agy 看得到真数，是我们读错了地方。
排除项：`project` 字段（`aicode-consumers`）、新版 User-Agent、OAuth client（`aud` 相同）、`fetchAvailableModels` 逐模型额度
（27 个模型也全 1.0 —— 同样是旧后端）。二进制 `strings` 里 `daily-cloudcode-pa` 与生产 host 并列，一试即中：
sam 5h 0.717 / 周 0.948，5h 重置 21:32:22Z = 05:32 SGT，与状态栏逐分钟对上。
**修**：`agy/pool.py` 新增 `QUOTA_API_HOST = "daily-cloudcode-pa.googleapis.com"`，`fetch_quota` 改用它。
修后实测：sam gemini 68.5%、dbk 92.8%、doushutangmu 100%（当天确实没用）。
⚠️ **修正一条错误结论**：B68 里「本机 RPC 失效后云端成了唯一来源」本身成立，但「云端 100% 是真数」不成立 —— 当时读的是空账本。
⚠️ 附带：agy 这一侧的咨询两次都失败（omc 5 分钟超时；直连 `agy -p` 空输出），结论只来自 codex + 实测。
⚠️ 另一个仍然开着的：钥匙串当值号在排查中途从 dbk 被冲成 sam（常驻 agy 进程写回，已知机制），
   所以「哪个号在消耗」必须看 agy 日志的 `applyAuthResult`，不能看我们以为装进去的号。
闸：`test_agy_quota_timely.py::TheQuotaSummaryGoesToTheHostAgyActuallyUses`（行为闸，退回旧 host 即红）。

### B70 · Gemini 轮换与总览按 codex 的规则对齐 + 一次测试污染真钥匙串的事故 — 2026-09-24 ✅（v1.9.1）

**需求**（用户逐项拍板）：换号时机「每次启动挑容量最高」；同步置顶插队、借用开关、「下一个」单一实现；
总览照搬 codex 的 `RunwayHero`、续航先显示「—」。
**实现**：
- `agy/pool.py` 新增**唯一**选号实现 `usable / pin_rank / sort_avail / pick / board`，规则照搬 `proxy.py`：
  置顶 > 容量（未置顶全部并列）、迟滞 5pp（不跨置顶档）、停用 / 凭证失效 / 见底（< 15%）不选、读不到排最后、
  池子空时按 `borrow_off` 决定借不借。`live_wanted`（手动切换）**只在那个号仍可用时兑现** ——
  旧实现兑现后直接 return，一次手动切换就让轮换永久失效，还会把见底的号装回去。
- `agy-rotate`：`auto` / `pick` 改调 `pool.pick`；新增 `next --json`（与 `codex-rotate next --json` 同形）/ `pin` / `borrow`。
- App：只读 IPC `read_agy_board`（不 emit）；`useRotationBoard` 加 `source: "agy"`；Gemini 总览换成 `RunwayHero source="agy"`
  （三处说法改成 agy 的真话：启动时借用 / 额度见底 / 没有消耗记录）；卡片「下一个」+ 置顶按钮与角标；菜单栏行「下一个」；
  设置页「Gemini 池子空时借用已停用的号」。删掉前端自排的 `agyBest`（最优 / USE / 建议切到 X）。
- **被取代的闸**：`test_agy_rank_common_basis.py`（整份删除）与 `TheGeminiTabHasAHeroLikeCodex` —— 它们守的是被撤掉的
  前端排名；「界面报的号 = 真挑号器会挑的号」由 `test_gemini_follows_codex_rotation.py` 接着守（18 条，6 个变异全红）。
**★★★ 事故（当场发现当场修）**：为跑 agy 相关测试用了 `discover -s tests -p 'test_agy*'` —— 这种按文件名过滤的跑法
**既不导入 `tests/__init__.py`、也匹配不到 `test_isolation_bootstrap.py`**，`AGY_KEYRING=0` 没被设置 ⇒
测试夹具 `new@x.y` 被 `install_live` **写进了用户真实的 agy 钥匙串**，`auth/agy/new.json` 落进真凭证目录，
还有测试经 `bin/agy` 对**真账号池**跑了 `auto`。已恢复（`agy-rotate switch dbk`，钥匙串核对为 dbk；删掉 `new.json`；池 3 号完好）。
修法不是「记得设变量」，是两道**与跑法无关**的闸：
① 源头：`keyring_write` 拒写非 Google 签发（`id_token.iss`）的凭证；真实默认路径的兜底文件同样拒写；
② 隔离唯一实现 `tests/_isolation.py`（另把 `AGY_POOL_STORE` 指到临时目录），**每个会起脚本子进程的测试模块自己 import 它**；
   闸 `EveryScriptSpawningTestImportsTheIsolation` 当场扫出另外 **17 个**漏了隔离的模块（已补），
   第一版只查子串被变异证明是空闸，已改成两支都要。

### B71 · 日志页「代理轮换」分成 Codex ｜ Gemini 两个版块 — 2026-09-24 ✅（v1.9.1）

**需求**（用户拍板）：标题行放分段切换（Codex ｜ Gemini）；Gemini 版 = 会话泳道 + 换号事件。
**实现**：新模块 `traffic/agy_rotation.py`（纯函数，只读本机日志与池文件，输出与 `rotation.collect` 同形 +
`platform: "agy"`，实测 0.2s）；只读 IPC `read_agy_rotation`（不 emit，已进安装包 resources）；
`LogsPage` 的 `Seg` 选中态记在 localStorage `codexbar_rot_plat`。
**口径**（agy 没有代理，能诚实拿到的只有两样）：
- 泳道段 = **agy 以这个号的身份在运行**（`cli-*.log` 文件名时间 → mtime），身份取 agy 自己日志的
  `applyAuthResult: email=`；同一份日志里身份变了就**切段**；认不出身份的会话**不归属**，计入 `responses_unplaced`。
- 换号事件来自 `agy.log`（自动 / 恢复成你选的 / 借用 / 手动）；**身份变了却没有换号记录**单列成 drift 事件
  ——「多半是某个仍在跑的 agy 把钥匙串写回了自己的身份」。
- **不按号记 token**：agy 的用量账本不带身份，按时间拼是猜。token 列显示「—」，请求改叫「会话」，
  429 / 断流 / 均每次三项在 Gemini 版不显示。
**踩到的一个真错**：日表「在岗」第一版把各会话时长**求和**，真机算出单日 139,633s（> 86,400）——
本机常有好几个 agy 同号并发。改成**区间并集**（dbk 当天 39,616s）。
**闸**：`tests/test_agy_rotation_lanes.py`（11 条，5 个变异全红：认不出也猜 / 中途换身份不切段 / 并集改求和 /
drift 并进 switch / Gemini 版运行日志重复并入）。
顺带修一条被新夹具戳穿的闸：`test_connector_oneclick` 数「停轮换角标」的期望值时对**整份** harness 计数，
新内联的 Gemini 轮换夹具也带 `"rotate_off": true` ⇒ 期望 4、实画 3 的假红。改为只数 `var STATE = …;` 那一份。

---

## v1.9.0 — 2026-09-23

**轮换回到「容量最高优先」，想先用谁就点亮它；总览顶部改成续航条，一眼看出谁在用、下一个是谁、还能撑多久。**

v1.8.0 之后 37 个 commit。两条主线：**选号规则说清楚、只算一份**，以及**卡片交互重做**。
中间在 2026-09-21 造出过一次事故（自激回环把机器吃满），当天定位、修复、上闸。

### 新增

- **置顶插队**（`codex-rotate pin`，卡片动作条 📌）。默认按容量最高优先，点亮的号先用，
  可点亮多个、按点亮先后排队。反转了 v1.8.0 之后一度上线的「拖拽顺序 = 优先级、压过额度」——
  那一版给**每个号**都排了名，于是「已用%」那一段永远说不上话。新的 `_pin_rank` 只差一处：
  **未置顶的号全部并列**，容量立刻接管。排序键 `(套餐档, 置顶位次, 最紧窗口已用%)`。
- **总览卡片可拖拽排序**（⠿ 手柄，⌘N 跟视觉顺序）。**只影响摆放，不影响轮换。**
- **续航条**（替换旧 banner）：环 = 代理**最近真正用的号**（`last_aid`，写多久前）；
  右侧 = 全池还能撑多少**活跃小时**（样本不足显示 `—`，绝不写 0）+ 按周余量成比例的色带。
  「下一个请求会用谁」只有一份实现：`codex-rotate next --json` import 真的 `proxy.py`。
  旧 banner 的两个前提都已不成立：「当前使用中」读的是上次 CLI 切换，「建议切到 X」既不看置顶也不看停用。
- **池子见底告警**：一个能用的号都没有时，顶部实心红底徽章 + 各有几个（冷却/停用/失效）+ **最快几分钟后回来**
  + 能动的那个旋钮；代理临时借用的号标「临时借用」。见底时**不画续航数字**（那一刻恒为 0，是假话）。
- **「池子空时借用已停用的号」开关**（设置页，`codex-rotate borrow --on|--off`，默认开 = 原行为）。
  用户原话「我明明停止轮换了，应该就不能去调用」。关掉后代理直接失败并在日志写明「是你自己关的」。
- **按号停用轮换的角标 ⊘**；**Connector 一键接入**（主按钮 = 必需的 5 步，次按钮 = 连 `codex` 一起接管）。
- **日志页**：每号 × 每天在岗表（回答「置顶到底生效没」）；泳道窗口加 14d / 30d。
- **中转站余额手动刷新**（页头，与「刷新全池」同形）+ 旧读数披露。

### 改进

- **卡片动作条改为浮层**：点卡片从底部浮出，卡片高度三态恒为 156px（原 156 → 203，整排跟着涨）；
  **5 秒后自动收回**（用户同日 30 → 10 → 5 秒），收回动画 = 入场倒放（140ms），底边 2px 倒计时细线；
  **macOS 式半透明磨砂**（.66 + 20px 模糊 + 提饱和，深浅两档）。codex 卡与 Gemini 卡共用 `CardActionBar`。
- **「谁在用」只剩一个答案**：卡片 `USE` → **下一个**（真挑号器 `board.next`，原来是「剩余最多」、不看置顶停用，
  会指向代理不会挑的号）；`当前` → **直连**（它是 `auth.json` 里那个号）；动作条 `✓ 当前` → `✓ 直连`。
- **菜单栏跟着代理走**：托盘标题与弹窗高亮 = 代理此刻在用的号（`last_aid`），行内文案「在用」。
- **AI 用量「今日」一格一小时**（原每 2 小时一格，交接稿 §5 的做法；用户改）。
- 三档卡片右上角统一（Gemini/grok 的 ↻ 与拖拽手柄叠在同一个角，删掉）；动作条绝不换行
  （根因是网格写死 3 列，改 `auto-fill minmax(320px)`，不是按钮）；全 app 悬浮提示「一次只出一个说法」。
- 代理轮换：窗口完整度改三态（`tail_truncated` 原来判的是「文件 > 6MB」，9.1MB 后恒为真、
  真截断那天反而看不出来）；读尾巴改为按窗口加倍读（24h I/O 6MB → 0.52MB）。

### 修复

- **B60** 拖拽「不流畅」四轮 → 两个真因（正本 `CLAUDE.md` §7.2）。
- **B61** 续航条造出 `state-changed` 自激回环（**12 秒 789 个 python 子进程**）；陈旧 bundle 静默顶替新版。
- **B62** 「谁在用」三个答案；`USE` 说谎；「临时借用」红灯描述 3 小时前的事。
- **B63** 抽 `usable()` 时兜底分支留下 `NameError`（池子最紧张那一刻才炸）。
- **B64** `deploy.sh` 被自己的管道 SIGPIPE 静默杀掉（时好时坏）+ 同形 3 处。
- **B65** 测量仪器撒谎两例：虚拟时钟不推进 CSS 动画；浅色主题根本没切过去。
- Connector「只能勾选准备运行时」：判「原地用还是复制」改看 store 里有没有运行时，不看 `src == store`。

### 闸

全量 **1663** 条通过（v1.8.0 时 1432）。新增：`test_no_event_feedback_loop`（回环 + 只读查询不许走写通道）·
`test_no_undefined_names`（pyflakes F821，CI 同步装 pyflakes）· `test_runway_hero` · `test_one_answer_to_who_is_in_use` ·
`test_menubar_follows_proxy` · `test_card_action_bar`（**真渲染像素**量磨砂对比度）· `test_deploy_script_sigpipe` ·
`test_pin_and_capacity` 等。每条新闸都做过变异验证（含「整个删掉」方向）。

### B60 · 拖拽「不流畅」连报四轮：命中测试不幂等 + 拿指针代替卡片 — 2026-09-20 ✅

三轮「修好了」都没用 —— 每一轮闸都是绿的，因为**没有一条闸真的拖过东西**。
两个缺陷都在同一段 ~8 行的命中测试里：① 槽位按下时冻结、`slot[i].aid` 是「原来住谁」，
而预览顺序每帧在变 ⇒ **指针不动，顺序每帧来回翻一次**（同坐标连发 8 次 pointermove 得到 2 种布局），
170ms 的过渡每 ~8ms 被重启、永远播不完；② 手柄在卡片右上角，指针领先卡片半列 ⇒
让位阈值约 8% 列距（修后 52%）。全文与判别实验在 `CLAUDE.md` §7.2（正本，这里只留指针）。
★ 可复用的判别法：**坐标停住、同一事件连发 N 次，状态最多变一次且与 N 无关。**

### B61 · 自激回环 789 个子进程 / 12 秒；陈旧构建静默顶替 — 2026-09-21 ✅ ★事故

**症状**：用户报「一直在闪来闪去，退出重开才好」+「菜单栏 AI 用量变成全量展示」+「线路崩了」。

**根因一（我引入）**：`useRotationBoard` 用 `run_rotate(["next","--json"])` 取数，又 `listen("state-changed")` 刷新自己；
而 `run_rotate` **无条件** `emit("state-changed")` ⇒ 自己喂自己。实测 12 秒 **789** 个不同 python 子进程（≈66/秒），
app CPU 16.3%。修后稳态 5 个 / 15 秒、CPU 0.1%。★ 这条规则当时**就写在** `read_integration` 的注释里
（「只读查询不要复用 run_rotate」），照样被违反 ⇒ 交付物是闸 `test_no_event_feedback_loop.py`
（从 lib.rs 现读「谁会 emit」，可达性解析，已知阳性自检两条）。
评审（agy + codex gpt-6 xhigh）另外抓到三处：`dawn-probe --status` 只读却走写通道（每 10 分钟全 app 抖一次）、
`ALLOWED_CMDS` 还留着 `next`（回环复活路径）、缺在途合流（20 条事件 → 21 次读）。
⚠️ agy 建议「`run_rotate` 只在成功时 emit」**没采纳**：`useBusyMirror` 的熄灯路径②明确依赖失败也 emit，
`dawn-probe` 失败前也会先写 `state="failed"`。codex 独立得出同样结论。

**根因二（独立）**：`~/archive/.../resume-compatibility-20260908/CodexBar.app` 是 **v1.4.1**，
与 `/Applications` 共用 bundle id，先抢到 flock ⇒ 新版每次启动判 `HeldByOther` **静默退出**。
用户对着 13 天前的构建看了很久。「今日画成全量」的真因是新旧 bundle **共用 `.traffic-latest.json` 而旧前端不校验契约**
（修复在 `03b008a`，v1.4.1 之后）。`deploy.sh` 现在核实「跑起来的是不是刚装的那份」。
★ 「线路崩了」并不是真的坏了：health 全绿，代理日志持续出 200 —— 是机器被吃满，codex 卡住像断了。

**判断失误的形状**：写新功能时复用了一条「看起来就是干这个的」通道，没去读它旁边解释「为什么另开一条」的注释。

### B62 · 「一个界面三个使用」；`USE` 说谎；红灯描述三小时前 — 2026-09-21 ✅

`正在使用 X 号 [临时借用]`（`last_aid`）· A 号卡 `当前`（`active`）· B 号卡 `USE`（`recommended()` = 剩余最多）。
三个概念、一种措辞。其中 `USE` 是**假话**：它不看置顶不看停用，B 号（置顶 #2）挂着 USE 而真挑号器说下一个是 A 号（#1）
—— 与同日从 banner 删掉的「建议切到」是同一份作废逻辑，换了个角标形态；菜单栏还另有一份。
「临时借用」只判了「这个号不可用」，而 `cur` 是 `last_aid`、天然滞后 ⇒ 池子早已恢复，红灯还在说三小时前的借用。
改为 `stranded && …`；闸需要专门的 `?pool=recovered` 夹具 —— 默认夹具里 `cur` 本来就可用，改不改都绿。
★ 用户同时追问「停止轮换了为什么还被调用」：不是 bug，是一个能用的号都没有时的兜底借用（日志写了 ⚠️，但用户不读日志）
⇒ 告警搬到总览 + 做成开关。

### B63 · 兜底分支里的 `NameError` — 2026-09-21 ✅

抽 `usable()` 时 `_pick` 的第二层兜底还调着已删除的 `rotatable` —— 那一支只有「一个干净可用的号都没有」才走到，
**池子最紧张那一刻才炸**，日常一个请求都碰不到。`test_rotate_toggle` 碰巧抓到。
⇒ 新闸 `test_no_undefined_names.py`（pyflakes F821，含空输入断言 + 已知阳性自检），CI 装 pyflakes 防止静默 skip。

### B64 · `deploy.sh` 被自己的管道静默杀掉 — 2026-09-23 ✅

B61 加的「核实跑起来的是哪一份」用了 `ps | awk '{print; exit}'`：awk 提前退出 ⇒ `ps` 吃 SIGPIPE(141) ⇒
`pipefail` + `set -e` 当场静默退出整个脚本，新包其实已装好启动，只是版本号与 B≠0 告警一行都不打。
竞态 ⇒ 同一天两次 deploy 一次完整、一次停在 `==> launching`。**一道「别让失败看起来像成功」的闸，自己失败得像成功。**
全仓扫开 pipefail 的脚本又找到 3 处同形：`setup-signing.sh` 的 `grep -q`（竞态时把「证书已存在」判成不存在 ⇒ 再造一张）、
`| head -2`、`install-launchd.sh` 的 awk `exit`。闸 `test_deploy_script_sigpipe.py` 用 4MB 确定性输入**必然**触发，不靠撞竞态。

### B65 · 测量仪器撒谎两例（都发生在做收回动画与磨砂材质时）— 2026-09-23 ✅

① **headless 的 `--virtual-time-budget` 不推进 CSS 动画时间线**（`getAnimations()[0].currentTime` 恒 0），
截图里倒计时细线看着几乎没动。改用 playwright 真实时钟量：2.5s/5s/9s 剩 75%/50%/10%，与设计一致。
同一原因，卸载必须靠 `setTimeout` 不能靠 `animationend`（后者在 harness 里永远不来）。
② **浅色主题根本没切过去**：`localStorage.codexbar_theme` 是菜单栏的键，主窗口主题不持久化、只认点太阳图标
⇒ 「浅色」那一列量的是白条压在深色界面上，得出「浅色要 .80 才过线（.68 只有 2.64）」。数字看着合理、
还能配出解释（透出来的是深色字），所以没人怀疑前提。真实浅色：.66 → 4.93。闸现在先断言卡片真的变白再量。
另：一次量到 880 宽见底态 hero 撑到 167px（上限 128），改 flex-basis 后变回 94px，**但改回去也是 94px** ——
四种组合 × 连跑 6 次不复现，成因未定，未宣称修复；真正的防线是高度闸现在也量见底档。

## v1.6.0 – v1.8.0 → 已分卷

> 2026-10-17 整段移到 [`docs/CHANGELOG-archive-2026H2.md`](docs/CHANGELOG-archive-2026H2.md)（**逐字未改**，1026 行）。查 `### B` 编号时两卷一起搜。

## 1c. 已发版、待真机回归（Codex session 隔离守卫）

- Codex PATH wrapper 的 session isolation guard 已收窄：原生 picker、`--all`、session name 与 ID 均透传，只拦自动接入最近 thread 的 `resume/fork --last`。新任务仍用 fresh `codex` 或 `/new <task-name>`。
- `scripts/test-codex-session-visibility.sh` 已覆盖 picker/名称/ID 放行与 `--last` 阻断，并用过宽 guard 做变异验证（变异版会红）。


---


> **线上验收（2026-09-21 从 `memory.md` 搬来，逐字未改）。** 板上那两条都已了结，
> 按「已发布的整段挪进 CHANGELOG，板上留一行指针」搬过来 —— 搬运保真，摘要不保真。
>
> - 2026-09-15 · ✅ **`_reset_crossed` 修复已在线上验证**：当天逐小时 `window reset crossed`
>   = 1~2 次（设计 12/小时；修复前那一段是 22/44/43/43/44/32）。
>   ★ 查法留一句（下次还用得上）：`quotad.log` **无日期**，必须先按「时间倒退＝跨日」
>   从文件尾切出当天那段再统计 —— 直接 grep 会串到别的天（本轮犯过一次）。
> - 2026-09-14 · 运行日志体检的证据保全在 `~/archive/codex-account-rotator/runtime-20260914/`。
>   ✅ `read_logs` 已于 2026-09-14 接进日志页（用户点名要），`@unwired` 标记随之摘掉。

用户问「目前的运行日志正常吗」。我先给了 4 条结论，随后用 opus / codex / grok 三方复核
（agy 缺席：omc 300s 超时 + 直连 headless 权限自动拒绝）。**三家各打掉我一条前提**，
而真正最贵的那条是复核里才浮出来的。逐条记，因为每一条的形状都值钱。

#### 我的 4 条里错了 2 条（都是"用坏掉的尺子量"）

| 我说的 | 实际 | 谁抓到 |
|---|---|---|
| 「日志页 300 行预算被退役日志吃掉」 | **`read_logs` 一个前端调用方都没有**（`grep -rn read_logs codexbar/src/` 为空）。那段截断从来没运行过 | codex |
| 「5h 窗口今天没被锚定」 | **锚上了**：6 个号 5 个 `quota_anchor["300"].state == anchored`。锚定它的是 08:45 一次手动 `probe --all` | opus |
| 「同时段 quotad.log 零条 SSL 失败」当反证 | **空探针**。`tick_usage()` 把 `cmd_refresh_all` 全部输出吞进 `StringIO` —— 而这条**就写在本仓自己的「已知验证缺口」一节里，我读过还照用** | opus |
| 「`health` 是只读的」 | **不是**，`cmd_health` 会 `_mutate_state` 写 `auth_dead` | codex |
| 「8 次里第 3 次全军覆没」 | `dawnprobe.log` **一个时间戳都没有**，8 段记录归不到具体日期 | opus |
| 「kickstart quotad 能治 dawn-probe」 | 治不了。dawnprobe 是**独立 launchd job**（`emit dawnprobe … "$ROT" dawn-probe`），`quota_daemon.py` 里 `dawn_probe` 出现 **0 次** | codex + grok |

★ 六条里有四条是同一个形状：**我的测量工具坏了，而坏掉的样子长得像"通过"**。
  这正是 §7.-1 那一节的主题，而我依然踩了 —— 包括那条"已知验证缺口"是我当天读过的。

#### ⑥ 真正最大的一件：`_reset_crossed` 把自己变成了 403 的放大器

`_reset_crossed` 的旧注释写着：

> 判据必须是「快照拍摄于重置之前」…… 这样写还顺带**自我清零**：扫描成功后
> `captured_at > resets_at`，条件自动不再成立，**不需要额外记"已触发过"**。

前半句对，**结论错**。`captured_at` 只在 `/usage` 回 HTTP 200 **且带 rate_limit 窗口**时才前进
（非 2xx 不替换是 v0.12.10 的刻意设计）⇒

    扫描失败 ⇒ captured_at 原地不动 ⇒ 条件恒真 ⇒ 每 60s 再扫一次 ⇒ 更容易 403 ⇒ 继续失败

**这道守卫在 403 出现的那一刻变成 403 的放大器** —— 正是它那段注释判过死刑的形状，
只是触发条件写反了：不是"服务端不更新 `resets_at`"时发生，是"**我们拿不到新读数**"时发生。

实测（`quotad.log` 无日期，按「时间倒退＝跨日」从尾部切出当天 264 行再逐小时统计）：

    03:00→22  04:00→44  05:00→43  06:00→43  07:00→44  08:00→32    ← 设计节拍 12 次/小时
    09:00 之后→ 1~2 次/小时

六小时、约 228 次多余的全池 `/usage`，**正好罩住 06:03 那次 dawn-probe 全军覆没**。
⚠️ 这给出第三个假说 **H3「本机把自己打进了边缘限流」**，它强于原来那两个：
  (a) LibreSSL 指纹 —— 被同日 08:45 的 `probe --all` 反证（同解释器、同 TLS 栈、同 host，全 200）；
  (b) Clash 黑洞 loopback —— dawn-probe 打的是外网，不是 loopback。
  **H3 仍是假说，不是结论**，闸 `TheEvidenceIsNotOverstated` 专门盯着注释别把它写成已证。

修法：每个「账号 × 窗口 × 重置时刻」只即时扫一次（调用方持 `served` 备忘录）。
旧注释说"不需要额外记已触发过" —— **需要，因为自我清零是有条件的**。
扫失败就退回 300s 固定节拍兜底，那正是这个特性存在之前的行为。

#### ③ 日志链两个方向同时漂，而安装脚本早就写着要同步

`install-launchd.sh` 的 `log_path()` 上面写着「CodexBar's log page reads these exact literals
(src-tauri/src/lib.rs read_logs). **Keep the two in sync.**」——**没有任何闸为此变红**：

    多出来：keepalive.log(08-26) · refreshquota.log(08-12)  —— 任务 08-29 已取消
    少掉了：dawnprobe.log · autosync.log                     —— 前者是全仓唯一会自动花钱的任务

叠加「先到先得」截断，实测 300 行里 **152 行是 8 月的尸体**，`agy.log` 一行露不出来。
现在：清单与安装脚本的任务集合对齐、每源保底配额（`LOG_BUDGET / 源数`）、
闸在 `tests/test_log_sources_match_installer.py`。

★ 顺带修掉一条**自己既假绿又假红**的老闸：`test_the_ui_reads_it` 断言 `"agy.log"` 出现在
  `fn read_logs()` 之后 500 字符内，docstring 却写着「判据打在**读取那一侧**」。
  它既证明不了 UI 读了（UI 根本不调这条命令），又会因为把清单抽成常量这种行为无关的重构假红。
  改成两条真断言 + 一条**异或闸**：「有前端调用方」与「挂着 `@unwired(read_logs)` 标记」恰好成立一个。
  ⚠️ 异或闸的第一版**变异验证当场判它是空的** —— 因为解释这条闸的注释里也写了一遍同样的记号，
    `in` 匹配到了它自己的说明。改成**出现次数 == 1**。本仓「闸被自己的说明文字判绿」的又一例。

#### ④ 计费探针白跑了没人说 —— 第三次了，所以这次是闸

今天 06:03 dawn-probe 5 个号全败，而 `health` 只字未提、设置页把 `0/5 可用` 和 `4/4 可用`
画成同一行中性文字、`dawn_probe.note` 是 `""`（**`done` 路径恒写空**，拿它判就是恒绿）。

新 `dawn_probe_gate()` 四态。★ 判据刻意**不是**「窗口有没有锚定」—— 今天锚上了，
但锚定它的是手动 `probe --all`；拿结果当判据会让「定时器连着几天白跑」永远不报
（`keepalive` 的 `runs = 0` 就是这个形状）。它报的是**运营事实**。
★★ 两种失败**下一步动作正好相反**，所以绝不合并：

    全部 send err  ⇒ 可证未计费 ⇒ warn    ⇒「今天可以安全重跑 --force」
    含 committed   ⇒ 可能已计费 ⇒ unknown ⇒「**不要**重跑，那是二次扣费」

为此 `cmd_dawn_probe` 现在把**本次**逐号计费相位摘进 `phases`/`billing`
—— 不能事后读 `last_probe` 重算，那个键会被任何后来的探针覆盖（今天 08:45 就覆盖了 06:03）。
判不出来时按"可能已计费"处理（钱这一侧 fail-safe）。

#### ⑦ 「谁在自动花钱」原来答不上来

08:45:00–08:45:50 有一次 `probe --all`（7 个槽位被写：5 真探 + 2 跳过 ⇒ **5 次真实计费**），
而 `last_probe` 里**没有任何字段**能说出是定时器、界面按钮还是终端触发的。
现在记 `via`：`dawn-probe` 传 `dawn`、Tauri 侧在 `spawn_cmd`（所有子进程的唯一入口）
统一带 `ui`、其余缺省 **`cli?`** —— 带问号，因为写成 `cli` 会把「没传这个变量」
和「真的从终端跑的」折叠成同一个值。

#### 顺带结案 ⑤（零成本，用盘上现成数据）

`dawn_probe.at` 仍是 06:03（**没有二次占天**）· 只有 qq55 一个号 `last_probe.at=17:57:45`
· 该记录带 `billed:true`（只有 `cmd_probe` 写得出）⇒ **卡片上的单号探针**，
不是 dawn 泄漏、不是重复计费。

#### 动作与验证

证据保全在 `~/archive/codex-account-rotator/runtime-20260914/`（launchctl print × 4 · plist × 4 ·
state/anchors/日志副本 · repo HEAD + 三个源文件 sha256）。
★ 顺带取证：**dawnprobe 的 plist 是健康的** —— `StartCalendarInterval` 完整、
`EnvironmentVariables` 非空、解释器钉在 `/opt/homebrew/bin/python3`（OpenSSL 3.6.3）。
那个至今未查明、专吃 `StartCalendarInterval` 的外力**没有碰过它**。

`kickstart -k … quotad` **只重启 quotad**（68310 → 34929），proxy 的 81134 原地不动 ——
三家一致：不存在版本配对要求，而 `kickstart -k` 是 SIGKILL，打断在途 `POST /responses`
落在 committed 相位（可能已计费），且 `_conv`/`_affinity` 是纯内存 FIFO，重启即失去全部会话粘性。

**测试 1206 → 1245 passed** · `cargo check` 干净 · `npx tsc -b` 干净 ·
变异验证 **13 个**全部符合预期（含 3 次「把被断言的东西整个删掉」方向与 4 次防假红）。
⚠️ 其中两次变异当场抓出**我自己新写的闸是空的**（异或闸匹配到自己的说明文字；
`-k TheGate` 只选中 15 条里的 9 条而漏掉的 6 条恰好守着那次变异）—— 工具挡住了流程漏项。

---

### B45 · Gemini 档「切档跳来跳去」：真因是**已验证的值被陈旧种子覆盖**，不是没做缓存 — 2026-09-14 ✅

用户报：「gemini 没有对应的缓存，因此在总览里切换导致跳来跳去」。

#### 现象与真因

`useAgyPool` 是总览三档里**唯一**没有缓存语义的取数口 —— codex 走常驻的 `useStore`，
grok/agy 额度走带 `fetched_at` 单调采纳的 `useQuotaSidecar`，而它每次 `enabled` 翻真
都从零重来，并且**先把 `liveSub` 写成池文件里的 `live_seen`**，等两个 python 子进程
（`auto-switch --json` → `live --json`，串行）回来才改正。

而这两个值**本来就常常不同**。修复当天本机实测：

    .agy-pool.json  live_seen = 100000000000000000002   (dbk)   ← 我们上次装进去的
    agy-rotate live --json → sub = 100000000000000000001 (sam), drifted: true

于是每进一次 Gemini 档，Hero 的号名 / 邮箱 / 环形百分比 / 5h·周两行**整块闪一次**，
「当前」徽章在两张卡之间跑一个来回。

★ **"没做缓存"是症状的名字，不是根因。** 根因是 `CLAUDE.md` §7.0b 那条
「**读不到 ≠ 没有**」在 UI 侧的形态：`live_seen` 是**已知不可靠**的写入侧标志
（B44 已经为它栽过一次 —— 那次的症状是「界面说 B、agy 里是 A」），
现读一旦回来过，退回去就是拿一个已知会撒谎的值覆盖一个已验证的值。
只加一层缓存而不修这条，重进时照样会被种子打回去。

#### 实测（`?agypool=3&agydrift=1&agy_delay=100&click=Gemini,Codex,Gemini`）

夹具：`live_seen=sub0`→`qq55` 是种子，`live --json` 回 `sub1`→`Asen` 是现读真值。

| | Hero 序列（ms） | 分档条 Gemini 计数 |
|---|---|---|
| 修前 | null → **qq55**@774 → Asen@966 → null@1078 → **qq55**@1366 → Asen@1558 | Gemini1 → Gemini3@**774**（进档那一刻） |
| 修后 | null → qq55@749 → Asen@845 → null@1053 → **Asen**@1341 | Gemini1 → Gemini3@**82**（挂载即真数） |

真机上那两个子进程实测各约 80ms（`live --json` 0.081s / `auto-switch --json` 0.046s），
串行 ⇒ 每次进档有 **160~440ms** 的错误身份。

#### 改了三处，每处对应一条不变量

1. **`live_seen` 只当种子**：加一位 `verified` ref，现读成功过之后就再也不许用种子写 `liveSub`。
   —— 这是那条「跳」的直接修法。
2. **池文件在挂载时就读**（`readPool` 独立成一个 effect，不受 `enabled` 约束）。
   它是一次 `read_sidecar` 文件读，**不起子进程、不联网、不消耗配额**，
   与「总览一打开就联网」那条纪律不同族。不预读的代价是可见的：分档条上的
   「Gemini N」在没进过这一档时恒显示兜底的 `Math.max(1, 0)` = **1**，
   进档那一刻才变真数、整条 pill 重排。**菜单栏芯片行同一份代码，一并修好**
   （那里更糟：「账号」Tab 的总数是三档计数之和，进档前整个总数都是错的）。
3. **探测失败不许写成"没有漂移"**：原来 `catch { setDrifted(false) }` 把
   「这次没探到」折叠成「确实没漂移」，一次子进程失败就让那条琥珀告警消失。
   现在失败什么都不动，也**不推进** `probedAt`（失败不算"刚探过"）。

附带两项：`read()` 加在途守卫 + `PROBE_FRESH_MS = 8000` 节流（挡"来回点分档"叠起来的子进程，
它们各自要抢 Rust 侧的 `AGY_LOCK`，而 `run_agy_quota` 抢的是同一把锁）；
**写操作一律 `read(true)` 绕过节流与在途守卫** —— 它们重读的正是刚被改掉的东西，
丢掉那次重读 = 用户点了「切换」而界面纹丝不动。
`live` 排到 `auto-switch` 前面，把首次进档的错误身份窗口从 ~440ms 砍到 ~200ms。

#### ★ 新探针：`trails` —— 本仓第一条**时间序列**闸

**终态永远是对的，错的只有中间那几帧。** overflow / 折行 / `--dump-dom` 问的全是
"最后长什么样"，它们对这类缺陷**完全沉默**，而沉默在报告里和通过一模一样。
`make_harness.py` 现在按 16ms 采样几个**身份格**（`[data-hero-acct]`、
`[data-provtab="gemini"]`）的文字、相邻重复折叠，判据打在序列上。
配套 `?agy_delay=<ms>` 让两条 stub 异步送达 —— 同步打桩 = 按设计绕开竞态 = 看不见任何竞态缺陷
（同 `?snap_delay=` 那条）。

⚠️ **档位是挑过的**：`agy_delay=220` 时修前的**第一次**访问在点走（1000ms）之前
根本没跑完现读，`Asen` 从没出现过，「现读之后又退回种子」这个形状就构不成 —— 闸会**假绿**。
100ms 才是只有被测那条能挡住的那一档（§7.-1 第 ⑦ 问）。

#### 顺手修了一条**自己假红**的老闸

`test_agy_pool.py::test_a_failed_probe_does_not_erase_the_fallback` 钉的是字面串
`if (probe.sub) setLiveSub(probe.sub)`。给那个 `if` 的花括号里多加一句就把它打红了，
而语义一个字没变。改成按行匹配 —— **变异验证当场判它仍然假红**（把同一个守卫拆成多行
就不认了）。最终改成结构判定：每一处 `setLiveSub(probe.sub)` 都必须落在某个
`if (probe.sub)` 的**管辖区间**内（带花括号就配对，不带就到分号）。
★ 这一条自己就是本轮的教训：**逐字/按行匹配守的是"代码长什么样"，不是"行为对不对"**，
而会因为无关重构假红的闸，人学会的是把它关掉。

#### 验证

新增 `tests/test_agy_pool_cache.py`（7 条：4 条行为 + 2 条锚点自证 + 1 条静态）。
★ 它的 `setUpClass` **自己跑 `vite build` + `make_harness.py`** ——
`sweep.probe` 只是去打静态服务，`_assert_fresh_bundle()` 在那条路径上**根本不会被调用**，
不自建这道防线就会测到旧 bundle（本仓已因此假绿两次）。

变异验证 8 个全部符合预期：
退回旧实现 / 删掉 `verified` 置位 / 删掉挂载预读 / 放回 `setDrifted(false)` /
去掉 `probe.sub` 守卫 / 整行删掉 → **红**；调大节流窗口 / 守卫拆成多行 → **绿**（防假红）。

**测试 1199 → 1206 passed**（全量 `unittest discover`）· `npx tsc -b` 干净 ·
`sweep.py` **16**（与基线一致，全部落在中转站那几个视图，本轮未碰）。
像素留档 `~/Downloads/codexbar_gemini_cache_20260914.png`。

---

### B44 · agy 账号池端到端：真因是登录态在**钥匙串**，此前换号一直是静默空操作 — 2026-09-13/14 ✅

用户从「新增 agy 版块的账号额度更新和自动轮换」开始，两天里报了十几处，
每一处的真因都不在它表现出来的地方。按**发现顺序**记，因为后面几条是前面几条的连锁。

#### ① 真因：agy 1.2.2 的登录态在 **macOS 钥匙串**里，不在那个文件里

用户实报 `agy-rotate login` 走完浏览器 OAuth、回来却被告知「读不到登录态」。
查 agy 自己的日志，登录**成功了**：

    auth.go:148]  ChainedAuth: authenticated via keyring (effective: keyring)
    browser.go:167] consumerOAuth: authenticated successfully as <新号>
    composite_token_storage.go:237] Failed to save token to keyring, falling back to file

`~/.gemini/antigravity-cli/antigravity-oauth-token` 只是**钥匙串写失败时的兜底**。
本机一直有那个文件，是因为 09-13 11:23 真发生过一次那种失败 —— 我们把兜底路径当成了主路径。

**判别实验**（已跑，别再推理）：文件里放 A 号、钥匙串留 B 号，跑 `agy models` →
日志 `applyAuthResult: email=B`。**文件被完全忽略。**
⇒ 在这之前 `agy-rotate switch` 一直是**静默空操作**：写成功、退出码 0、打印「已切到」，
而 agy 根本不读那份。又一次「写入侧标志会撒谎，判据要由被作用对象自证」。

- 主存储 = 钥匙串 `svce=gemini` / `acct=antigravity`，值是
  `go-keyring-base64:` + base64(JSON{auth_method, id_token, token{...}})。
- 读序跟 agy 的 `ChainedAuth` 一致：**钥匙串优先**（实测 13/13 次 `effective: keyring`）。
- ★★ **写钥匙串只能走 argv。** `security -w` 从 stdin 读时**静默截断到 128 字节**
  （`readpassphrase` 缓冲区），而凭证约 2.2 KB。退出码 0、读回来还带正确前缀，
  只有 agy 说「你没登录」—— 我的第一版就这么把用户的登录态截没了（靠池里备份复原）。
  所以 `keyring_write()` **写完必须读回来逐字比**。
- ★★★ **测试默认 `AGY_KEYRING=0`**（两处 bootstrap 都设）：钥匙串**没有临时目录这种东西**，
  换 `AGY_TOKEN_FILE` 挡不住，一条用例就能覆盖用户真实的登录态。

#### ② 钥匙串是**被多个常驻 agy 进程并发写的单槽**

用户报「界面说当前是 B，打开 agy 看到的是 A」。本机同时跑着 **5 个** agy 进程
（最久 6 天）。时间线：

    17:58     switch 到 B，`agy models` 日志证明新进程认到 B（当时 token expiry = 18:23:16）
    18:23:17  钥匙串 mdat 被改写 ← 某个身份为 A 的常驻 agy 在自己 token 到期时写回了自己
    18:59     用户开 agy → applyAuthResult: email=A

⇒ **「当前账号」不是我们能维持的状态，只是一个随时会被冲刷的观测值。**
三方评审（Claude / codex / grok）独立得出同一结论。落地：

- 新增 `agy-rotate live [--json]`：**只读钥匙串**回答"现在到底是谁"。
  UI 的「当前」徽章由它驱动，`live_seen` 降级为诊断字段。分歧时出琥珀提示并说明原因。
- `auto` 新增 `live_wanted`：**先兑现用户显式选的号，再谈额度够不够**。
  此前 `if _score(cur) >= LOW_WATER: return` 会在 A 抢回槽后看到 A 健康就不动 ⇒
  **静默撤销用户的 switch**，比显示错严重（工具撤销一个明确指令且不出声）。

#### ③ agy 的探针 / 检查 token / 自动切号 —— **三条都不是 codex 那一套**

| | codex | agy |
|---|---|---|
| 检查 token | 问 OpenAI「这 token 被作废了吗」 | 刷一次 access_token + 打一次 `fetchAvailableModels`，两步都过才算能用。零消耗 |
| 探针 | 直接 `POST /responses` | **起一次 `agy -p`** —— agy 只在进程启动时读凭证，没有"指定号发一次请求"这种东西 |
| 自动切号 | 代理逐请求挑号 | `bin/agy` 在 exec 真身**之前**调 `agy-rotate auto`，开关存池里 |

★★★ **探针不能自己拼 HTTP（实测，别再试）**：直接打
`v1internal:streamGenerateContent` 恒 **429 RESOURCE_EXHAUSTED**，即使该号额度满格、
模型 id 取自它自己的 `fetchAvailableModels`、也带上了 `loadCodeAssist` 回的
`aicode-consumers`。**那个 429 长得和「额度用光了」一模一样** ——
用它做探针会把"我们拼错了"报成"你的号没额度了"。
起 agy 真身顺带拿到**精确到 token 的用量**（实测一次 15,195 token / 约 30s），
比 codex 那边只能拿到整数百分比还清楚。判据同 codex：**模型真吐出字**，不是退出码 0。
非当值号先切过去再探，**还原放在 `finally`**。

★★ **自动切号开关能做，我曾判断"做不了"并说给用户听过 —— 那个结论是错的。**
当时的理由是「自动选号发生在 wrapper 里」，那句话没错但结论错了：wrapper 调的是
`agy-rotate auto`，**而它读池**。全局 `auto_off` + 按号 `rotate_off`，两个都**存反向**
（缺省 = 参与轮换；正向命名要写迁移，漏迁移的号会静默退出轮换池），恢复时**删键**不写 `False`。

#### ④ 周额度的**归属**：`agy-quota` 打的是"第一个应答的 pid"，不是当值号

多个常驻进程身份不同 ⇒ 那份带「周」的读数属于**那个进程**。实测：卡上
`user-b` 的「周 98.9%」实际来自 pid 24433（`user-a`，起于 09-07）。
现在 `agy-quota` 记 `pid_email`（取自 agy 自己日志的 `applyAuthResult:`），
**归属对不上就不用那份**。同「按 `response_id` 精确 join，不按时间猜」。
★ `ps -o lstart=` 的日期顺序**跟 locale 走**（本机是日在前），只写一种格式会让归属
**静默恒空** —— 闸打在 `_parse_lstart` 这个纯函数上。

#### ⑤ 两个"看不见的空"

- **GUI 切不了 agy 号而 codex 可以**：`agy/pool.py` 按 `__file__` 推数据目录，
  打进 app 后是 `Contents/Resources/scripts/`（空池）⇒ 点「切换」跑的是空池，
  命令成功、退出码 0、什么也没发生。`spawn_cmd` 补 `AGY_POOL_STORE`。
  闸从两边解析（打包清单里"默认值来自 `__file__`"的变量必须都被喂到），
  **当场揪出第二处**：`agy_quota_sampler.py` 与 `scan.py` 对同一本账本推出两个路径。
- **总览 Gemini 档整块灰**：`colorOf()` 三级链的末端 `PLATFORM_COLORS` 里没有 `agy`
  ⇒ 落到 `?? "#5b6472"` 那个死灰。同一形态记过一次（MiMo/DeepSeek）。

#### ⑥ 缺一个额度窗口时**画出来并说明为什么**

四处都用 `visibility: hidden` 的同构占位行（为了跨卡对齐），用户看到的是一整行空白。
改成 `—` + 悬浮说明，高度仍同构。★ **两种缺失的文案刻意不同**：
agy 缺「周」= 这个号读不到（切过去就能看到）；grok 缺「5h」= **上游根本没有这个窗口**
（实测 `window_minutes = 10080`，等也没用）。合并成一句话就把两种状态又折叠回同一个值。

#### ⑦ 其余

- 总览按供应商分三档 **Codex / Gemini / Grok**，清单抽到 `codexbar/src/platforms.ts`
  （主窗分档与菜单栏芯片行**共用一份**）。`Google → Gemini`、`xAI → Grok` 改名，
  旧 localStorage 值仍然认（否则停在该档的用户下次打开会静默跳回 Codex）。
  ⚠️ **「AI 用量」页仍是 8 家**，用户明确分开：账号池 = 我有凭证能管的号；用量 = 本机哪些 CLI 落了盘。
- 菜单栏 **v4 平台 logo 芯片行**（1:1 复刻 `design_handoff_codexbar 11`），
  一档一份列表、底栏随平台变。logo 走 CSS `mask-image` 一张图覆盖两态、资产内置。
  ⚠️ 与稿的两处刻意偏离：Grok 档**不给**「检查 token / 探针」（稿假设 grok 有自己的池，
  而本机 grok 单号只读、探针属 codex）；Tab 上的数字是**全平台总数**（用户当面否了稿的"当前档"）。
- 托盘标题**去掉** grok 的 `Gxx%`（用户点名）；同时收编另一会话已在线上跑着的
  `grok-quota-sampler`（三条判据全过：自带 29 条测试、`cargo check` 干净、线上已在跑）。
- 新增 `<store>/agy.log` 运行日志：`switch`/`auto`/`quota`/`health`/`probe` 逐号留痕，
  **成败与用量都写**；`read_logs` 收它，日志页把 `✗` 行染红。
- 「AI用量信息」补回交接稿 §1/§5 的**数据源副标**与**请求数** KPI
  （`grandRounds` 一直算着没人消费 —— 后端有值 ≠ 已披露）。
- 菜单栏点账号行**不再跳到 AI 用量**：三档统一成「点行 = 开主界面的总览并停在这一档」。
- Gemini 卡补 `⌘N` 角标，且 ⌘1~⌘9 **真的按档分流**（角标是承诺，不接线就不该画）。

#### 被推翻/撤回的

- ~~「Gemini 档不许有 ProbeButton」~~ —— 当时探针只有 codex 一套。agy 有了自己的之后，
  那条闸锁死的是一个已不成立的前提，已改写成「不许跑 **codex 的那条** probe」。
- ~~「agy 绝不能长出切换入口」~~ —— 前提是"agy 切不了号"，打通之后作废。
- ~~「菜单栏至少装得下 4 个账号」~~ —— 用户当场撤回（「这个需求不要了」），代码与闸一并回退。
- ~~直接打 `streamGenerateContent` 做探针~~ —— 恒 429，见 ③。

### B43 · 四方评审 14 条：①-⑥ 全修，⑦-⑭ 判为不做 — 2026-09-12 ✅

（下面这张表整段自 `memory.md` §0a 搬来，**逐字未改** —— 它记着几个当时的实测数字，摘要会把那部分磨掉。）

### 0a. 四方评审 14 条发现 —— **①-⑥ 全部已修；⑦-⑭ 判为不值得做**（2026-09-12）

`/cross-review` 4/4 面板全票（claude+codex+antigravity+grok），2 critical / 4 high。
完整证据与修法在 workflow 结果里，这里只留清单与优先级：

| # | 级别 | 一句话 | 谁找到 |
|---|---|---|---|
| 1 | ~~critical~~ **已修 0912** | `--force` 绕过占天却不区分「已完成 / 正在跑」⇒ 并发全池双重计费。修法：`running` 且未陈旧时 force 也拒；超 `DAWN_STALE_SECS`(1800s) 按 `kill -9` 遗骸可接管并打印（那次**可能已花过钱**）。闸 `ForceDoesNotJoinARunInFlight`，3 变异 | claude+agy+grok |
| 2 | ~~critical~~ **已修 0912** | 刚锚定的窗口被判 `floating`，UI 在计费探针刚跑完后反说「窗口未启动」。**实测**（`scratch/measure_anchor_lag_20260912.py`，纯内存零落盘）：**每次探针必现、与相位无关**，持续 **897–1197s**（≈15–20min）。四家说的「+900 还错、+1200 才对」成立。根因链：`cmd_probe` 在计费请求**之前**调 `_probe_quota`，而 `_note_quota_anchors` 就在它里面（`codex-rotate:1698`）⇒ 探针前 ~3s 必有一条带**旧浮动 reset** 的记录 ⇒ 锚定后的 `R` 与它只差 ε≤`JITTER_SECS`(60) ⇒ 合并进那一行 ⇒ `_slide_run` 尾行仍是闲置行、`slides` 恒 ≥2 ⇒ 只有 `held ≥ HOLD_SECS`(900) 能救，而 `held` 只在 300s 扫描点上涨。UI 侧 `used_max < 2` 守卫接不住（low-effort 探针对 5h 窗口的消耗取整后 0~1%）。**修法＝`mark_billed()`/`note_billed()`：把「我们亲手在这个窗口里发过计费请求」记成事实，`verdict` 里排在 `slides` 之前。**★ 不是放宽 `_slide_run`（那会让真浮动窗口被认成锚定，方向正好相反）；`slides` 一个都没少。修后首个读数即 `anchored`。11 条闸 + 9 变异。⚠️ 我第一版建模漏了探针前那次免费 GET，算出「只有 20% 相位中招」，**那个数是错的，别再引用** | 四家一致 |
| 3 | ~~high~~ **已修 0912** | `_billed_probe` 把 `request()/getresponse()/read()` 放同一 try，全塌成 `req err` 而它会重试 ⇒ 200 后读流超时会**重发计费请求**（违反本仓 §8「计费相位分界」铁律） | 仅 codex |
| 4 | ~~high~~ **已修 0912** | dawn-probe 把 aid 转成 label 再当 argv 解析：label 叫 `--all` ⇒ 全池计费；重名 ⇒ 一号billed两次；`cmd_add` 完全不校验 label | 四家一致 |
| 5 | ~~high~~ **已修 0912** | 探针循环抛异常 ⇒ 当天永久占住 `state:"running"`，整天锚定静默失效，无人清理 | claude+agy+grok |
| 6 | ~~high~~ **已修 0912** | `note()` 的 load→record→save **不持锁** ⇒ 三个写入进程互相丢锚点。**我声称的不变量 (d) 是假的** | 四家一致 |
| 7-9 | medium · **判为不做** | 日期幂等只用裸本地日历日（时区/跨午夜再计费）· 完成回写盖掉更新的一天 · `cycles()` 造出幻影 0% 周期 | — |
| 10-14 | low · **判为不做** | 无按号台账 · 零目标也占天 · SCHEMA_V 不匹配互相清库 · plan 用 id_token 快照而非更新的 `/usage` · `enabled` 在锁外读 | — |

★ **①-⑥ 全清。** ⑦-⑭ 判为不值得做（medium/low，多为已被别处闸覆盖或收益低于改动风险）。本轮沉淀的两条通用教训：**① 闸只覆盖单向 = 在它没覆盖的那一向上等于不存在**（「标记按行不按桶」第一版只写了「往后不继承」，漏了「往回不误标旧行」，按桶标记那个变异照样绿，被 `tools/mutate.py` 当场拦下）；**② 修法要改的是「信息被丢掉了」，不是「阈值太大」**—— 见 ②：真正的毛病是探针手里有全部答案却扔掉、再花十几分钟推导一遍。

### 0-relay → 见 CHANGELOG `B41`（架构）与 `B42`（评审三轮 + 设计稿重做）

⚠️ **B41 与旧版本文写过「四个入口已统一，含 VS Code」—— 那句是错的**
（实测：扩展自带 codex 二进制、不查 PATH，且跑黑名单里的 `app-server`）。已在 B42 与 CLAUDE.md 更正。

本轮沉淀的两条通用教训（已同时写进 `CLAUDE.md`）：

1. ★★ **一条只覆盖单向的闸，在它没覆盖的那一向上等于不存在。** 「计费标记按行不按桶」这条闸的第一版只写了「**往后**：新窗口不继承标记」，漏了「**往回**：标记的那一刻不许误标桶里的旧行」—— 而后者才是危险的方向（一串确实在漂的窗口集体自称已锚定）。把 `mark_billed` 改成按桶标记的那个变异因此**照样绿**，是 `tools/mutate.py` 当场拦下的。写闸时要问的不是「它红不红」，是「它在哪个方向上红」。

2. ★★ **当症状是「要等很久才判对」，先问信息是不是被丢掉了，而不是去调阈值。** 计费探针**就是**那个把窗口锚定的动作，它手里有判定需要的全部信息；原实现把这份信息扔掉，再花 897–1197s 从时间序列里把同一件事归纳一遍。调 `HOLD_SECS` 或放宽 `_slide_run` 都能让症状变轻，代价是让**真正的**浮动窗口被认成锚定 —— 方向正好是这套判据存在的理由。正确的修法是加一条事实（`mark_billed`），让演绎排在归纳之前，而归纳本身一个字都不动（`slides` 修前修后完全相同）。

---

## 已知待办 / cleanup
- ⏳ **`Selected model is at capacity` 未定案**（2026-09-08 用户报）。**已排除本仓改动**：当轮只改了
  `proxy/cxp` 的 argv 路由（diff 里 model / `service_tier` 一个都没碰），两个 config 的 mtime 都早于
  第一次编辑；额度链正常（当天 429 六次全部被代理接住换号）。**当场用现状配置真跑 `codex exec` 成功**
  ⇒ 间歇性，未复现。两个都成立的假说与判别实验见 `memory.md` §0a-bis（一句话：同一时刻跑
  `codex exec -c service_tier='"default"'`，成功=fast 通道满，也失败=模型整体容量）。**不在这里展开，
  免得同一件事有两个家。**
- ~~`scratch/codex-native-resume-0.153.4` 占 25G（B39 弃案后的构建树）~~ → **2026-09-09 已删，回收 24.4 G**。
  99.5% 是 cargo 构建产物、0.5% 是官方源码解包，**无独一无二信息**（补丁 + 34 个文件锚点哈希 +
  上游 commit 全在 `scripts/native-resume/`）。删除用点名 `rm -rf <dir>`、**不带通配符**，
  并做逐名比对确认只少目标一项。
- ~~v1.5.0 的跨平台产物~~ → **已确认 success**（release workflow `34461451417`，7m27s，
  macOS + Windows 两个 runner）。三个 SHA 一致只证明本地/远端/tag 对齐，
  **不证明产物构建成功** —— 这条规则本身留着。
- ⚠️ **`v1.5.0` 这个 tag 指向的 commit，其 `ci` 作业是红的**（`34461445099`）。修复在紧随其后的
  `c22da6d`（CI 已绿）。**不重打 tag** —— 产物构建（`release` 作业）是成功的，红的是
  三条 macOS-only 的测试假设 + 一条 `exec command` 的可移植性，对 macOS/Windows 用户零影响。
  真正的教训见下一条。
- ★★★ **CI 自 2026-09-08 起一直是红的，而没人看见** —— 因为那之后没发过版，
  而我每次只在本机跑 pytest。两个叠加的原因：① CI 跑 `unittest discover`（856 条）而本地跑
  pytest（879 条），**23 条从来没被 CI 守过**；② 三条测试携带 macOS-only 假设
  （`plutil` / `/usr/bin/command` / 本机得有 codex rollout），在 ubuntu runner 上必红。
  已改成**同一条命令**（CI 装 pytest 跑 `pytest tests/ -q`）。
  **两条不同的命令 = 两个不同的门，而只有一个会红。**
- ⏳ **`resume_provenance.mark_proxy_session` 全仓无调用者** —— marker 从来没人写，`.proxy-sessions-v1/` 是空的。
  归属判定实际全靠 `payload.model_provider == "rotateproxy"` 这条主判据。模块与 `codex-rotate:399` 的
  接线留着（无害、测试全绿），但**别当它在工作**。
- ~~`_run_codex_ping`/`_codex_running`/`CODEX_BIN`/`LOCK` dead code~~ → B21 已删。
- ~~代理刷新与 keepalive 并发刷同一号~~ → B9 已加 `.refresh.lock` 跨进程串行解决。
- ~~`auth_dead` 被 autosync 竞争清掉~~ → B17 指纹门控 + B15 state 锁双重解决。
- **额度归因**:plain 模式靠 rollout 时间窗、cxp(代理)模式靠 `x-codex-*` 头——两套已对齐,但跨模式快速切换的边界可能短暂不准(原文的 ±10s 是 SwiftBar 10s tick 时代的数,载体已退役;现由 `last_proxy_ts + 12` 与 quotad 的 `TICK_SECS` 决定)。CLI 侧的 SwiftBar 联动已于 2026-08-12 删除,`tests/test_retired_swiftbar.py` 用 AST 守着不回来;`swiftbar/` 目录本身仍在仓库,清理登记在 memory.md。

## 弃案与负面结论（防止半年后重试）

> 2026-09-10 从 `memory.md` **逐字**搬来 —— 它们不是"进行时"，是**历史**：
> 「我们试过 X，否了，理由是这个实测数字」。摘要会把不可再生的那部分磨掉，所以一个字没改。

- 2026-08-16 · **★★ codex 走代理挂死 = macOS 系统代理黑洞 loopback，不是 codex 不支持明文 http**。
  Clash Verge 开着系统代理（`HTTPEnable=1` → `127.0.0.1:7890`），codex 的 reqwest 把发往
  `http://127.0.0.1:8011` 的请求也送进 Clash，而 Clash 对 loopback 目标**连接受理、永不响应** ⇒
  永久挂死、零输出、代理侧一条日志都没有。**修法：`cxp` 里 `export NO_PROXY=127.0.0.1,localhost,::1`**
  （已落地，软链所以线上同步生效；`cxp` 与 `omc ask codex` 均实测 exit 0 且 proxy.log 增长）。
  ⚠️ **系统代理的 ExceptionsList 本来就有 127.0.0.1，reqwest 无视它** —— 在 Clash 里配 bypass 没用。
  ★ **我自己查错过一轮，两个陷阱留档**：① 症状 `models_manager: timeout waiting for child process to exit`
  是 auth 5s 超时的次生文案，**与子进程无关**，顺着它查会走死；② 我做的判别实验
  「换 `https://chatgpt.com` 能成 ⇒ 是 http 的问题」**一次换了两个变量**（scheme + host），
  真因是 Clash 代理公网目标正常而已；指向没人听的 `http://127.0.0.1:9999` 症状相同，
  不是"没走到连接"，是两者第一跳都是 7890。**给代理套 TLS 解决不了**（CONNECT 到 loopback 同样黑洞，实测）。
  ✅ 闸已加（`proxy_env_gate()`，接在 `codex-rotate health`）：三态 ok/warn/unknown，告警印在**最前面**、
  正常时只在末尾一行。**变异测试过它会变红**（去掉 cxp 的 NO_PROXY → ⚠️；cxp 读不到 → unknown，
  文案与 ok 不同）。★ 闸**跑在 `if not slots: return` 之前** —— 空池正是最需要它的场景之一。
  这是一类 bug：**任何 reqwest 系工具打 `http://127.0.0.1:*` 在系统代理开启时都会中招**。

- 2026-08-13 · **「今日小时图改成逐小时柱」已被用户否掉，保持平滑面积**。出过真数据 demo
  （`~/Downloads/codexbar_today_hourly_demo_20260813.html`，2026-08-09 真实逐小时，含 03–07 空档）
  四档并列比过：柱在 2 桶、10 桶两档确实更诚实（面积会把两个离散小时铺成全宽色块、把真实空档抹成低谷），
  **用户仍选 A**。所以那两个观感缺陷是**已知且被接受**的，别当 bug 再修一遍。只有 n=1 的空白是缺陷，已修。

- 2026-08-01 · **「curl 也被挡 ⇒ 是端点级问题」已证伪**：macOS 自带 curl 同链 LibreSSL，复现的是同一失败模式。换工具名不是对照组，**换 TLS 栈才是**。
- 2026-07-30 · **假说 H2「服务端按设备撤销上一次授权」已证伪**：plus7 是本机上一次签发的授权，受控实验第三轮中存活。
- 2026-08-01 · `applicable_available_count` 的放行门槛**未定**：2 次观测（周用量 0% 与 74%）都是 0，无法区分「须 `limit_reached`」与「须过某高水位」。判别实验免费：盯高用量号的 `applicable` 在 `used_percent` 爬升时何时翻正。**别当成已知规律用**。
- 2026-08-01 · 重置卡的发放圈选规则**未定**：唯一有效反例只有 plus6（07-13 授予时已是订阅期内付费 Plus 却没拿到）；plus7 当时尚不存在＝零信息量。`credits` 已会自动记录新卡的 `granted_at`，攒样本后再判。
- 2026-08-01 · 观察待验证（n=1，勿外推）：plus3 与 plus4 同批（相隔 75 秒）、到期时刻仅差 1 分钟的两张卡，plus3 那张在标称到期前就从接口消失、plus4 那张还在。
- 2026-06 · **每号挂不同代理 IP** —— 议过，未做。
- 2026-08-04 · **`_affinity`（会话粘同一号）从未生效**：实测 2291 次请求 **100% 不带 `previous_response_id`**，选号原因全是 `new`。proxy.py 顶部 docstring 的「session affinity sticks the whole conversation to one account」不符实际。~~未改——因为轮换本身不浪费（`cached_tokens` 在所有配置下都是 0，没有 prompt cache 可失去）。~~
  **★ 2026-08-09 这条结论被推翻，且它是整个「轮换不浪费」论证的地基。** 实测全量 rollout：`cached_input_tokens / input_tokens` 逐月 **95%~99%**（2026-03 到 08 全覆盖，无一例外）。当年那次测量大概率只覆盖了会话首轮（首轮本就恒 0）。
  ⚠️ **但我由此推出的「换号=浪费额度」是错的（用户 08-09 纠正，实测证实）**：`total_tokens` 本就包含缓存命中部分，冷启动改的是**价格**不是**数量**，订阅制下没有价格。按 token 对齐后，plus3/5/6 的缓存命中率 92~98%，与 pro1 的 95.3% 无差异——**切过去根本没冷启动**。「冷大请求占未命中 input 27.2%」这个测量本身成立，但它衡量的是钱、不是额度。
  实测预算量级：**Pro ≈1.85B token/周、Plus ≈250M/周，差 7~8 倍**。「6 次比 139 次还贵」全部由此解释。
- 2026-08-04 · **客户端重试是最大的一类双计费源，代理侧无解**：542 次 `stream err`（已 200、流中断），其中 85 次紧跟新请求。响应已部分转发，abort 是唯一正确动作；伪造 `response.completed` 收尾更糟，别做。已加 `proxy_counters.stream_aborts` 让频次可量化。
- 2026-08-04 · ~~**未测的假说**：客户端超时并发重发。观测数=0。~~
  **2026-08-09 已有观测**：`proxy.log` 里 `stream err` 共 593 条，`broken pipe` 占 **347 条(58.5%)**——broken pipe 就是**客户端先断开**。但其中大部分是无害的 `GET /models`；真正计费的以 `proxy_counters.stream_aborts` 为准（**29 条 / 4 天 ≈ 7.4/天**）。`timed out` 只占 13 条(2.2%)，所以「我方 180s 读超时掐断长思考」这条具体机制**已证伪**。
- 2026-08-09 · **「一次会话扣两个号」的现场三方结论（我 + grok + kimi）**：代理内**不存在**系统性双计费——299 轮 POST 里只有 5 轮(1.7%)碰了两个号，且都是 401/429 正当 failover；`committed_aborts` 全日志仅 2 次。「扣得一样」是 `_pick` 最少使用者优先**主动拉平**的必然结果，不是故障。残余真浪费只有两处：换号冷缓存（上一条）与断流后客户端重发（~7.4/天）。
  **★ 关键未知量（别当已知用）**：Codex 的周额度 `used_percent` 到底按不按缓存折价计量。若它对缓存/非缓存一视同仁，上面整套缓存分析对额度**零影响**。判别实验（grok 设计，尚未跑）：只留 1 个可用号跑固定工作量 W 得 Δ₁ → 恢复多号跑同一个 W 得 ΣΔ；`ΣΔ≈Δ₁` 则无翻倍，`ΣΔ≈2Δ₁` 才是真翻倍。**「眼睛看见两个号都涨了」不是 2× 的证据。**


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
