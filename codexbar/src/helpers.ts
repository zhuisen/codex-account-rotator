import type { Theme } from "./theme";
// shared helpers — data transforms & formatters

export interface Win { used_percent?: number; resets_at?: number; window_minutes?: number }
export interface Quota { primary?: Win; secondary?: Win; captured_at?: number; source?: string; plan_type?: string }
/** One reset credit ("重置卡") as returned by /backend-api/codex/rate-limit-reset-credits. */
export interface CreditDetail {
  id?: string; status?: string; granted_at?: string; expires_at?: string; title?: string;
}
export interface Slot {
  label?: string; email?: string; quota?: Quota; auth_dead?: boolean; auth_dead_at?: number;
  cooling_until?: number; sub_until?: string; file?: string; plan?: string;
  /**
   * OpenAI **上次向计费系统复核订阅**的时刻（id_token 的 `chatgpt_subscription_last_checked`）。
   * 签发新 token 时它不重新查，只把上次复核的快照抄进新 JWT —— 所以续费后无论刷多少次，
   * `sub_until` 都停在复核那天。有了它才能区分「真的过期」和「快照太旧」。
   */
  sub_checked?: string;
  /** Free summary, refreshed on every usage probe. */
  credits?: { available?: number; applicable?: number; at?: number };
  /** Rate-limited detail fetch — the only source of per-credit expiry. */
  credits_detail?: { credits?: CreditDetail[]; available?: number; fetched_at?: number };
}
export interface AppState {
  slots?: Record<string, Slot>; active?: string; last_proxy_ts?: number;
}
export interface TokenInfo { exp?: number }

export interface QuotaWindow {
  label: string;
  /** 窗口时长（分钟）。★ 供 `winColor()` 按**时长档**取色 —— 不用 label 字符串，
   *  那是 `winLabel()` 现算的展示文本，上游多一个窗口就会全落进兜底。 */
  mins: number;
  pct: number;
  reset: string;
  resetAt: string;
}

export interface Account {
  aid: string;
  node: string;
  email: string;
  status: "live" | "low" | "cool" | "dead";
  windows: QuotaWindow[];
  tightest: number;
  /** `tightest` 这个数**出自哪个窗口**（整个对象，不只是 label）。
   *  ★★ 规则：**单个汇总数字一律取「最紧」的窗口** —— hero 环、卡片环、菜单栏行、托盘标题
   *  全部用它；只有"有空间列清单"的地方（卡片下方的细条）才把 `windows` 全画出来。
   *  拿 `windows[0]` 会在两个窗口时显示**较宽松**的那个，把真正的约束藏起来
   *  （5h 回归后这是常态，而 5h 缺席的那一年里根本不可能暴露）。 */
  tightestWin: QuotaWindow | null;
  exp: string;
  /** 这个到期日已不可信(已过期,但 OpenAI 上次复核订阅还早于它) —— 见 `expStale` 的计算处 */
  expStale: boolean;
  cooldownSec: number;
  tok: string;
  /** Unix seconds of the death event; a CHANGED value means a new death (not the same one). */
  deadAt?: number;
  /** 套餐(plus/pro/…),来自 id_token,**权威**。label 只是昵称:老号从 Plus 升 Pro 时 label 不变,
   *  所以任何"这是不是 Pro"的判断都必须看这里,不能看 node 名以 pro 开头。 */
  plan: string;
  /** 这份额度快照的年龄（秒）；`null` = 没有 `captured_at`（未知，不是 0）。 */
  quotaAgeSec: number | null;
  /** 快照是否已陈旧（> `QUOTA_STALE_SEC`）。★ 陈旧**不等于**额度是错的，
   *  它只说「这个数是多久以前读到的」—— 卡片如实标注，不上红、不参与选号否决。 */
  quotaStale: boolean;
  /** Reset credits held. Count comes free with every usage probe. */
  cards: number;
  /** Days until the soonest still-available credit expires — needs the detail fetch, so it stays
   *  undefined when only the count is known. `cards>0 && cardDays==null` = "N 张, 到期未知". */
  cardDays?: number;
  /** Expiry date of that soonest credit, YYYY-MM-DD. */
  cardExp?: string;
  /** How many of `cards` lapse within CARD_WARN_DAYS. Distinct from `cards` on purpose: holding 2
   *  cards where only 1 is about to lapse is the normal case, and collapsing the two numbers would
   *  claim the whole stack is expiring. */
  cardsExpiring: number;
}

