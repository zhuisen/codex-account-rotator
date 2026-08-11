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

export function winRem(w?: Win): number | null {
  if (!w || w.used_percent == null) return null;
  if (w.resets_at && w.resets_at <= now()) return 100;
  return 100 - w.used_percent;
}

// Codex retired the 5h window (2026-07). A real quota window is now weekly (10080)
// or monthly (43200); anything shorter is a deprecated/phantom slot (e.g. the empty
// {window_minutes: 0, resets_at: null} Codex still returns) and must not be shown.
const REAL_WINDOW_MIN = 5000;

function winLabel(w?: Win): string {
  const mins = w?.window_minutes ?? 0;
  if (mins >= 40000) return "月";
  return "周";
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

/** When the pool was last read FROM THE SERVER. Deliberately derived from the snapshots rather than
 *  stored separately: a rollout-derived snapshot is a local echo, not a pool refresh, so counting it
 *  would report the pool as fresher than it is. */
export function poolRefreshedAt(slots: Record<string, Slot>): number | undefined {
  let newest: number | undefined;
  for (const sl of Object.values(slots)) {
    const q = sl.quota;
    if (!q?.captured_at || (q.source !== "usage-api" && q.source !== "probe")) continue;
    if (newest == null || q.captured_at > newest) newest = q.captured_at;
  }
  return newest;
}

function buildWindow(w: Win | undefined): QuotaWindow | null {
  // Drop deprecated/phantom windows (old 5h = 300, empty slot = 0/undefined).
  if (!w || (w.window_minutes ?? 0) < REAL_WINDOW_MIN) return null;
  const pctRaw = winRem(w);
  if (pctRaw == null) return null;
  return {
    label: winLabel(w),
    pct: clamp(pctRaw),
    reset: fmtEta(w.resets_at),
    resetAt: fmtResetTime(w.resets_at),
  };
}

export function slotToAccount(aid: string, slot: Slot, tokens: Record<string, TokenInfo>): Account {
  const q = slot.quota;
  const n = now();
  const coolSec = (slot.cooling_until ?? 0) > n ? Math.max(0, (slot.cooling_until ?? 0) - n) : 0;

  const windows: QuotaWindow[] = [];
  const w1 = buildWindow(q?.primary);
  if (w1) windows.push(w1);
  const w2 = buildWindow(q?.secondary);
  if (w2) windows.push(w2);

  const tightest = windows.length > 0 ? Math.min(...windows.map(w => w.pct)) : -1;

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
    status, windows, tightest, deadAt: slot.auth_dead_at,
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
