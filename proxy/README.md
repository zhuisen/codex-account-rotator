# codex-rotate proxy — 多号轮换代理(日常入口)

让原生 Codex 经一个**本机回环代理**(`127.0.0.1:8011`)透明地在你的多个 ChatGPT 订阅号之间轮换。
全程同一家庭 IP 出网、loopback-only、复用 `codex-rotate` 的账号池。

## 怎么用

- **日常**:用 `cxp` 代替 `codex`(参数完全一样)。它复用你真实的 `~/.codex`(MCP/hooks/profiles/模型设置),只把 model provider 换成本地代理。
  ```
  cxp                      # 交互
  cxp exec "修个 bug"      # 非交互
  ```
- **不想轮换**:照常用 `codex`(纯单号,走 ~/.codex/auth.json 的当前号),完全不受影响。

## 它做了什么(每个请求)

1. 从 `codex-rotate` 池按 **5h 用量最少 + 跳过冷却中** 选一个号;
2. 该号 token 过期就**自动 OAuth 刷新**(`auth.openai.com/oauth/token`,轮换后的 refresh_token 存回槽位);
3. 注入 `Authorization` + `chatgpt-account-id`,转发到 `chatgpt.com/backend-api/codex`;
4. 撞 429 就把该号标 5h 冷却,下个请求自动换号。

因为 Codex 每个请求都发**完整上下文(无 previous_response_id)**,跨号轮换对会话**无感、不用重启**;长会话的消耗自动摊到多个号上 ≈ 把 5 小时上限扩成 N 倍。

## 服务 / 开关

- 代理是 launchd 常驻:`com.doushutangmu.codex-rotate.proxy`(端口 8011,日志 `proxy.log`)。
- 停:`launchctl bootout gui/$(id -u)/com.doushutangmu.codex-rotate.proxy`
- 起:`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.doushutangmu.codex-rotate.proxy.plist`
- 看状态:SwiftBar 菜单顶部「代理轮换 开/关」,或 `lsof -iTCP:8011 -sTCP:LISTEN`。

## 已知限制(Phase 2 再优化)

- SwiftBar 的额度归因在代理模式下是近似的(代理逐请求换号,而面板按 codex-rotate 的「active」+ rollout 时间窗归因)。真正准确需代理侧逐请求记账(待做)。
- 代理刷新槽位 token 与 keepalive(每天 04:30)理论上可能并发刷同一号;实际重叠概率极低。

## 文件

- `proxy.py` — 代理本体(stdlib,复用 `../state.json` + `../auth/` 槽位)
- `cxp` — 日常入口(codex `-c` 覆盖 provider)
- `auth-token` — codex 的 auth.command 占位 token(代理会覆盖)
- `test-home/` — 隔离测试用的 CODEX_HOME(非日常)