/** ≤ this many days left ⇒ amber + pulse (design handoff §4). */
export const CARD_WARN_DAYS = 3;

export const now = () => Date.now() / 1000;
export const clamp = (n: number) => Math.max(0, Math.min(100, Math.round(n)));

/**
 * 这个窗口的**剩余**百分比，或 `null` = **没有可信的读数**。
 *
 * ★★ 旧版是「`resets_at` 一过就 `return 100`」—— 那是**编造**：重置时刻到了
 * **不等于**已确认重置为满额，而画出来的 100% 与实测的 100% 长得一模一样，用户无从分辨。
 * 这与本仓库的头号铁律「读不到 ≠ 确实没有」是同一件事，只是换了个面孔。
 * （2026-08-28 三方评审 codex/grok 共同指出；托盘 `lib.rs` 有独立的第二份实现，必须同步。）
 *
 * ★ 过了重置点分两种，别一律作废：
 *   · 快照 `capturedAt` **晚于** `resets_at` ⇒ 这份读数本来就是重置之后拍的，
 *     `used_percent` 属于新窗口，**照常采信**（服务端回了个已过期的 resets_at，读数却是新的）；
 *   · 快照更旧 ⇒ 重置了但**还没有任何新读数** ⇒ 返回 `null`。
 *
 * 返回 `null` 时 `buildWindow` 会把整个窗口丢掉，于是它不参与 `tightest`；
 * 全都没了就走**已有的**「—／未探测」路径 —— 不新增一种"假装知道"的渲染。
 */
export function winRem(w?: Win, capturedAt?: number): number | null {
  if (!w || w.used_percent == null) return null;
  if (w.resets_at && w.resets_at <= now()) {
    if (capturedAt != null && capturedAt > w.resets_at) return 100 - w.used_percent;
    return null;
  }
  return 100 - w.used_percent;
}

/**
 * 一个额度窗口是不是**真的**。
 *
 * ★★ 2026-08-25 改判据（Plus 的 5 小时窗口回来了，实测 `primary.window_minutes = 300`）。
 *
 * 这里要挡的东西**从来没变过**：Codex 仍会返回**空槽** `{window_minutes: 0, resets_at: null}`。
 * 变的是判据 —— 2026-07 那会儿真窗口只剩周/月，所以「够大(≥5000)」**恰好等价于**「非空」，
 * 于是当时用了这个代理判据。5h 回归之后那个等价关系断了：`300 < 5000`，
 * **一个合法窗口会被当垃圾丢掉**，用户看不到自己的 5 小时额度。
 *
 * 所以现在直接判「有没有值」，不再判「够不够大」。用量级去猜语义，量级一变就失效。
 * ⚠️ 同一份判据还有**两个副本**：`codex-rotate` 的 `_win_real`、`lib.rs` 托盘那段。
 *    跨语言没法共用，**改这里必须同时改那两处**（闸在 `tests/test_quota_windows.py`）。
 */
const REAL_WINDOW_MIN = 1;

/** 窗口名按**实际时长**算，不写死那几个已知值 —— 上游加一个新窗口时不至于全标成「周」。 */
function winLabel(w?: Win): string {
  const mins = w?.window_minutes ?? 0;
  if (mins >= 40000) return "月";
  if (mins >= 10000) return "周";
  if (mins >= 1440) return `${Math.round(mins / 1440)}天`;
  return `${Math.round(mins / 60)}h`;
}

export function fmtEta(ts?: number): string {
  if (!ts) return "—";
  const d = Math.floor(ts - now());
  if (d <= 0) return "已重置";
  const h = Math.floor(d / 3600), m = Math.floor((d % 3600) / 60);
  return h >= 24 ? `${Math.floor(h / 24)}d${h % 24}h` : `${h}h${String(m).padStart(2, "0")}m`;
}

