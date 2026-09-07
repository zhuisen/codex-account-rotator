# 排障

每条都是**症状 → 判据 → 处置**。判据优先给能一眼跑的命令 —— 猜测在这个项目里代价很高，
几乎每条都是花时间买来的。

## 会话跑一半说「额度用完了」然后停住，重开一个新会话就能用

**这不是额度真的用完了。** 判据：

```bash
sqlite3 ~/.codex/logs_2.sqlite \
  "select count(*) from logs where target like '%responses_websocket%' and ts > strftime('%s','now')-86400;"
```

大于 0 ⇒ 有 turn 走了 codex 的 WebSocket 通道。那条通道**硬编码上游地址、不认 `base_url`**，
完全绕过本机代理 ⇒ 没有轮换，只烧当前那一个号。

**处置**：确认你走的是 `cxp`（`codex` 应当 alias 到它），且 `[model_providers.rotateproxy]`
里有 `supports_websockets = false`。**不要**试图给内置 provider 加这一行（配了也被忽略），
也**不要**新建一个 provider 当默认（会让 `codex resume` 列表直接清空）。详见 B36 / B37。

## `codex resume` 列表变短了

**正常。** picker 按 provider **逐字**过滤，只列当前 provider 戳记的会话。
走代理之后只显示 `rotateproxy` 戳记的。

旧会话**没有消失** —— `codex resume <session-id>` 照样能进。往后新会话都是新戳记，列表会自己长回来。

## `codex resume` 列表**完全空了**

你（或某个 AI）把默认 provider 换成了一个新 id。**存量会话没有一个带这个戳记 ⇒ 匹配数为 0。**
回滚 `~/.codex/config.toml` 即可（该目录下有 `*.bak-*` 备份）。B37。

## 改了代码但行为没变

这个项目有**三个**独立的「改了没生效」陷阱，症状一模一样：

| 陷阱 | 判据 | 处置 |
|---|---|---|
| 守护进程还在跑旧代码 | `codex-rotate health` 末尾那行 | `launchctl kickstart -k gui/$UID/com.doushutangmu.codex-rotate.{proxy,quotad}` |
| app 还是旧构建 | 比对 `/Applications/CodexBar.app` 的 mtime 与你改的源文件 | `bash codexbar/scripts/deploy.sh` |
| launchd 定时任务被外力改写、静默从未运行 | `launchctl print gui/$UID/<label> \| grep runs` | 重跑 `scripts/install-launchd.sh`（会被再次改写，原因未查明） |

★ `deploy.sh` **只换 app bundle，从不重启守护进程** —— 两件事要分别做。

## 额度数字显示「未知」或「待确认」

**这是设计，不是故障。** 本项目的铁律是「读不到 ≠ 确实没有」：

- 「未知」= 窗口已过重置时刻但还没拿到新读数。绝不显示成「满额」。
- 「待确认」= `resets_at` 看起来像服务端回的浮动占位值（窗口一次都没被用过），
  倒计时不可信，但**水位是可信的**。
- 「未启动」= 锚点账本连续观测到 `resets_at` 跟着当前时间滑动 —— 这是一句**有观测支撑**的话，
  不是猜测。

## codex 挂死、零输出、代理日志一条都没有

系统代理（Clash 等）把发往 `127.0.0.1:8011` 的请求也吞了：Clash 对 loopback 目标
**连接受理、永不响应**。

⚠️ 系统代理的例外表里**本来就有 `127.0.0.1`，reqwest 无视它** —— 在 Clash 里配 bypass 没用，
只有进程级 `NO_PROXY` 管用（`cxp` 里已经 export，别删那两行）。

误导性症状：stderr 报 `timeout waiting for child process to exit` —— 与子进程无关，顺着它查会走死。

## `GET /backend-api/codex/usage` 恒 403

macOS 自带的 `/usr/bin/python3` 链 LibreSSL，Cloudflare 按 TLS ClientHello 指纹拦；
OpenSSL 3.x 同一请求恒 200（受控实验，单一变量各 3 次）。

**装 `brew install python3`**。launchd 的默认 PATH 只有 `/usr/bin:/bin:…`，必踩。

★ 用 macOS 自带 `curl` 复现「也被挡」**不算独立证据** —— 它链同一个 LibreSSL，是同一个失败模式。

## 想验证某个配置改动到底生效没

**「没报错」证明不了任何事** —— codex 对未知配置键是静默忽略的。

要用**有判别力的对照**：故意写一个不存在的 provider id，它会报 `Model provider ... not found`；
如果连这个都不报错，说明你的探针本身是坏的。

同理，验「WebSocket 还发不发生」**必须用交互式会话** —— `codex exec` 那条路本来就不用 WS，
拿它测会得到实验组、对照组**都是 0** 的假绿。
