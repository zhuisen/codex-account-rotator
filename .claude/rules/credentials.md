---
paths:
  - "**/codex-rotate"
  - "proxy/**"
  - "agy/**"
  - "**/agy-rotate"
  - "**/agy-quota"
  - "daemon/**"
  - "**/bin/agy"
  - "**/grok-quota"
  - "**/grok-quota-sampler"
---

# 凭证与额度（path-scoped · 花钱买来的那一半）

> 2026-09-16 从项目 `CLAUDE.md` **整段搬来，逐字未改**。
> 搬走的理由是预算：正文顶到 110 KB 的闸，而这一节占 47.3 KB，
> 且**只在碰凭证/额度相关文件时才有用**。
> ★ **刻意不翻译成英文。** 项目 `CLAUDE.md` 改用英文（见其 §3.8），但这里每一条都是
> **实测数字 + 当时的判断**，翻译只会磨损精度 —— 与 CHANGELOG「只准分卷不准摘要」
> 同一条理由：**搬运保真，翻译不保真**。
> ⚠️ **一处例外：搬运时做了脱敏。** 「逐字未改」对内容成立，对**指向具体账号的那几个字**不成立。
> `.claude/rules/*.md` 是**入库并推到公开仓库**的，而 `CLAUDE.md` 是 gitignored 的 ——
> **搬过去 = 公开**，边界跟着内容一起变了。所以本机真实账号名（标签与 Google 账号名）
> 一律换成 `某个 Plus 号` / `A 号` 这类占位，**实测数字一个没动**。
> 往这里再搬内容时同样处理；闸在 `tests/test_doc_boards.py::TheCommittedRulesCarryNoLocalFacts`
> （两条：形状模式 + **从本机池子现读真实账号名**，后者已双向变异验证）。
> ★ 这里是**正本**；`CLAUDE.md` 只留一行红线摘要与路由。

## 8. ★ 踩过的坑（花钱买来的，改凭证/额度前必读）