export function fmtCd(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.round(sec % 60);
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}m`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtResetTime(ts?: number): string {
  if (!ts) return "";
  const n = now();
  if (ts <= n) return "已重置";
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

/**
 * 额度**窗口**的识别色（用户 2026-08-26 从四版 demo 里选的 C：「两行 + 双色相，5h 青 / 周 绿」）。
 *
 * ★★ **这是一个知情的取舍，不是疏漏 —— 改之前先读完。**
 * 它把条与环的颜色从「额度水位」改成了「哪个窗口」，代价是**低额度不再靠条色报警**：
 * 剩 41% 和剩 95% 的周，条都是同一个绿。用户在 demo 里看过这两个数的实际渲染后仍选了 C。
 *
 * 仅剩的两个报警口，**别再顺手删**：
 *   ① 百分数仍按阈值变色（<50% 琥珀）—— 用户指定的是「曲线颜色」，数字不在其中；
 *   ② 环外 `glow` 在低额度时点亮（不改环的描边色）。
 *
 * ★ 单一真源：菜单栏行与总览卡若都要用，必须都调这里。两边各写一份迟早分叉
 *   （本项目已经在 grok 那边栽过一次：同一状态两个 surface 两种画法）。
 * ★ 按**时长档**取色，不是按 label 字符串 —— label 是 `winLabel()` 现算的，
 *   上游哪天多一个窗口，这里不至于全落进兜底。
 */
export function winColor(w: { mins?: number } | null | undefined, t: Theme): string {
  const m = w?.mins ?? 0;
  if (m > 0 && m < 1440) return t.accent;   // 5h 这一档：品牌青
  return "#27B26B";                          // 周 / 月：绿
}

/**
 * 条与环最终用的颜色 —— **窗口识别色 + 低额度夺色**（用户 2026-08-26 定稿的 C′）。
 *
 * ★★ 两个诉求本来是打架的，这条规则是它们的和解：
 *   · 「5h 和周的颜色不一样」→ 平时按**窗口**取色（青 / 绿）；
 *   · 「低额度靠条色报警」  → **跌破阈值时警告色夺回条色**，识别色让位。
 * 换句话说：**识别是常态，报警是例外，而例外优先**。额度快没了的时候，
 * 「这是哪个窗口」远不如「这个要没了」重要 —— 而后者正是这个 app 存在的理由。
 *
 * 阈值与 `quotaColor()` 保持同一套（<50% 琥珀），另加 ≤10% 红：
 * 那是 `quotaColor` 没有、但托盘的 `rem_rgb` 有的一档，这里对齐到更严的那个。
 *
 * ★ **单一真源**：菜单栏行与总览卡都调这里。两边各写一份迟早分叉 ——
 *   本项目已经在 grok 那边栽过一次（同一状态两个 surface 两种画法，靠截图才发现）。
 */
/** 额度水位分档。**只有这一处判据** —— 见 `winNumColor` 的说明。 */
export type QuotaLevel = "danger" | "warn" | "ok";
export function quotaLevel(pct: number): QuotaLevel {
  if (pct <= 10) return "danger";
  if (pct < 50) return "warn";
  return "ok";
}

export function winBarColor(
  w: { mins?: number } | null | undefined,
  pct: number,
  t: Theme,
): string {
  const lv = quotaLevel(pct);
  if (lv === "danger") return "#E0524D";   // 危险：红
  if (lv === "warn") return "#E0901C";     // 警告：琥珀
  return winColor(w, t);                   // 正常：窗口识别色
}

/**
 * 百分比**数字**的颜色（用户 2026-08-26 定稿：**策略③ 正常中性、告警夺色**）。
 *
 * 与 `winBarColor` **共用 `quotaLevel` 这一个判据**，只是正常态不上色：
 *   · 危险/警告 → 与条同色（红 / 琥珀），条和数字必然一致；
 *   · 正常     → 中性次级灰，**不跟着染窗口识别色** —— 一屏三张卡就是六个数字，
 *                正常态全上色的话满屏彩色，真正的报警反而不显眼。
 *
 * ★★ 为什么必须抽出来：改动前**三个 surface 各写一份**，而且写的还不一样 ——
 *    账号卡与菜单栏行是 `<50 琥珀` 两档（**没有红档**），grok 卡是三档。
 *    结果剩 7% 时：条是红的、账号卡的数字却是琥珀，**同一个状态两种说法**。
 *    这正是本仓库反复栽的那一类（grok 那次也是同一状态两个 surface 两种画法，靠截图才发现）。
 *    闸在 `tests/test_quota_windows.py::WindowColourRule`。
 *
 * ★ 环外的 `glow`（≤20 亮起）是**有意的第三条更窄的带**，不是漏改：它表达"快没了，看这里"，
 *   比 `warn` 更紧；跟着 `<50` 亮的话几乎天天亮，等于没有。
 */
export function winNumColor(pct: number, t: Theme): string {
  const lv = quotaLevel(pct);
  if (lv === "danger") return "#E0524D";
  if (lv === "warn") return "#E0901C";
  return t.text2;
}

export function ringDash(pct: number, r: number): string {
  const C = 2 * Math.PI * r;
  return `${(clamp(pct) / 100 * C).toFixed(1)} ${C.toFixed(1)}`;
}

/** Ring / bar / percent colour. The handoff (§5.1.5) states the rule as a single threshold —
 *  remaining `<50%` is amber, otherwise green — so it is deliberately coarser than a per-severity
 *  ramp. Keep both surfaces on this one function so they can never drift apart. */
export function quotaColor(pct: number): string {
  return pct < 50 ? "#E0901C" : "#27B26B";
}

/**
 * 打码模式下的身份文本。保留前 3 个字符:够你自己认出是哪个号,又不足以让别人还原。
 * 1 个字符试过,用户反馈认不出来(huo/553/dou/xsh/qq5 这五个前缀刚好两两可分)。
 * 定宽输出,所以开关打码时整列不会跳动。
 *
 * `keep` 按「前缀之后还剩几个可区分字符」来给:邮箱直接 3;`account_id` 全都以 `user-` 开头,
 * 保 3 个只会得到五个一样的 `use`,所以调用处传 8。
 */
export function maskId(s: string | undefined, on: boolean, keep = 3): string {
  if (!on) return s ?? "";
  if (!s) return "—";
  return s.slice(0, keep) + "•".repeat(11);
}

/** "14:32 · 3 分钟前". Empty when never refreshed. */
export function fmtAgo(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const mins = Math.floor((now() - ts) / 60);
  if (mins < 1) return `${hhmm} · 刚刚`;
  if (mins < 60) return `${hhmm} · ${mins} 分钟前`;
  const h = Math.floor(mins / 60);
  return h < 24 ? `${hhmm} · ${h} 小时前` : `${hhmm} · ${Math.floor(h / 24)} 天前`;
}

/**
 * 额度快照多旧才算**陈旧**。
 *
 * ★★ **锚定采集心跳，不锚定窗口长度**（三方评审一致）。曾考虑按窗口比例算
 * （「周窗口陈旧 1 小时无所谓」），但那个前提是错的：周额度也可能几小时烧光，
 * 而一个 token 已失效 10 小时的号会因为「相对周窗口不算久」被判新鲜，
 * 调度器继续往黑洞里打请求。**窗口长度决定的是预算周期，不是观测有效期。**
 *
 * quotad 的全池扫描周期是 300s。取 **6 个周期 = 30 分钟**：够宽，不会被一两次
 * 网络抖动或单次扫描失败触发；又远短于「一个号已经死了好几天」那种真问题。
 *
 * ⚠️ **已知边界（agy 提出）**：Mac 合盖休眠数小时后唤醒的那一瞬间，全池 age 会同时突增，
 * 于是所有号一起标陈旧。这**不是误报** —— 那一刻的数据确实全是旧的；quotad 会在一个
 * 扫描周期内补齐。所以这里刻意**不上红色**、不参与选号否决，只做一个可悬浮的事实陈述，
 * 避免把「一次正常的唤醒」训练成用户忽略所有告警的理由。
 */
export const QUOTA_STALE_SEC = 30 * 60;

/** 秒数 → 「N 分钟 / N 小时 / N 天」。★ 与 `fmtAgo` 分工:那个吃时间戳,这个吃**已经算好的年龄**
 *  —— 让调用方各自再减一次 `now()`,就等于把「现在是几点」这个知识复制出去好几份。 */
export function fmtAgeSec(sec: number): string {
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))} 分钟`;
  if (sec < 86400) return `${Math.round(sec / 3600)} 小时`;
  return `${Math.round(sec / 86400)} 天`;
}

