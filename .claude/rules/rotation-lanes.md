---
paths:
  - "**/rotation.py"
  - "**/LogsPage.tsx"
  - "**/proxy.py"
---

# 代理轮换泳道（path-scoped）

> 2026-09-16 从项目 `CLAUDE.md` **整段搬来，逐字未改**。
> ★ **刻意不翻译成英文。** 项目 `CLAUDE.md` 改用英文（见其 §3.8），但这里每一条都是
> **实测数字 + 当时的判断**，翻译只会磨损精度 —— 与 CHANGELOG「只准分卷不准摘要」
> 同一条理由：**搬运保真，翻译不保真**。
> ⚠️ **一处例外：搬运时做了脱敏。** 「逐字未改」对内容成立，对**指向具体账号的那几个字**不成立。
> `.claude/rules/*.md` 是**入库并推到公开仓库**的，而 `CLAUDE.md` 是 gitignored 的 ——
> **搬过去 = 公开**，边界跟着内容一起变了。所以本机真实账号名（标签与 Google 账号名）
> 一律换成 `某个 Plus 号` / `A 号` 这类占位，**实测数字一个没动**。
> 往这里再搬内容时同样处理；闸在 `tests/test_doc_boards.py::TheCommittedRulesCarryNoLocalFacts`
> （两条：形状模式 + **从本机池子现读真实账号名**，后者已双向变异验证）。

## 5b. 代理轮换泳道（v1.4.0）

引擎 `traffic/rotation.py`（纯模块，可按路径 import），Rust 只起进程 + 快照缓存，前端 `LogsPage.tsx`。

- ★★ **token 归属靠 `response_id` 精确 join，不是按时间猜**。`proxy.log` 的 affinity 行
  `[proxy … #resp_<完整id>] affinity … → [plusN]` 与 rollout 的 `token_usage_record.response_id`
  是**同一个 id**。实测 942 条命中 727（77%）；**对照：300 个随机同形 id 命中 0** ⇒ 不是碰运气。
  按时间猜会在两个号交替的边界上把 A 的消耗记到 B 头上，而画出来完全正常。
- ★★★ **`proxy.log` 里 `[...]` 的东西以前是「显示名」，现在带身份与类型**（2026-09-12，用户实报
  「改了名字，代理轮换版块没匹配上，变成新建名字」）。两条根因同一个形状：
  ① **label 用户可改，而日志只追加** ⇒ 改名前的行永远停在旧名字上 ⇒ 同一个号劈成两条泳道，
     旧名那条在池子里查不到 ⇒ **plan / 额度 / 配色全丢**（实测同一个号被劈成两条：旧名 10 req、新名 12 req）。
     与四方评审 #4 是同一条根：**身份必须是 aid**。
  ② **账号与中转站上游共用同一个 `[...]` 句式**，没有类型标记 ⇒ 下游没有任何办法分辨 ⇒
     `TokenDun` 被当成账号画进泳道（实测 5 req）。
  现在：`proxy.py::_acct_tag` 写 `label#aid8`、`_relay_tag` 写 `name@relay`；
  `rotation.py::_first_tag` 三路解析，`make_resolver` 把历史名字归一成**当前** label；
  `rename` 记 `label_history`，`codex-rotate alias <旧名> <号>` 给改格式之前的历史补账。
  ⚠️ **历史行永远不会消失**（本机 8MB 全是裸名字），所以每条修法都必须对旧格式也成立 ——
  中转站的历史行靠 reason `relay` 认，`@relay` 后缀只对 `affinity` 那条路径是唯一判据
  （`←` 行认不出来，但它本来就被丢弃，**这是"确实不需要"不是"没打中"**）。
  ★ aid8 撞前缀时**不解析**（宁可不并，也不并错：并错会把 A 的 token 记到 B 头上且画出来完全正常）。
- ★ **合计是下界不是总量**：只有走过代理的响应能归属，直连 `codex` 的请求永不进来。
  所以那格标签写「**已归属** token」。把下界当总量画 = 编造。
- ★ 用 `usage`（该次响应）不是 `turn_token_usage`/`thread_token_usage`（**累计**）——取错会随轮次平方级虚高。
- **只有 POST /responses 切在岗段**；`GET /models` 是纯探活，算进去会画出假的在岗块。
  同号间隔 > `SEG_GAP_SECS`(900s) 也要断开，否则整夜没流量会被画成一条 8 小时在岗块。
- ★ 归属落段取**距离最近**的那一段，不是第一个落进容差的 —— 同号多段时会张冠李戴且看不出来。
- ★★ **Pro 在岗 ⇒ 当时没有任何可用 Plus**（策略 C 直接推出）。所以单列 `pro_fallback`，
  它等价于「Plus 池干了」。判据看 `plan` 不看 label。染紫不染红：按设计工作，不是故障。
- 三类失败的**计费含义不同，不可合并**（§8「计费相位分界」的展示层投影）：
  `send err`=未计费 · `stream err`=已计费 · `committed`=**可能已计费**（唯一危险级）。
- **缓存与快照**：按 `st_mtime_ns`+size 缓存**整份 rollout** 的解析结果（只存"窗口内那部分"的话
  换个窗口就全失效）。成品快照 `.rotation-latest.json` 按窗口分键，UI **先画快照再后台重扫**
  —— 实测热缓存 7d **3.00s → 0.65s**，冷路径 1h 0.9s / 24h 1.7s / 7d 3.3s。两者都 gitignored。
- ★ 配色 `assign_colors`：散列偏好 + **线性探测**。纯散列实测当场撞车（6 个号进 6 色板，
  其中两个号同紫），而两条同色泳道不会报任何错。
- ★ 泳道名字列 `NAME_W=152`，名字 `flexShrink:0` 且**不加省略号** —— 最坏情况是
  `名字 + PRO + 当前` 三样并排（118 时被截成 `Pr…`）。⚠️ **这类缺陷 harness 抓不到**：
  `textOverflow` 只改渲染，DOM 文本仍完整，探针读的是 DOM。只能看像素（`?rot=procur`）。
- harness 开关：`?rot=ok|procur|undated|empty|fail|snaponly` · `?tipseg=<n>`（浮层）·
  `?focusacc=<号>`（聚焦）。★ 这两个驱动**必须轮询等待**，泳道要等异步 IPC 才渲染，
  固定延时会命中 0 个而看着像选择器写错。★ 浮层要派发 **`mouseover`** 不是 `mouseenter`
  —— React 的 `onMouseEnter` 是合成事件，靠根节点 mouseover 委托。
