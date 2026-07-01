// shared helpers — data transforms & formatters

export interface Win { used_percent?: number; resets_at?: number }
export interface Quota { primary?: Win; secondary?: Win; captured_at?: number; source?: string }
export interface Slot {
  label?: string; email?: string; quota?: Quota; auth_dead?: boolean;
  cooling_until?: number; sub_until?: string; file?: string;
}
export interface AppState {
  slots?: Record<string, Slot>; active?: string; last_proxy_ts?: number;
}
export interface TokenInfo { exp?: number }

export interface Account {
  aid: string;
  node: string;
  email: string;
  status: "live" | "low" | "cool" | "dead";
  h5: number;
  h5reset: string;
  h5resetAt: string;  // absolute time "HH:MM" or "已重置"
  wk: number;
  wkReset: string;
  exp: string;
  cooldownSec: number;
  tok: string;
}

export const now = () => Date.now() / 1000;
export const clamp = (n: number) => Math.max(0, Math.min(100, Math.round(n)));

export function winRem(w?: Win, _cap = 0): number | null {
  if (!w || w.used_percent == null) return null;
  if (w.resets_at && w.resets_at <= now()) return 100;
  return 100 - w.used_percent;
}

export function fmtEta(ts?: number): string {
  if (!ts) return "—";
  const d = Math.floor(ts - now());
  if (d <= 0) return "已重置";
  const h = Math.floor(d / 3600), m = Math.floor((d % 3600) / 60);
  return h >= 24 ? `${Math.floor(h / 24)}d${h % 24}h` : `${h}h${String(m).padStart(2, "0")}m`;
}

export function fmtCd(sec: number): string {
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
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

export function slotToAccount(aid: string, slot: Slot, tokens: Record<string, TokenInfo>): Account {
  const q = slot.quota; const cap = q?.captured_at ?? 0;
  const h5 = winRem(q?.primary, cap) ?? 0;
  const wk = winRem(q?.secondary, cap) ?? 0;
  const n = now();
  const coolSec = (slot.cooling_until ?? 0) > n ? Math.max(0, (slot.cooling_until ?? 0) - n) : 0;

  let status: Account["status"] = "live";
  if (slot.auth_dead) status = "dead";
  else if (coolSec > 0) status = "cool";
  else if (h5 <= 20) status = "low";

  const tokExp = tokens[aid]?.exp;
  const tokH = tokExp ? Math.floor((tokExp - n) / 3600) : null;

  return {
    aid, node: slot.label ?? "?", email: slot.email ?? "",
    status, h5: clamp(h5), wk: clamp(wk),
    h5reset: fmtEta(q?.primary?.resets_at),
    h5resetAt: fmtResetTime(q?.primary?.resets_at),
    wkReset: fmtEta(q?.secondary?.resets_at),
    exp: slot.sub_until?.slice(0, 10) ?? "—",
    cooldownSec: Math.round(coolSec),
    tok: tokH != null ? `${tokH}h` : "—",
  };
}

export function recommended(accounts: Account[]): Account | null {
  const avail = accounts.filter(a => a.status === "live" || a.status === "low");
  return avail.sort((x, y) => y.h5 - x.h5)[0] ?? null;
}