/** 这份额度快照的年龄（秒）。没有 `captured_at` ⇒ `null`（未知，不是 0）。 */
export function quotaAgeSec(slot: Slot, atNow = now()): number | null {
  const cap = slot.quota?.captured_at;
  return cap == null ? null : Math.max(0, atNow - cap);
}

/**
 * 池级新鲜度。★★ **不返回单个 max/min** —— 三方一致指出那是个假两难：
 *   · `max`（现状）被每 300s 刷新的活号盖成「刚刚」，**主动藏住**一个陈旧 3.8 天的号；
 *   · `min` 又会被一个弃用号永久拉垮，天天谎报全池故障。
 * 两者都证明不了「上次全池刷新成功」。所以给**覆盖度**：几个新鲜、几个陈旧、最旧多旧。
 */
export function poolFreshness(slots: Record<string, Slot>, atNow = now()):
  { fresh: number; stale: number; unknown: number; oldestAgeSec: number | null } {
  let fresh = 0, stale = 0, unknown = 0, oldest: number | null = null;
  for (const sl of Object.values(slots)) {
    const age = quotaAgeSec(sl, atNow);
    if (age == null) { unknown++; continue; }
    if (age > QUOTA_STALE_SEC) stale++; else fresh++;
    if (oldest == null || age > oldest) oldest = age;
  }
  return { fresh, stale, unknown, oldestAgeSec: oldest };
}

