# 架构

四个常驻件 + 一个 CLI + 一个展示层。**账号池**和**用量统计**是两条互不相干的链路，
共用一个界面——搞混这一点是读这个仓库最常见的误解。

```
                    ┌──────────────── 账号池链路（碰凭证、会花钱）
                    │
  codex CLI ──cxp──▶ proxy.py :8011 ──▶ chatgpt.com
                    │      │
                    │      └─ 逐请求挑号（按额度）· 429 冷却换号 · 过期自动刷新
                    │
  codex-rotate  ────┤  账号池 CLI：add/login/switch/health/quota/probe/dawn-probe
                    │
  quota_daemon  ────┘  三条循环：活动驱动 · rollout tail · 300s 全池扫描
       │
       ▼
   state.json ◀────── 五个进程同读写，锁序恒 state → cred
       │
       ▼
   CodexBar (Tauri) ─── 只读展示；两个 webview（主窗 + 菜单栏）


                    ┌──────────────── 用量统计链路（不碰凭证、不联网、零额度）
  traffic/scan.py ──┤  扫 8 个本机 CLI 自己落的盘 → .traffic-latest.json
                    └  Claude / Codex / Grok / Kimi / Antigravity + 3 个宿主源
```

## 账号池链路

| 件 | 职责 | 关键约束 |
|---|---|---|
| `codex-rotate` | 账号池 CLI，单文件，最重要 | 解释器**绝不由 PATH 决定**（TLS 指纹问题） |
| `proxy/proxy.py` | 轮换代理 `127.0.0.1:8011` | 对 live 号**只读**，过期就 failover；绝不刷 active 号的 token |
| `proxy/cxp` | 日常入口 = `codex --profile rotateproxy` | **所有*运行时*子命令一律走代理**，没有例外分支；`doctor`/`update`/`plugin` 等本地工具子命令原样透传（codex 0.154 起对它们带 `--profile` 会硬报错） |
| `daemon/quota_daemon.py` | 让 `state.json` 的额度持续准确 | 三条循环全部零额度成本（GET） |

### 为什么必须走代理，而不只是"能轮换就行"

codex 有一条 WebSocket 响应通道，它**硬编码上游地址、不认 `base_url`**。关掉它的开关是
provider 的 `supports_websockets`，而**内置 provider 把它硬编码为 `true` 且不可覆盖**。

⇒ **「不走代理」= 「WS 直连」= 「整段会话钉死在一个号上，烧完即停」。**

所以走代理不只是为了轮换，也是**唯一**能让请求真正经过本机的办法。详见 `CHANGELOG.md` 的 B36。

## 中转站链路：一个 provider，两种上游

账号池是订阅制（免费，但撞额度要等重置）；中转站是第三方 OpenAI 协议 relay，按量付费
（实测单次 `codex` 调用 **$0.0863** —— tokens used 39,513，系统提示 + 工具定义就这么大）。
两者是**同一件事的两条路由**，同时只有一个生效。

```
codex ──> cxp ──> --profile rotateproxy ──> proxy.py
                                              │
                        每请求读 relay/route.local.json
                                              │
                        ┌─────────────────────┴─────────────────────┐
                   route = pool                              route = <relay-id>
                        │                                            │
             轮换账号池的 OAuth token                    注入该中转站的 api key
             + chatgpt-account-id 头                      **绝不带 account-id 头**
                        ↓                                            ↓
              chatgpt.com/backend-api/codex              https://<relay>/v1/responses
```

**为什么切换发生在代理内部，而不是给每个中转站一份 codex profile。**
早期实现是后者：每站一个 `~/.codex/<id>.config.toml`，靠 `cxp` 换 `--profile` 切。
问题是 `codex resume` 的 picker **按 `model_provider` 过滤，而 0.154 里没有任何配置键能放宽它**
（二进制里所有含 provider 的键都查过）—— 每多一个 provider id 就多一份互相看不见的会话列表。
让代理去分叉之后，codex 眼里永远只有 `rotateproxy`，会话列表只有一份；
`profile_missing` / `profile_stale` / `orphan` 三个**静默失败态**也随之消失
（它们全部源于"第二份 profile 文件与登记表不同步"）。