- ★★ **`codex login` / `codex logout` 会把当时躺在 `~/.codex/auth.json` 里的那个号在服务端 revoke**（受控实验三轮确证，症状伪装成"这台电脑只能登 2 个号"）。加号/重登**只用 `codex-rotate login`**：syncback → 把 auth.json 整个 `os.replace` 移到 `.rotator-stash` → 在本机无 token 状态下登 → 失败/Ctrl-C 自动还原。机制仍是假说（H1/H2/H3 见 `codex-rotate` 的 `cmd_login` 注释），此法在三种假说下都不更差。
- ★ 拦截必须放 **PATH wrapper**（`~/.local/bin/codex`，仓库备份 `scripts/codex-wrapper-with-logout-guard.sh`）：`\codex logout` 的反斜杠只绕 alias、绕不过 PATH。
- ★ `resume` / `fork` 的原生 picker、`--all`、session name 和 session ID 都必须透传；PATH wrapper 只拦会跳过人工选择并自动接入最近 thread 的 `--last`。新任务仍用 fresh `codex` 或 `/new <task-name>`；恢复同一任务可直接 `codex resume` 选择，跨目录选择用 `codex resume --all`。本地只读 `codex sessions` 仅作为查 ID 的辅助入口。
- ★ **绝不刷 active 号的 token**：refresh_token 一次性轮换，codex 原生刷新器不持我们的 flock，插手 = 两边互相作废（B7/B8/B14 连环杀号）。proxy 对 live 号**只读**，过期就 failover 换号。
- ★ **判死活用 `GET /backend-api/codex/models`，不是 `/usage`**：`/usage` 有 bot challenge，健康号照样 403，曾误判成全池死亡。403 只降级为"额度未知"。
- ★ **看额度只走 `GET /backend-api/codex/usage`（零消耗）。`POST /responses` 是真计费**——旧版拿它当自动额度探测，新周额度模型下每天烧 17-18%，已废除。
  - 手动的计费探针保留为 `codex-rotate probe <label…|--all> [--model M] [--effort low|medium|high]`：问「hi」要求原样答「ok」，`effort=low`。
    - ★★ **默认模型不写死，从 `<CODEX_HOME>/models_cache.json`（codex 自己的权威清单）现挑**，偏好序便宜优先（实测同代 luna $0.038/M vs sol $0.840/M，差 22 倍），写死的只作兜底。
      起因是 2026-09-06 的事故：原来写死的 `gpt-5.4` 被上游下架，**每次探针都 400**、一个请求都没成功 ⇒ 5h 窗口永远锚定不了 ⇒ 用户报「我探针了，额度还是没刷新」。**把上游模型名写死在一个必须长期能用的工具里 = 预约一次故障，而且它坏得没有声音。**
    - ★ 只认 `models[*].slug` **一层取值**，不做递归遍历：每条模型记录里还有 `upgrade` 字段指向**推荐升级到的另一个模型**，递归会把它当成可用（实测夹具选中一个清单里没有的模型）。顺带也没了「深层 JSON `RecursionError` 打死 CLI」那个边界。跳过 `visibility: "hide"`（`gpt-reserve` / `codex-auto-review` 不是给人聊天用的，选中同样 400）。
    - ★★ **`slot["last_probe"]` 独立兄弟键**记每次运行结果（成功/失败/**跳过死号**都写），`completion_ok` 与 `quota_ok` 分开。理由：探针写回的 `quota` 会在 20~300s 内被 quotad 的 usage-api **整体替换**，于是 state 里永远找不到 `source == "probe"`，「到底探成没有」事后无从查证 —— 这次事故正是卡在这里，我据代码注释错误地答过一次「探针没坏」。**刻意不存 used%**：一份事实一个家，存两份 20 秒后就分叉。
    - ★ 「模型不被支持」的 400 单独给**可执行的下一步**（去哪查清单 / 怎么 `--model` 覆盖），不是甩一串原始 JSON。回答 `/models` 回答不了的问题——**「这号真的还能干活吗」**（订阅到期 / 模型权限被撤 / 被限流，token 有效也照样失败）。实测单次 Δ+0%（1% 整数位不动 ⇒ 成本 <1%，这是上界不是点估计）。
  - **判据是「模型真吐出字」，不是 HTTP 200**：200 只说明请求被受理，流中途断掉照样 200，报「能用」就是假阳性。`_sse_answer()` 拼 `response.output_text.delta` 取回原话并打印；空回答判失败。答非所问只标 ⚠️ 不算失败（模型换措辞不代表账号有问题）。
  - **不接 quotad、无任何定时器**（自动计费探测正是被废掉的那个）。GUI 有三个入口：主界面工具栏「探针 全池」、卡片动作条「探针」（单号）、菜单栏底栏第三格。三处共用 `ProbeButton`——**琥珀 + ⚡ + 「计费」角标 + 两段确认**（单击只亮「确认?」，5s 无二次点击自动退回）。这是全 app 唯一花钱的控件，必须与旁边带「免费」角标的按钮一眼可分；确认逻辑只写一份，三个界面各自手搓迟早有一个漏掉护栏。
  - ★★ **每日清晨探针 `dawn-probe`（v1.2.0，用户 2026-09-06：「早上 6 点给 Plus 号探针，让 5h 额度走动」）—— 本仓唯一会自动花钱的东西。**
    上面那句「不接 quotad、没有任何定时器会调它」**对 `probe` 仍然成立**；`dawn-probe` 是**另一个**命令，它自带三条护栏，改它之前先读完：
    - ★★ **先占天再探**：日期标记写在**发请求之前**（`_mutate_state` 持跨进程锁）。launchd 06:00 与 app 内补跑**两条路都会调它**，写在探测之后的话，那段窗口里第二个进程看到的仍是昨天的日期 ⇒ **双重计费**。3 进程并发实测：恰好 1 个进到探测阶段。⚠️ 代价是显式的：探测中途崩了今天不重试（日期已占）——在「少跑一次」和「可能多花一次钱」之间这个工具一律选前者。
    - **默认关闭**（`dawn_probe.enabled` 缺省假）。仓库已公开，默认开启的自动计费定时器会在别人机器上悄悄花钱。
    - **按 `plan` 判 Plus，绝不按 label** —— 老号从 Plus 升 Pro 时 label 一个字都不变，按名字挑会在升级那天开始给没有 5h 窗口的 Pro 号花钱，钱花了目的没达到且没有任何症状。
    - **模型不写死**：走 `PROBE_MODEL`（现为 gpt-5.6-luna）/ `PROBE_EFFORT`（low），默认值从 codex 自己的 `models_cache.json` 现挑 —— 写死正是 v1.1.1 那次事故的成因。
    - ★★ **为什么 launchd 之外还要 app 内补跑**：本项目的日历定时**有前科** —— keepalive/refreshquota 的 `StartCalendarInterval` 被 `install-launchd.sh` 以外的东西改写丢掉，`runs = 0`、**从未运行过**，而没有任何一处会为此报红（改写者至今未查明，见 §3）。所以那个 plist **不能是唯一触发路径**。补跑挂在**菜单栏 webview**（启动即创建、从不卸载）。判据是「今天过了 6 点、而 state 里记的日期不是今天」，**不是**「现在正好 6 点」—— Mac 凌晨多半在睡，卡点判定等于永远不触发。
    - **开关与状态的真源是 `state.json` 的 `dawn_probe`，不是 localStorage** —— launchd 在 app 没开时也要读它，两个真源迟早分叉成「界面说开着、定时器不认」。设置页那一格因此走 CLI (`dawn-probe --status/--enable/--disable`)。
    - ★ **设置页必须显示「上次运行」** —— 它是「定时到底跑没跑」的唯一可见证据，就是上面那个 `runs = 0` 前科的闸。闸在 `tests/test_dawn_probe.py`（15 条，3 次变异全红，全部在临时 store 上跑、不发任何请求）。
    - Windows 侧等价任务在 `install-windows.ps1`（`CalendarTrigger` 06:00），**刻意不 `/Run`** —— 装 ≠ 现在就跑一次计费任务。两边服务集合一致由 `tests/test_installers_agree.py` 守着（这次就是它当场抓出我只改了 macOS 一边）。
  - 它**不标记 `auth_dead`**：改号池成员资格是那两个带防抖守卫的检测器的事，测试工具再插一手会把"两端点互相打架→每轮翻转→反复告警"请回来。
  - 只对 `req err`（连不上/TLS 断）重试一次；HTTP 4xx/5xx 是服务端已判决，重试只白烧额度。实测某个 Plus 号报过一次 `SSL: UNEXPECTED_EOF`，紧接着连测三次全 200——不重试就会把网络打嗝写成"这号挂了"。
- ★★ **会话粘性的 key 是 `prompt_cache_key`，不是 `previous_response_id`**（2026-08-09 实测 body 键名确认）。codex 每个 `POST /responses` 都带前者、从不带后者——所以老的 `_affinity` **一次都没命中过**（2291/2291），每轮都在重新挑号。`prompt_cache_key` 正是 OpenAI 标识 prompt cache 血缘的字段，同一会话恒定，拿它做粘性等于"同一段对话恒定落同一个号"的硬保证。选号优先级：`conv` > `affinity` > 迟滞 > 最少使用者，**每一层都先过 `ok()`**（dead/冷却/本轮已试过一律不粘），所以粘性永远挡不住 failover。
  - ⚠️ **别把它当"省额度"的措施**（我 2026-08-09 一度这么写，错了）。`total_tokens` 本来就**包含**缓存命中的部分，冷启动改变的是这些 token 的**价格**而非**数量**；订阅制下只有额度百分比、没有价格，所以换号在额度上不多花。它的价值是**可预测性**（一段对话恒定落一个号）+ 对冲「计量是否折价缓存」这个未定量。
  - ★ **「6 次比 139 次还贵」是分母不同，不是冷缓存**（用户纠正，实测证实）：Pro 周预算约 **1.85B** token、Plus 约 **250M**，差 7~8 倍，所以同样烧 6~7M token 在 Plus 上是 3%、在 Pro 上不到 0.4%。用 token 对齐后三个 plus 号的缓存命中率 **92~98%**，与那个 Pro 号的 95.3% 无差异——切过去并没有冷启动。
  - **额度计量算不算缓存,尚未定论**：n=3、Δ% 只有 2~3（整数量化 ±50%）。方向性证据是「每 1% 对应的 **total** token」离散 1.5 倍、「对应的**未命中** token」离散 6.6 倍 ⇒ 更像按 total 计量。已加 `state.json` 的 `quota_marks`（跨整数百分点时记一条）攒每请求级样本。**在有结论前，别用"省缓存=省额度"做任何决策。**
- ★★ **选号策略 C：Plus 优先、Pro 保底**（用户 2026-09-07 定；`proxy.py::_plan_tier` + `_tightest_used`）。
  Plus 平时承担轮换，**Pro 只在没有任何可用 Plus 时才动**。读不到 `plan` 的归 **Plus 档** ——
  归到保底档会让刚入池、还没解出 plan 的号永远排最后、拿不到流量。
  · **顺带修掉一个真 bug**：旧的 `_used()` 按 `(primary, secondary)` 字典序排，而 `primary` 是
    **槽位名不是窗口时长**（Plus 的 primary 是 5h、Pro 的是周）。于是「周额度 100% 烧光、
    5h 刚重置回 0%」的号按 primary 看是**全池最空的** —— 实测某个 Plus 号被排全池第一，
    每次 5h 重置都重排第一、白撞一次 429。改用**最紧窗口**，与 `helpers.ts`、`_headroom` 三处一致。
    `_used()` 已删（`git show v1.3.0:proxy/proxy.py` 可查）。
  · ★ **迟滞不得跨档**：原来只比 `primary` 百分比，粘在 Pro 上的会话会因为「没比最省的 Plus 贵多少」
    而一直粘着，把「Pro 保底」静默绕过。闸在 `tests/test_pick_policy.py`。
- ★★ **按号开关自动轮换**（用户 2026-09-07；`codex-rotate rotate <label> --on|--off`，总览卡片动作条）。
  · 真源是 `state.json` 的 **`rotate_off`**，不是 localStorage —— 代理在 app 没开时也要读它
    （同 dawn-probe）。存**反向**命名是因为**缺省必须等于「参与轮换」**：存量号与 autosync 新号
    都没有这个键，正向命名要写迁移，漏迁移的号会**静默退出轮换池**（症状：代理只用那两三个号，零报错）。
    恢复时**删键**不是写 `False`，否则"缺省"有两种表示。
  · **CLI 拒绝关掉最后一个**（全关 = 无号可挑 = codex 整个不能用）；代理侧另有 fail-open 兜底
    并**写日志**（手改 state.json 绕过 CLI 时）——在「工具变砖」与「多用一个号」之间选后者，但绝不静默。
  · 会话粘性（`conv`/`affinity`）**也过这道闸**，否则已粘在 A 上的对话会继续用 A，
    而用户以为自己把它摘出去了。闸在 `tests/test_rotate_toggle.py`。
- ★ **选号迟滞（`PICK_HYSTERESIS`，默认 5 个百分点）是上面那条的兜底**（覆盖没有 `conv` 的请求，如 GET 或非 codex 客户端）。别把它当"负载不均"改回去：`_affinity` 依赖 `previous_response_id` 而 codex 从不发（2291/2291），粘性从未生效；服务端只回**整数** `used_percent`，多个号打平后会来回横跳，而**每次换号 = 整段历史在新号上冷缓存全价重算**。实测缓存命中率 95~99%（推翻了「cached_tokens 恒 0」的旧结论），冷大请求占未命中 input 已升到 27.2%（8月）。迟滞只放弃「百分比完全拉平」这个本来就不是目标的性质，不平衡上界钉在 5 个百分点。耗尽/冷却/dead 判断完全不参与迟滞。回退：`CRP_PICK_HYSTERESIS=0`。
- ★★ **订阅到期日续费后不更新，是 OpenAI 那边的事，别再往我们这边查**（2026-08-11 实测定稿）。`sub_until` 唯一来源是 id_token 的 `chatgpt_subscription_active_until`，而同一个命名空间里还有 **`chatgpt_subscription_last_checked`** —— **签发新 token 时 OpenAI 不重新查计费系统，只把上次复核的订阅快照原样抄进去**。
  - 实测：对两个非活跃号 `refresh --force` 刷出**全新** id_token（`iat` 就是当天），里面的 `last_checked` 仍是 11 天前的 07-30，`active_until` 纹丝不动。**刷新拉不到新订阅状态，没有办法强制它复核。** 对照：某个 Pro 号的 `last_checked`（08-08）晚于其订阅起始日，所以它的日期是准的。
  - 复核间隔 n=4 看着像一周多一次，**样本太少，别当规律用**。
  - `GET /backend-api/codex/usage` 只回 `{rate_limit, plan_type, credits}`，**没有订阅期**——想找别的来源得按 §7 那条去 `strings` 挖二进制，尚未做。
  - ★ 顺带查出并修掉**我们自己的两个缺陷**（独立成立，在上述结论下也照样要修，否则 OpenAI 哪天复核了你也看不到）：① `_refresh_slot` 拿到新 id_token 却**从不调 `_stamp_identity`**（其余四条写槽位的路径都调了）；② 两个刷新调用点（手动 / keepalive）只做定向 RMW 回写 `last_refresh`，身份字段写进内存即被丢弃 —— 抽成 `_refresh_patch(slot)` 一并落盘，**两处形状相同，各写一份迟早只改一处**。
  - 新增 `refresh [label] --force`：access token 通常还剩一周多，不 force 会直接 `still valid` 跳过，永远拉不到新 JWT。`skip-active` 守卫在 force 下**依然生效**。
  - UI：到期日已过 **且** `sub_checked` 早于它 ⇒ 标琥珀 `*` + 悬浮说明，**不再断言「已过期」**。理由是 app 自己的健康检查同时说这号是活的，两个信号本来就矛盾；同重置卡「`cards>0 && cardDays==null` 显示到期未知」那条原则。
- ★★ **额度窗口不变量（2026-08-25 改写，旧版已作废）**：**判「有没有值」，不判「够不够大」** —— 真实窗口 = `window_minutes > 0`，要丢的只有 Codex 仍在返回的空槽 `{window_minutes: 0, resets_at: null}`。
  - **旧规则「只有 >= 5000 才是真实窗口」已被推翻**：Plus 的 **5 小时窗口 2026-08-25 回来了**（实测 `primary.window_minutes = 300`，weekly 退到 `secondary`；Pro 号目前仍只有周）。旧判据会把它当垃圾丢掉，用户看不到自己的 5h 额度。
  - **教训不是"阈值调小点"，是别用量级去猜语义**。2026-07 真窗口只剩周/月时，「够大」**恰好等价于**「非空」，于是用了那个代理判据；量级一变，等价关系断了，而且**断得很安静**。
  - ⚠️ **同一判据有三份副本，跨语言没法共用**：`helpers.ts` 的 `REAL_WINDOW_MIN` · `codex-rotate` 的同名常量 · `lib.rs` 托盘那段。漏改任一份的症状是「有的地方看得见 5h、有的地方看不见」，**没有一处会报错**。闸在 `tests/test_quota_windows.py`。
  - ★ **窗口标签按实际时长分档**（月 ≥40000 / 周 ≥10000 / N天 ≥1440 / Nh），不是 `>=40000 ? 月 : 周`。旧的两分法会把 300 分钟标成「周」—— **那比不显示更糟：它把 5 小时的余量说成一周的余量**。
  - ★★ **单个汇总数字一律取「最紧」的窗口**：hero 环、卡片环、菜单栏行、托盘标题、差值角标的基准 `bestPct`，全部用 `tightest`，**不用 `windows[0]`**。`windows[0]` 是 primary，而 plus 的 primary 现在是 5h —— 用它等于**把真正的约束藏起来**，且显示的还是个正常的绿数字。只有卡片下方"有空间列清单"的细条才把 `windows` 全画出来。这个缺陷在 5h 缺席的那一年里**不可能暴露**（只有一个窗口时两者恒等）。
- ★★ **额度对象要按 `limit_id` 认身份 —— 新版 Codex 一条会话记录里有好几套额度**（2026-08-28，v0.12.9）。
  本机 400 个 rollout 实测：`codex` ×27160（真实值 7~9% 已用）、`codex_bengalfox`
  （`limit_name = "GPT-5.3-Codex-Spark"`，模型专属）×9635 且 **100% 都是 0%/0%**、`premium`（`primary` 为 null，本就跳过）。
  `_find_rl` 旧判据只有「`primary` 是个带 `used_percent` 的 dict」、**递归找到第一个就返回**，
  于是一套恒 0% 的模型额度会被当成账号额度 ⇒ UI 显示 **100% 剩余**，直到官方 usage API 读回来才恢复。
  - ★ **触发时机是「最新会话记录」被换掉**（新建/恢复/暂停/归档任务都会换）——所以症状是**毫无征兆地跳**，不是随用量渐变。
  - ⚠️ **不能按窗口形状分辨**：`codex_bengalfox` 有 2752 次带的是 `10080` 周窗口，与 Pro 账号真实窗口同形。
  - **白名单不是黑名单**：认 `codex`；完全没有 `limit_id` 的（老协议）照旧接受；**只有不认识的 ID 时返回 `None` 不猜** ——
    下次 Codex 再加一套模型额度默认被挡在外面。同时支持新协议 `rateLimitsByLimitId`（以 ID 为键的字典）。
  闸在 `tests/test_rate_limit_identity.py`。
- ★★ **额度数字绝不可以被编造：没读到就是没读到，不是「满额」**（2026-08-28，v0.12.9/v0.12.10）。
  这是「读不到 ≠ 确实没有」在额度上的形态，**咬过至少两次**（另一次见 CHANGELOG 里 07:00 快照那条）。
  - **判据**：`resets_at` 过了**不等于**已确认重置。快照 `captured_at` **晚于** `resets_at` ⇒ 读数属于新窗口，采信；
    快照更旧 ⇒ **未知**。三处独立实现必须同步：`helpers.ts::winRem` · `lib.rs` 托盘 · `proxy.py::_win_used`。
  - **未知的语义**：显示层该窗口不参与 `tightest`（走已有的 `—`）；**选号器分层排序** ——
    有读数的一律排在未知之前。★ 旧代码把「没有读数」当 0% 已用，于是**额度未知的号被排成最空闲、优先抢走流量**。
  - ★ **限流/错误响应不是完整清单**：`_record_quota` 只在 **2xx** 时整体替换（2xx 与 usage-api 才有权删窗口）；
    非 2xx 不替换。**默认值站安全侧**（`status=None` ⇒ 不替换），调用点漏传由 AST 闸盯着。
  - ⚠️ **不要改成「proxy 永不删、逐窗口保留」**：`captured_at` 挂在 quota **对象**上，保留的窗口会蹭到兄弟窗刚刷新的
    时间戳，反而让上面那条判据**把幽灵窗认证成真实读数**，永远画绿色 100%。闸在 `tests/test_quota_never_fabricated.py`。
- ★★ **锚点账本 `traffic/quota_anchors.py`（2026-09-06）—— 把「reset 是真的还是跟着 now 滑」从推断换成观测。**
  起因是读 `cclank/tokei` 时发现对方用**时间序列**解同一个问题，而我们上一轮只做了单样本点估计。
  - **点估计有天花板，不是精度问题**：一个**刚刚**首次使用的真窗口，它的 `resets_at − captured_at` 也恰好等于整窗
    ⇒ 单样本永远分不出「闲置浮动」和「刚锚定」，只能说「待确认」，而且**永远确认不了**。判别信息在序列里：
    浮动的 reset 每轮跟着 `now` 挪，锚定的一动不动。
  - **三态**：`anchored`（reset 静止 ≥15min）/ `floating`（连续 ≥2 个锚点跟着时间挪）/ `unknown`（样本不够）。
    ★ `unknown` **必须回落到点估计**，绝不当成 `floating` —— 那是拿「还没看够」冒充「确定没启动」。
    「未启动」这四个字**只能由 `floating` 开口**（闸逐处核它前面 400 字符内有没有那个守卫）。
  - ★★ **合并锚点时绝不更新 `row["reset"]`。** 采样最快 20s 一次（`MIN_GAP_SECS`）而容差 60s，
    跟着改的话浮动窗口**永不分裂**、`held_secs` 一路涨到超过阈值 ⇒ **闲置窗口被认证成锚点已确认**，
    正好是这本账存在理由的反面，且看上去完全正常。守门员测试
    `test_quota_anchors.py::test_floating_window_polled_faster_than_jitter_is_never_anchored`。
  - **只在 `/usage` 这条路径记**（`_probe_quota` 里）。六个写 `slot["quota"]` 的地方只有它是服务端权威读数；
    rollout tail / proxy 是本地回声、`captured_at` 语义不同，混进来会把时间轴搅脏。
  - **判定是 `slot["quota_anchor"]` 兄弟键，且自带它描述的那个 `reset`**（同 `codex_headers` 的理由，更硬）：
    `quota` 会被整体替换而兄弟键不跟着换，不核身份就会拿旧窗口的判定解释新窗口，两者渲染出来一模一样。
  - grok / agy 各自在采集脚本里记（`_note_anchors`），**口径转换在调用方做**：grok 给已用、agy 给剩余，
    让公共函数猜方向就是把一个能静默算反的判断藏进没有上下文的地方。**agy 是收益最大的一家** ——
    它的闲置桶此前直接渲染那个永远停在 4h5xm 的假倒计时，一个标记都没有。
  - ⚠️ **三个脚本的 `_quota_anchors_mod()` 整体 fail-open，它会把接线错误一起吞掉。**
    第一版 `agy-quota` 用了 `Path` 而那文件从没 import 过 `pathlib` —— 语法检查过、脚本照跑、输出照常，
    账本**静默地从不工作**。所以闸 `tests/test_quota_anchor_wiring.py` 判的是「真的把模块加载出来」，
    不是「源码里有那几个字」。
  - ⚠️ **托盘那份至今没接账本**（只有点估计）。不是漏改：托盘不画倒计时，「钟准不准」对它没有渲染后果。
    哪天托盘要画倒计时了再接，在那之前别"顺手对齐"。
  - ★★ **事故:测试把夹具数据写进了真实账本(当天发现当天修)。** `test_grok_degrade_contract.py`
    拿夹具 auth 起 `grok-quota`,而账本写入没有隔离口 ⇒ 三个假账号(`https://auth.x.ai::c1/c2/client-1`,
    used 恒 35%)进了真实的 `.quota-anchors.json`,**而那些假锚点会直接参与 UI 的「未启动」判定**。
    当时 **9 个**测试文件在起这三个脚本,一个都没隔离 store。
    - **修法不是逐个去补**(那是"写下来但没有闸"),是加一个**只影响账本落点**的隔离口
      `CODEXBAR_QUOTA_ANCHORS`(优先级高于 `CODEX_ROTATE_STORE`)。不动 `CODEX_ROTATE_STORE`
      是因为它连带决定 `STORE`/`AUTH_DIR`/`STATE` 且在 import 时求值,爆炸半径太大。
    - ★ **隔离要设两处**:`tests/test_isolation_bootstrap.py`(模块顶层,管
      `unittest discover -s tests` —— 那条路**不导入** `tests/__init__.py`)+ `tests/__init__.py`
      (管 `python -m unittest tests.test_x`,CI 里就有一条)。两半各摘一次都会变红。
    - ★ 判据写成「隔离变量必须已设置」而不是「代码里有隔离逻辑」——我第一版只写在
      `__init__.py` 里,正是这条断言当场判红才发现 discover 根本不导入它。
  - ⚠️ **harness 的 `?agy=ok` 走不到「未启动」分支**——卡与菜单栏行只取每个窗口**最紧**的桶，
    而 100% 的桶按定义永远不是最紧的。验那条分支要用 **`?agy=idle`**（四桶全满）或
    `CODEXBAR_FLOATING_ANCHOR=1`（codex 侧）。★ 我推理说"覆盖到了"，`--dump-dom` 当场证伪。
- ★ **quotad 的到点判断一律走 `_due()`，不是裸的 `now - last >= T`**（2026-09-06）。
  墙钟回拨（NTP / 改时间 / 快照恢复）会让差值变负，朴素写法把下一次执行**推迟整整一个回拨的量**，
  而这件事**没有任何症状** —— 日志里只是安静地少了几行，额度停在旧值，看着和「这段时间没人用 codex」一样。
  ⚠️ **不要"顺手"换成 `time.monotonic()`**：macOS 的 monotonic 不含睡眠时间（`CLOCK_UPTIME_RAW`），
  合盖三小时唤醒后它几乎没动 ⇒ 还要再等一个完整周期才刷新，而那正是全池数据最旧、最该立刻刷的时刻。
- ★ **全池扫描有第二个触发口：窗口跨过重置时刻立刻扫**（`_reset_crossed`，2026-09-06）。
  重置那一刻旧读数语义作废、UI 如实显示"未知"，而固定节拍下那段未知最长挂 300s。
  ★★ 判据必须是「**快照拍摄于重置之前**」而不只是「重置时刻已过」：后者在服务端迟迟不更新 `resets_at` 时
  **恒为真**，把兜底节拍变成每 60s 一扫，在 /usage 的 bot challenge 面前就是自找 403。
  这样写还**自我清零**（扫完 `captured_at > resets_at`，条件自动失效），不需要额外记「已触发过」。
- ★★ **`cxp` 对所有*运行时*子命令一律 `--profile rotateproxy`，没有例外分支（2026-09-07 恢复原始设计，B36/B37）。**
  - ⚠️ **「运行时」这个限定词是 2026-09-08 加的，不是措辞收敛。** codex **0.154.0-alpha.6** 起，
    对非运行时子命令带 `--profile` 从「静默忽略」改成**硬报错**：
    `Error: --profile only applies to runtime commands and \`codex mcp\`: \`codex\`, \`codex exec\`,
    \`codex review\`, \`codex resume\`, \`codex queue\`, \`codex archive\`, \`codex delete\`,
    \`codex unarchive\`, \`codex fork\`, \`codex mcp\`, \`codex sandbox\`, and \`codex debug prompt-input\`。
    而 `alias codex=cxp` 当时给**每个**子命令都塞 profile ⇒ `doctor`/`update`/`plugin`/`features`/
    `completion`/`apply`/`agents` 全部一句话就死，运行时那半完全正常。
    症状因此是「**会话能开、工具全废**」，极易误判成本仓的 resume 改动弄坏了什么。
  - **实现必须是黑名单不是白名单**：白名单会把裸 prompt（`codex 修一下这个 bug`，首个非选项 token
    是 `修一下这个 bug`）判成「未知子命令」而丢掉 profile ⇒ **静默退回单号直连、不轮换**。
    这个方向的失败不出声，比报错危险得多。闸：`tests/test_cxp_profile_scope.py`。
  - ⚠️ **别用 `codex <sub> --help` 探这个** —— clap 在 `--help` 上短路，profile 校验根本没跑到，
    26 个子命令会**全绿**。我第一轮就是这么扫出「全部 ok」的，与事实相反。必须发真实调用。
  - ✅ 附带堵上一个空守卫：profile 曾恒占 `$1`，而 PATH wrapper 的拦截写的是 `[ "$1" = "logout" ]` ——
    那条「`logout` 会在服务端 revoke 当前号」的守卫**一直没生效**。去掉 profile 后才真命中。
  - **「不走代理」= 「WS 必开」= 「单号烧到停」**，这三者是同一件事，别当成三个独立问题：
    codex 的 `codex_api::endpoint::responses_websocket` **硬编码 `wss://chatgpt.com/backend-api/codex/responses`、不认 `base_url`**（实测近 3 天 124 次 WS 连接 124 次直连公网、0 次到 8011）；
    关它的开关是 provider 的 `supports_websockets`（`client.rs::responses_websocket_enabled()`），
    而**内置 provider 把它硬编码成 `true` 且不可覆盖** —— `merge_configured_model_providers` 对非 Bedrock 的 key 用 `entry(key).or_insert()`，内置 id 配了也被忽略。
    所以唯一能关掉 WS 的办法就是**走一个用户定义的 provider**，也就是走代理。
  - ⚠️ **别再试「新建一个 provider 当默认、只关 WS 不走代理」** —— 试过，`codex resume` **直接空了**（B37）。
    picker 按 provider **逐字**过滤（`ProviderMatcher::matches`，filters = `[当前默认 provider]`），
    而存量会话没有一个带新戳记。**换 id 就等于清空列表。**
  - **已知代价（定稿，2026-09-08，别再提统一方案）**：picker 只列 `rotateproxy` 戳记的会话。
    `openai` 戳记的**没有消失**，`codex resume <id>` **跨 provider 照样能进**（已实测）。
    ★★ **两条入口的分裂是用户主动选择的终态**，理由是**「需要单号入口跑 `/usage` 看重置卡」** ——
    走代理时每个请求可能落在不同号上，那个数就没意义了：

    | 入口 | provider | 行为 | picker 里能看到 |
    |---|---|---|---|
    | `codex`（alias→cxp） | `rotateproxy` | 逐请求轮换、WS 关 | 新会话（今起累积） |
    | `\codex` / `cx` | `openai`（内置） | 单号直连，`/usage` 有意义 | 238 条存量档案 |

    **技术上能统一**（profile 与 provider 解耦，两个 profile 可指向同一个 `model_provider`；
    `env_http_headers` 在 0.154 二进制里确实存在，可让「单号入口」也走代理但按 header 钉号）——
    **用户否了**，因为那样 `/usage` 那条路就不再是真正的直连。
  - ★★ **「让 cxp 的 picker 同时列出两个 provider」= 不可能（无补丁）**，别再花时间试：
    - 真渲染实测（`scratch/picker_render_probe.py`，2026-09-08）：cxp `1 / 5`；官方 `1 / 25`→`1 / 75` 仍在加载。
      picker 顶栏筛选器只有 `Cwd / Status / Sort`，**没有 provider 这一维**。
    - SQL 是 ` AND threads.model_provider IN (`；二进制里所有含 `provider` 的键都列过一遍，
      唯一沾边的 `allow_provider_model_fallback` 是选模型不是选列表。
    - `--all` 只解 cwd；0.154 新增的 `--include-non-interactive` 只解 `has_user_event`。**都不碰 provider**。
    - 0.154 仍拒绝把代理 provider 命名为 `openai`：`model_providers contains reserved built-in provider IDs:`。
    - ⚠️ **探针陷阱**：pty 不设窗口大小（`TIOCSWINSZ`）时 TUI 什么都不画，**和「列表真的是空的」长得一模一样**。
      我第一次就得到了「两边都 0 条」的假结论。
  - ⚠️ **纠正一条本文档自己写错并被反复引用的数据**：这里原本写着「最近 50 个里 rotateproxy 占 76%、
    最近 500 个占 64%、往后只增不减」。**2026-09-08 实测推翻** —— picker 口径
    （`archived=0` + `has_user_event=1` + `source in cli/vscode`）是 **openai 238 : rotateproxy 2**，
    2026-08 及以前**每月都是 0**。大概率是 wrapper 里那个已删的 `repair_codex_session_visibility()`
    一直在把 DB 的 rotateproxy 改写成 openai（238 这个数基本就是它的产物）；另一部分是 69 条
    VS Code 会话，那条路根本不经过 cxp。**两者分不干净，别当已知事实用。**
    可确认的只有：repair 移除后新交互会话稳稳戳 rotateproxy（当天 14:22/14:30 两条已验），
    所以 238 是**存量、不再增长**。
    ★ 这条错误本身是「结论要带证据和日期」那条规矩的最好例证 —— 它带了日期，所以三个月后被查出来了。
  - ★★ **`cxp` 里那段「resume 例外」的注释曾把我误导整整一轮。** 它是 `8753a28`（2026-06-13）的权衡，
    注释里带着当时的实测数据（89 个 openai 会话 vs 1 个 rotateproxy）—— 数据早过期，结论早该翻。
    **看到解释性注释先 `git log -S '<那段代码>' -- <file>` 查它是什么时候、基于什么数据写的**，
    这正是本文开头「代码 > 带实测数据的 CHANGELOG 结论 > 本文」那条优先级的用法。
  - ★★ **中转站（第三方 OpenAI 协议 relay）是账号池的第二条路由**（2026-09-09 落地，B41）。
    机制与详细不变量在 `relay/store.py` 与 `relay/monitor.py` 的 docstring 里，这里只留三条必须先知道的：
    ① ~~每个中转站一份 `~/.codex/<id>.config.toml`~~ —— **2026-09-09 起不再生成**
       （「一个 provider，两种上游」定稿，`write_profile` 已删）。托管区标记的规矩仍然有效，
       但只对**清理遗留文件**这一件事：`store.drop_managed_profile()` 只剥
       `MARK_BEGIN`/`MARK_END` 之间那段，**用户写在前后的内容一个字节都不动**
       （2026-09-10 修：原来两处各写一份判据，命中标记就 `unlink()` 整份）。
       codex 确实会往 overlay 回写（本机 12 行 hooks 信任哈希 / 项目信任 / NUX 计数器），
       所以整文件覆盖会静默毁掉 oh-my-codex 的 hooks 与项目信任。
    ② **profile 文件缺失/漂移 codex 都不报错**，直接退回 base 配置 = 直连单号、不轮换、WS 全开。
       闸有三道且**必须都在**：`cxp` 的 exec 前硬检查（exit 78）、`health` 的 `relay_route_gate()`
       六态、CodexBar 路由卡。三道挡的是**不同时刻**，不是重复。
    ③ **两个成本口径永不合并**：中转站的 `cost` 是牌价、`actual_cost` 是真实扣款（实测差 3.85 倍），
       而「AI用量」页的是按 OpenAI 牌价折算的**等效**成本 —— 三个数放一起不标注就是骗人。
       经中转站的 token **绝不许用 `rates.ts` 乘**；`scan.py` 的 `by_provider` 只做归属不做计价。
    ④ **`/usage` 的粒度：有「每天 × 每模型」，没有小时。**（2026-09-09 实测，两条都别再自己试一遍）
       · `?start_date=D&end_date=D` **是认的** —— `model_stats` 跟着窗口走，逐日查一次就拿到
         每天每模型，与当天 `total_tokens` **逐 token 相等**（8/8 天核对；唯一不等的是今天，
         两次 HTTP 之间用量还在涨）。⚠️ 我曾只看默认响应就断言"没有这个交叉"并否掉整张图。
       · **没有小时粒度** —— `period`/`granularity`/`group_by`/`hourly`/`interval`/`unit`/`type`/
         `default_time` 共 10 种参数形式全部原样返回按天数据，响应里也没有任何 hour 字段。
         所以「今日」档只有一个点，页面上必须**说出为什么**，否则用户会以为是我们没做。
    ⑤ **key 的两个面都要守**（2026-09-10）：**传输面** —— `urllib` 跟随重定向时原样带上
       `Authorization`，`monitor._get` 因此走自建 `_OPENER`，跨源**直接拒绝**（不是"跟过去但删
       header"：那样拿到的响应与「key 失效」长得一模一样）；远端明文 http 一律拒发，只放行
       https 或**回环**。**静止面** —— `_atomic_write` 用 `os.open(O_CREAT|O_EXCL, 0600)`，
       文件从未有过更宽的权限；`fingerprint()` 不出明文尾巴（哈希已能区分同前缀的两把，
       多给 3 个明文字符只是喂给离线暴力）。
    ★ 实测单次成本 **$0.0863**（tokens used 39,513，系统提示+工具定义就这么大）。
      切到中转站 = 每次 `codex` 都在扣余额,所以那个按钮是全 app **第二个花钱控件**（第一个是 ProbeButton）。
  - ★★★ **禁止：给 codex 打补丁二进制（`native-codex/`）。定稿弃案，2026-09-08，Do Not Revisit。**
    曾把本地编译的 `0.153.4+codexbar.1` 放到 `<store>/native-codex/codex`、让 `cxp` 探到就改走它，
    目的是让原生 picker 同时查两个 provider。**用户拍板废除**（「不要弄补丁的，改为官方版」，
    理由是它挡后续官方版更新）。三条独立理由，任何一条单独成立就足够：
    ① ★ **它当场炸掉了全部工具调用。** codex 按**自己可执行文件的同级目录**解析辅助进程，
       而 `scripts/native-resume/build.py` 只 `shutil.copy2` 了 `codex` 一个文件 —— 官方 vendor 是 4 件套
       （`codex` / `codex-code-mode-host` / `codex-resources/` / `codex-path/`）。`code_mode_host` 是
       stable/true，spawn 不到 ⇒ `codex_core::tools::router` **fail closed** ⇒ 模型一个工具都调不动。
       ⚠️ **而它没有任何「配置坏了」的迹象**：`codex doctor` 全绿、`config.toml parse ok`、auth ok、
          MCP 8 个都在 —— 所以人必然先去翻配置，而配置是干净的，白查一轮。
          **唯一拿到真因的办法是真跑一次 `codex exec`** 看 stderr。
       ★ 附带判据教训：**`codex features list` 的第三列是默认值不是有效值**
         （`--disable X` 之后仍显示 `true`），拿它推断有效配置会得出相反结论。
    ② **它把版本钉死**：补丁对 0.153.4，npm 当天已到 0.154.0-alpha.6；`codex update` 更新 npm 那份、
       跑的却是被钉住的补丁，**无声**越差越远。
    ③ 每次官方发版都要重 apply + 重编 + 重验，成本没人会长期付。
    现状：`cxp` **只有一条 `exec command codex`**。闸 `tests/test_resume_routing.py::NoPatchedBinaryEntry`
    （唯一 exec + 无 `native-codex`/`CODEX_NATIVE_BIN`/wrapper 转发残留 + 仓库里不许有该二进制）。
    `scripts/native-resume/` 仅作存档。二进制归档在
    `~/archive/codex-account-rotator/native-codex-dropped-20260908/`。
    ⚠️ `CODEX_ROTATE_STORE` **不属于补丁残留** —— 它是全仓统一的数据目录变量（`codex-rotate`/`traffic/*` 都读）。
       我拆补丁时顺手删过一次，那是把公共设施当成残留；闸里现在**断言它必须在**。
  - `codex-rotate switch --best` 保留为**手动**入口（按最紧窗口判、只看 Plus），但 `cxp` 不再自动调用 ——
    走代理之后「开场挑一个号」没必要，代理每个请求都在挑。闸在 `tests/test_resume_routing.py`。
- ★ **验证配置生效必须用有判别力的对照**（2026-09-07 连栽两次）：
  - codex 对**未知配置键静默忽略** —— 塞一个虚构键它也不报错，所以「没报错」证明不了键被识别。
    有判别力的对照是**写一个不存在的 provider id**：那会报 `Model provider ... not found`。
  - **WS 只在交互式会话里发生**（331 条记录 / 69 个进程，30 个有 TUI 日志；`codex exec` 一条都没有）。
    拿 `exec` 验「WS 还发不发生」时实验组与对照组**都是 0**，两边都没判别力 —— 那种测试等于没做。
- ★ **续期只剩代理这一条路**（keepalive 定时器 2026-08-29 按用户要求取消）。`_slot_token` 只续**它挑得中**的非活跃号，
  所以**长期不被挑中的号 token 到期后不会自愈**；而上面那条「未知排最后」会加重它（过期→读不到→排最后→更不被挑中）。
  症状无声：额度扫描每 300s 失败一次，而 `tick_usage` 把 `cmd_refresh_all` 的每账号结果吞进 `StringIO`。
  ★ **`access 已过期` ≠ 掉登录**：先只读 `health`，再 `codex-rotate refresh <label>`（非活跃号安全），**回 `ok` 即证明没掉登录**。
- 重置卡的**张数与到期分属两次取数**（张数随 usage 探测免费带回，到期只在限流的明细端点）。`cards>0 && cardDays==null` 是合法状态，显示"到期未知"而不是假装没有；`cardsExpiring` 必须 `min(…, cards)` 钳位。
- 每个新号必须**独立无痕窗**登授权 URL，否则同浏览器会话链里两个号反复互顶（"signed in to another account"）。
- ★ **代理回给 codex 的状态码决定它重发几次**。实测（假上游顶掉真代理，数 `POST /responses`）：`502 → 30 次` · `409 → 6 次` · `429 → 1 次` · `400 → 1 次`。计费请求要「中止而不重发」时**必须**用 **400**——用 5xx 会被 codex 带退避猛重试，而每次重试在代理里都重新挑号，等于把「两个号各计一次」放大成「N 个号轮着计费」，比不修更糟。**别靠记忆猜哪个码可重试，起个假上游数一次。**
- ★ **计费相位分界 = `conn.request()` vs `conn.getresponse()`**。`sendall` 抛异常 ⟺ 仍有尾段未写入 ⟹ Content-Length 下 body 不完整 ⟹ 上游永不 dispatch ⟹ 不计费。所以 `request()` 失败可**证明**未计费、换号安全；只有 `getresponse()` 失败才是「已交内核、到没到不可知」。判「会不会烧钱」用**黑名单**（`command not in ("GET","HEAD")`）而非白名单——白名单漏掉新计费端点会让双计费静默复活，且计数器对它零感知。
- 禁在 cxp 重度使用时手动 `codex-rotate refresh all`（跨进程刷新竞争窗口仍在）。
- ★★★ **agy 账号池（`agy/pool.py` + `agy-rotate`，2026-09-13）—— 登录态在 macOS 钥匙串里，不在文件里。**
  机制与实测记录写在 `agy/pool.py` 的模块 docstring 与 `KEYRING_SVC` 注释里（正本），这里只留必须先知道的：
  - **主存储 = 钥匙串 `svce=gemini` / `acct=antigravity`**；`~/.gemini/antigravity-cli/antigravity-oauth-token`
    只是**钥匙串写失败时的兜底**（agy 日志：`composite_token_storage.go:237] Failed to save token to
    keyring, falling back to file`）。读序跟 agy 的 `ChainedAuth` 一致：钥匙串优先（实测 13/13 `effective: keyring`）。
    ⚠️ **我们最初把兜底当成了主路径**，于是 `agy-rotate switch` 是**静默空操作** —— 写成功、退出码 0、
    打印「已切到」，而 agy 根本不读那份。判别实验：文件放 A、钥匙串留 B，跑 `agy models` 看
    `applyAuthResult: email=`。**验换号一律用这个，别看我们自己的输出。**
  - ★★ **写钥匙串只能走 argv。** `security -w` 从 stdin 读时**静默截断到 128 字节**（`readpassphrase`
    缓冲区），而凭证约 2.2 KB —— 退出码 0、读回来还带正确前缀，只有 agy 说「你没登录」。
    所以 `keyring_write()` **写完必须读回来逐字比**。代价是密文在那一次调用里对 `ps` 可见；
    agy 自己用的 go-keyring 也是 argv，没有扩大暴露面。
  - ★★★ **测试必须设 `AGY_KEYRING=0`**（两处 bootstrap 都设了，闸在 `test_isolation_bootstrap.py`）。
    钥匙串**没有临时目录这种东西**，换 `AGY_TOKEN_FILE` 挡不住它 —— 一条用例就能覆盖用户的真登录态，
    代价是重走一遍浏览器 OAuth。与 2026-09-06「夹具写进真账本」同族，只是账本换成了系统钥匙串。
  - **刷新不轮换 `refresh_token`**（响应里没有该字段）⇒ 刷我们这份**不会**作废 agy 那份。
    ⚠️ 与 grok 的铁律**正好相反**（grok 单次有效、绝不刷），两家照搬任何一边都会出事。
  - ★★★ 额度走 `POST cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary`，
    **零消耗、每账号、含周窗口**（2026-09-15 起）。返回 `groups[].buckets[]`，
    与本机 RPC（`agy-quota`）**同形同源**，前端 `AgySnapshot` 直接吃。
    ⚠️ **这条推翻了本文此前的一个结论**：旧文写着「额度只有 5h；周窗口只有本机 RPC 有、
    且只看得到当值号」，并据此做过 `weekly_seen` 与「非当值号」文案。
    **那是假阴性** —— 它建立在 `fetchAvailableModels` 只回 5h 这**一个**观测上，
    而从没找过第二个端点；端点就摆在 agy 二进制的 `strings` 里，与本地 RPC 方法名并排。
    实测两个号都 200（`gemini-weekly` 98.78% / 97.33%）。**这是 §6「只看默认响应就断言
    接口没这能力 = 假阴性」的又一次实证，用户追问两次才逼出搜索。**
  - `fetchAvailableModels` **仍在用**，但只用于 `health`（刷 token + 打一次，验凭证还活着）。
    ★ 组名**不再靠猜**：新端点自带 `displayName` / `bucketId`，旧那套「按 `(remainingFraction,
    resetTime)` 分桶 + 成员最多的那组是 gemini」的启发式已删除，闸在
    `tests/test_agy_pool.py::TheQuotaComesFromTheSummaryEndpoint`。
  - **绝不补一个假的格**：上游 `remainingFraction` 缺省恰好是 1.0，
    这条链路上「没有」和「满格」只隔一个默认值。失败一律 `(None, 说明)`，200 但无 `groups` 也当失败。
  - ★★★ **钥匙串是被多个常驻 agy 进程并发写的单槽**（2026-09-13 实测，三方评审一致）。
    本机常有 5 个跑了好几天的 agy 进程；它们**各自在自己 access token 到期时把自己的身份
    整份写回钥匙串**。实测 17:58 装进 B、18:23:17 被一个身份为 A 的旧进程冲掉。
    ⇒ **「当前账号」不是我们能维持的状态，只是一个随时被冲刷的观测值。**
    · UI 的「当前」徽章必须走 `agy-rotate live`（**现读钥匙串**），`live_seen` 只是诊断字段；
    · `auto` **先兑现 `live_wanted`（用户显式选的号）再谈额度够不够** ——
      否则 A 抢回槽之后「当前号还够用」那条 early-return 会**静默撤销用户的 switch**；
    · 要让切换真的生效：退掉那些旧身份的 agy 进程，再开一个新的。
  - ★★★ **探针绝不能自己拼 HTTP**：直接打 `v1internal:streamGenerateContent` 恒
    **429 RESOURCE_EXHAUSTED**，即使额度满格、模型 id 取自该号自己的 `fetchAvailableModels`、
    还带上了 `loadCodeAssist` 回的 `aicode-consumers`。**那个 429 长得和「额度用光了」一模一样** ——
    用它做探针会把"我们拼错了"报成"你的号没额度了"。所以 `agy-rotate probe` 起的是
    **agy 真身**（`agy -p … --output-format json`），顺带拿到精确到 token 的用量
    （实测一次 15,195 token / 约 30s）。判据同 codex：**模型真吐出字**，不是退出码 0。
    非当值号先切过去再探，**还原放在 `finally`**。
  - `agy-rotate health` 是**零消耗**的那一半：刷一次 access_token + 打一次 `fetchAvailableModels`，
    两步都过才算能用。`invalid_grant`（掉登录）与网络抖动**必须分开**报。
  - **自动切号开关存在池里**：全局 `auto_off` + 按号 `rotate_off`，两个都**存反向**
    （缺省 = 参与轮换；正向命名要写迁移，漏迁移的号会静默退出轮换池），恢复时**删键**不写 `False`。
    ⚠️ 我曾判断"这条做不了"并说给用户听过 —— **错的**：wrapper 调的是 `agy-rotate auto`，而它读池。
    ★ 闸盯的是「`cmd_auto` 真的读了这两个键」——只存不读就是「界面说关着、wrapper 照切」。
  - ★★ **周额度的归属要有证据**：`agy-quota` 打的是「**第一个应答的 pid**」，而多个常驻进程
    身份不同 ⇒ 那份读数属于**那个进程**。实测 A 号卡上的「周 98.9%」来自一个身份其实是 B 号的 pid。现在它记 `pid_email`（取自 agy 日志的 `applyAuthResult:`），
    **对不上就不挂卡**。★ `ps -o lstart=` 的日期顺序跟 **locale** 走（本机日在前），
    只写一种格式会让归属**静默恒空**。
  - ★★ **GUI 跑 agy 命令必须喂 `AGY_POOL_STORE`**（`spawn_cmd`）：`agy/pool.py` 按 `__file__`
    推数据目录，打进 app 后是 `Contents/Resources/scripts/`（空池）⇒ 点「切换」跑的是空池，
    命令成功、退出码 0、什么也没发生。同族：`agy_quota_sampler.py` 的账本基准必须与
    `scan.py` 同一个（都走 `CODEX_ROTATE_STORE`）。闸 `tests/test_bundled_scripts_get_their_store.py`。
  - ★★★ **测试默认 `AGY_KEYRING=0`**（`tests/__init__.py` + `tests/test_isolation_bootstrap.py` 两处）。
    钥匙串**没有临时目录这种东西**，重定向 `AGY_TOKEN_FILE` 对它完全无效 ——
    一条用例调到 `install_live()` 就能覆盖用户真实的 agy 登录态，代价是重走一遍浏览器 OAuth。