/** When the pool was last read FROM THE SERVER. Deliberately derived from the snapshots rather than
 *  stored separately: a rollout-derived snapshot is a local echo, not a pool refresh, so counting it
 *  would report the pool as fresher than it is.
 *  ⚠️ 它只回答「**最近有账号被刷新过**」，**不能**读成「全池都是新的」——
 *  那个问题要用 `poolFreshness()`。 */
export function poolRefreshedAt(slots: Record<string, Slot>): number | undefined {
  let newest: number | undefined;
  for (const sl of Object.values(slots)) {
    const q = sl.quota;
    if (!q?.captured_at || (q.source !== "usage-api" && q.source !== "probe")) continue;
    if (newest == null || q.captured_at > newest) newest = q.captured_at;
  }
  return newest;
}

/**
 * `resets_at` 是不是**浮动占位值**（窗口还没被使用过，服务端每次都回「此刻 + 整窗」）。
 *
 * ★★ 实测（2026-09-05，5h 窗口 = 300 分钟）：
 *
 *     plus4  used=0%    resets_at − captured_at = 17999.5s   整窗 18000s   差 −0.5s
 *     plus6  used=0%    resets_at − captured_at = 17999.4s   整窗 18000s   差 −0.6s
 *     plus3  used=55%   resets_at − captured_at =  3588s     整窗 18000s   差 −14411s
 *     plus5  used=100%  resets_at − captured_at =  2943s     整窗 18000s   差 −15057s
 *
 * 用过的号有真实锚点；**没用过的号每轮轮询都把 `resets_at` 往前滑一整个轮询周期**。
 * 于是倒计时永远停在 ~4h55m —— 用户报的「5h 没有继续计时」就是这个。
 * （同族现象：Antigravity 的额度接口也是闲置桶的 resetTime 跟着 now 滑动，用过才锚定。）
 *
 * ★★ **必须拿 `capturedAt` 比，不能拿 `now()`**（这条是决定性的）：
 * 闲置轮询周期正好 300s，真钟会从 5h00 走到 4h55 再被下一轮占位写回去。用 `now()` 做判据，
 * 会在两次写入之间误判成「已启动」，轮询一到又跳回「未启动」—— 每 5 分钟闪一次。
 *
 * ★ 阈值 90s：观测到的滑动误差 < 1s，而最短的真实锚点（plus3）也差了 14411s，
 * 两者相隔三个数量级，阈值取在哪都不敏感；90s 只是给 RPC 往返和时钟抖动留余量。
 */
const FLOATING_RESET_TOL_SEC = 90;