**三条不变量。**

1. **计费相位分界。** 账号池那条路有 failover：`SendFailed`（可证明没发出去）可以重试，
   `UpstreamCommitted` 必须中止。**中转站那条路没有 failover** —— 单上游，`"NEXT"` 是终态，
   401 也不转发给 codex（转发会触发它去重登，而 `codex logout` 在本仓是杀号）。
   两条路的断流计数器因此也是分开的（`stream_aborts` vs `relay_stream_aborts`）。
2. **`chatgpt-account-id` 永不出现在发给第三方的请求里。**
3. **三个「钱」永不合并**：中转站的 `cost`（对方按上游牌价记的账）、`actual_cost`（真实扣款，
   实测与前者差 3.85 倍）、以及「AI用量」页那个按 OpenAI 牌价折算的**等效**成本
   （订阅制下并没有真付）。经中转站的 token **绝不许用 `rates.ts` 乘**。

**用量是只读的、零计费的。** `relay/monitor.py` 打对方的 `/usage`（端点各家不同，要探测并记住），
快照 `.relay-usage.json` **只增不减**：取数失败保留旧值并标 `stale`，`daily` 按日期并集合并 ——
上游窗口会滑动，每次整块替换会让滑出去的日子**永久消失**。

---

## 用量统计链路

`traffic/scan.py` 只读各家 CLI 自己落的盘，**零额度消耗、不联网、不碰凭证**。
八个数据源，加一家 = 写一个 `_scan_*` + 在 `SOURCES` 加一行，前端不用动。

⚠️ 这条「不碰凭证」的安全线**按目录判定**：`grok-quota` / `agy-quota` 会读凭证或打接口，
所以它们**刻意放在仓库根、不在 `traffic/` 里**。别把它们挪进来。

### 四家的 token 口径不一样，必须先归一

- codex / Grok：`total = input + output`，且 `cached ⊆ input`
- Claude / Kimi / Antigravity：各输入字段**互不相交**

`scan.py` 统一折成四个互不相交的类：`uncached_in | cache_read | cache_write | output`。
直接把四家的 `total` 摞在一张图上，就是拿四把不同的尺量同一根线。

## 额度窗口：两个容易混的概念

| | 是什么 | 谁在用 |
|---|---|---|
| `primary` / `secondary` | **槽位名，不是窗口时长** | 服务端返回的结构 |
| `window_minutes` | 真正的窗口时长（300 = 5h，10080 = 周） | 判断窗口语义只能看它 |

★ Plus 的 `primary` 是 5h 窗口、Pro 的 `primary` 是周窗口。**把两者的剩余百分比排在同一条轴上
比大小是不成立的** —— 一个「周额度烧光但 5h 刚重置」的号，按 `primary` 看是全池最空的。

## 展示层

CodexBar = Tauri 2 + React，**唯一有构建系统的地方**。两个 webview（主窗 + 菜单栏）是
独立 JS 上下文，`localStorage` 不互通，跨窗口同步只能走 Tauri 事件：数据、完成信号、
**以及进行态**（`useBusyMirror`）三样都要广播，少一样就会出现「一边在转圈、另一边像没事发生」。

主窗五个导航项：**总览**（账号池）· **AI用量信息** · **日志** · **中转站** · **设置**。
中转站页内再分「账号 / 用量」两块（两块都挂载、CSS 隐藏 —— 条件渲染会在切 tab 时
把填了一半的表单清空）。版式按 `design_handoff_codexbar/中转站-交接说明.md`
1:1 复刻（2026-09-10）：账号块是「当前出口」两张同权卡 + 中转站表格，
用量块是**每模型一张小图卡**（每卡独立 y 轴）而不是堆叠面积图 ——
堆叠图回答"这段时间的构成"，而这一页被问的是"**哪个模型在烧钱**"。

★ **同一个 sidecar 的所有实例共享一次取数**（`useQuotaSidecar` 按 `runCmd` 去重 + 广播）。
两个组件各挂一个 hook 时，原来会各起一次 python 子进程、各打一次外网，
且手动刷新的 `force:true` 让后端的合并窗口失效 ⇒ 同一屏上的两个数最多差一个刷新周期。
