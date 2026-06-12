# codex-rotate · CHANGELOG & BUG LOG

构建于 2026-06-09 ~ 06-10。插件版本号见 `swiftbar/codex-status.10s.py` 的 `VERSION`(改插件必 bump)。

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