export function resetAnchorUnknown(w?: Win, capturedAt?: number): boolean {
  const wm = w?.window_minutes, ra = w?.resets_at;
  if (!wm || !ra || !capturedAt) return false;
  return Math.abs((ra - capturedAt) - wm * 60) < FLOATING_RESET_TOL_SEC;
}

function buildWindow(w: Win | undefined, capturedAt?: number): QuotaWindow | null {
  // 只丢**空槽**(window_minutes 为 0/缺失)。5h(300) 是合法窗口,别再按量级丢。
  if (!w || (w.window_minutes ?? 0) < REAL_WINDOW_MIN) return null;
  // ★ `capturedAt` 挂在 quota 对象上、不在窗口里,必须显式传进来 ——
  //   少传这一个参数,判据就退化回"过期即 100%"而且**不会报错**。
  const pctRaw = winRem(w, capturedAt);
  if (pctRaw == null) return null;
  // ★★ 锚点不可信时**只把倒计时换掉**，条和百分比照画。
  //    · 窗口**不能**从 `windows` 里丢掉 —— 丢了 Plus 的 5h 行会整行消失，卡片看起来像 Pro，
  //      而槽位对齐是按行数走的（那套对齐规则刚在 v1.1.0 修过一次）。
  //    · 水位本身是可信的：油箱确实是满的，**假的是钟不是水位**。所以 pct 不动，
  //      选号器也不动 —— 0% 排最前正是负载均衡要的。
  //    · 文案用「待确认」而不是「未启动」：刚首次使用、用量被取整成 0% 的**真**窗口
  //      也会命中这个判据，此时断言「未启动」就是在编一个我们证不了的事实。
  const anchorUnknown = resetAnchorUnknown(w, capturedAt);
  return {
    label: winLabel(w),
    mins: w.window_minutes ?? 0,
    pct: clamp(pctRaw),
    reset: anchorUnknown ? "待确认" : fmtEta(w.resets_at),
    resetAt: anchorUnknown ? "重置时间待确认" : fmtResetTime(w.resets_at),
  };
}

