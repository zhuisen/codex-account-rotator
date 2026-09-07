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
| `proxy/cxp` | 日常入口 = `codex --profile rotateproxy` | **所有子命令一律走代理**，没有例外分支 |
| `daemon/quota_daemon.py` | 让 `state.json` 的额度持续准确 | 三条循环全部零额度成本（GET） |

### 为什么必须走代理，而不只是"能轮换就行"

codex 有一条 WebSocket 响应通道，它**硬编码上游地址、不认 `base_url`**。关掉它的开关是
provider 的 `supports_websockets`，而**内置 provider 把它硬编码为 `true` 且不可覆盖**。

⇒ **「不走代理」= 「WS 直连」= 「整段会话钉死在一个号上，烧完即停」。**

所以走代理不只是为了轮换，也是**唯一**能让请求真正经过本机的办法。详见 `CHANGELOG.md` 的 B36。

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
