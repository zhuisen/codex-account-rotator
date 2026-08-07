// shared helpers — data transforms & formatters

export interface Win { used_percent?: number; resets_at?: number; window_minutes?: number }
export interface Quota { primary?: Win; secondary?: Win; captured_at?: number; source?: string }
/** One reset credit ("重置卡") as returned by /backend-api/codex/rate-limit-reset-credits. */
export interface CreditDetail {
  id?: string; status?: string; granted_at?: string; expires_at?: string; title?: string;
}
export interface Slot {
  label?: string; email?: string; quota?: Quota; auth_dead?: boolean; auth_dead_at?: number;
  cooling_until?: number; sub_until?: string; file?: string;
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
  cooldownSec: number;
  tok: string;
  /** Unix seconds of the death event; a CHANGED value means a new death (not the same one). */
  deadAt?: number;
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
 * 打码模式下的身份文本。保留首字符是刻意的:你自己还能认出是哪个号,别人认不出。
 * 定宽输出,所以开关打码时整列不会跳动。
 */
export function maskId(s: string | undefined, on: boolean, keep = 1): string {
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
    cooldownSec: Math.round(coolSec),
    tok: tokH != null ? `${tokH}h` : "—",
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