export function slotToAccount(aid: string, slot: Slot, tokens: Record<string, TokenInfo>): Account {
  const q = slot.quota;
  const n = now();
  const coolSec = (slot.cooling_until ?? 0) > n ? Math.max(0, (slot.cooling_until ?? 0) - n) : 0;

  const windows: QuotaWindow[] = [];
  const w1 = buildWindow(q?.primary, q?.captured_at);
  if (w1) windows.push(w1);
  const w2 = buildWindow(q?.secondary, q?.captured_at);
  if (w2) windows.push(w2);

  // ★★ 不只算最小值,还要记住**是哪一个窗口** —— hero 环的数字取 `tightest`,标签却取
  //    `windows[0].label`。只有一个窗口时两者永远一致,**5h 回归后就有两个窗口了**,
  //    数字可能来自周、标签却写着 5h。这是"恢复 5h"这件事本身引入的缺陷,不是老 bug。
  const tightestWin = windows.length > 0
    ? windows.reduce((a, b) => (b.pct < a.pct ? b : a))
    : null;
  const tightest = tightestWin ? tightestWin.pct : -1;

  let status: Account["status"] = "live";
  if (slot.auth_dead) status = "dead";
  else if (coolSec > 0) status = "cool";
  else if (tightest >= 0 && tightest <= 20) status = "low";

  const tokExp = tokens[aid]?.exp;
  const tokH = tokExp ? Math.floor((tokExp - n) / 3600) : null;

  // Card COUNT comes from the free summary; EXPIRY only exists in the rate-limited detail fetch, so
  // the two are read independently — an account can legitimately know it holds 2 cards while having
  // no dates yet. Only `status === "available"` counts: a redeemed card is still in the list.
  const plan = (slot.quota?.plan_type || slot.plan || "").toLowerCase();

  const qAge = quotaAgeSec(slot, n);
  const cards = slot.credits?.available ?? 0;
  let cardDays: number | undefined;
  let cardExp: string | undefined;
  let cardsExpiring = 0;
  for (const c of slot.credits_detail?.credits ?? []) {
    if (c.status !== "available" || !c.expires_at) continue;
    const ts = Date.parse(c.expires_at) / 1000;
    if (!Number.isFinite(ts) || ts <= n) continue;
    const days = (ts - n) / 86400;
    if (days <= CARD_WARN_DAYS) cardsExpiring++;
    if (cardDays == null || days < cardDays) { cardDays = days; cardExp = c.expires_at.slice(0, 10); }
  }

  return {
    aid, node: slot.label ?? "?", email: slot.email ?? "",
    status, windows, tightest, tightestWin, deadAt: slot.auth_dead_at,
    exp: slot.sub_until?.slice(0, 10) ?? "—",
    /**
     * 这个到期日**是否已经不可信**。判据:到期日已过 **且** OpenAI 上次复核订阅早于该到期日 ——
     * 那说明这个「已过期」是拿一份复核时就已陈旧的快照下的结论,续费根本不在它的视野里。
     *
     * 用户 2026-08-11 报「续费成功但有效期没更新」。实测:两个号 force 刷出全新 id_token,
     * `last_checked` 仍是 07-30,`sub_until` 纹丝不动 —— 拉新 token 拉不到新订阅状态。
     * 此时 app 的健康检查说这号是活的,到期日却说已过期,**两个信号互相矛盾**。
     * 按仓库既有原则(重置卡 `cards>0 && cardDays==null` 显示「到期未知」而不是假装没有),
     * 这里也只标不确定,不改写日期本身。
     */
    expStale: (() => {
      if (!slot.sub_until) return false;
      const until = Date.parse(slot.sub_until);
      const checked = slot.sub_checked ? Date.parse(slot.sub_checked) : NaN;
      if (!Number.isFinite(until) || until > Date.now()) return false;   // 没过期,无需怀疑
      if (!Number.isFinite(checked)) return true;   // 连复核时间都没有 ⇒ 无从判断新鲜度
      return checked < until;
    })(),
    cooldownSec: Math.round(coolSec),
    tok: tokH != null ? `${tokH}h` : "—",
    plan,
    // ★ 快照年龄如实带出来。`null` = 没有 `captured_at`（未知，**不是 0**）——
    //   0 会被读成「刚刚读到的」，正好把最坏的情况显示成最好的。
    quotaAgeSec: qAge,
    quotaStale: qAge != null && qAge > QUOTA_STALE_SEC,
    cards, cardDays, cardExp,
    // The two numbers come from different fetches at different times: the count is refreshed on every
    // usage probe, the detail only when `credits` runs. So the cached detail can legitimately still
    // list a card the server has already dropped, which would render "×1 · 2张…". Clamp — never claim
    // more cards are expiring than are held. (`credits` self-heals the cache on the next run, because
    // a changed count is exactly what marks the detail stale.)
    cardsExpiring: Math.min(cardsExpiring, cards),
  };
}

export function recommended(accounts: Account[]): Account | null {
  const avail = accounts.filter(a => a.status === "live" || a.status === "low");
  return avail.sort((x, y) => y.tightest - x.tightest || x.node.localeCompare(y.node))[0] ?? null;
}

/**
 * 是否用 **Windows 版窗口控制**（右上 ─ □ ✕），而不是 macOS 的左上红黄绿。
 *
 * ★ 窗口控制按钮的**位置属于「必须各平台原生」**那一类（OS 级肌肉记忆 + 无障碍）——
 *   与"可以统一品牌"的标题栏配色不同，这个不能一刀切。用户 2026-08-31 实测 Windows 版
 *   顶着一排 macOS 红绿灯，报「要右上角缩小放大删除」。
 *
 * ★ 判据走 `navigator.userAgent` 而**不是新加一个 Tauri 命令**：harness 打桩的是 IPC，
 *   每加一个命令就要同步补一个桩，而漏补的症状是**整页零渲染** —— 那正好量出来是
 *   「零溢出、零报错」，是个假阴性（本仓库 2026-08-11 连中两次）。
 *
 * `?os=windows|macos` 可强制，供 harness 在 macOS 上渲染 Windows 版式做像素核对。
 */
export function isWindowsUI(): boolean {
  try {
    const forced = new URLSearchParams(location.search).get("os");
    if (forced) return forced === "windows";
    return /Windows NT/i.test(navigator.userAgent);
  } catch {
    return false;   // 判定不了就按 macOS ——本机就是 macOS，保持既有行为
  }
}
