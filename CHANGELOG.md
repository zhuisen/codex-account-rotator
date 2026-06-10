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

---

## 已知待办 / cleanup
- `codex-rotate` 里 `_run_codex_ping`/`_codex_running`/`CODEX_BIN`/`LOCK`(autosync 内)是 keepalive 重写后的 **dead code**,可删。
- 代理刷新槽位 token 与 keepalive(04:30)理论可能并发刷同一号(实际重叠概率极低)。
- SwiftBar 额度归因:plain 模式靠 rollout 时间窗、代理模式靠 `x-codex-*` 头——两套已对齐,但跨模式快速切换的边界(±10s)可能短暂不准。

## 插件版本史
- `v0.6.0` 加版本号显示
- `v0.7.0` 版本号右对齐(padding,已废弃)
- `v0.7.1` 版本号并进 CODEX 头部行
- `v0.7.2` 修"代理服务在跑 ≠ 在用代理"(plain codex 号不刷新额度)
