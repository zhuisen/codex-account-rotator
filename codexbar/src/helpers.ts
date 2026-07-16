// shared helpers — data transforms & formatters

export interface Win { used_percent?: number; resets_at?: number; window_minutes?: number }
export interface Quota { primary?: Win; secondary?: Win; captured_at?: number; source?: string }
export interface Slot {
  label?: string; email?: string; quota?: Quota; auth_dead?: boolean;
  cooling_until?: number; sub_until?: string; file?: string;
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
}

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

  return {
    aid, node: slot.label ?? "?", email: slot.email ?? "",
    status, windows, tightest,
    exp: slot.sub_until?.slice(0, 10) ?? "—",
    cooldownSec: Math.round(coolSec),
    tok: tokH != null ? `${tokH}h` : "—",
  };
}

export function recommended(accounts: Account[]): Account | null {
  const avail = accounts.filter(a => a.status === "live" || a.status === "low");
  return avail.sort((x, y) => y.tightest - x.tightest || x.node.localeCompare(y.node))[0] ?? null;
}
