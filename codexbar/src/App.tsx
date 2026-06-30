import { useEffect, useState, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

// ---- types ----
interface Win { used_percent?: number; resets_at?: number }
interface Quota { primary?: Win; secondary?: Win; captured_at?: number; source?: string }
interface Slot { label?: string; email?: string; quota?: Quota; auth_dead?: boolean; cooling_until?: number; sub_until?: string; file?: string }
interface AppState { slots?: Record<string, Slot>; active?: string; last_proxy_ts?: number }
interface TokenInfo { exp?: number }

// ---- helpers ----
const now = () => Date.now() / 1000;
const clamp = (n: number) => Math.max(0, Math.min(100, Math.round(n)));
const winRem = (w?: Win, cap = 0): number | null => {
  if (!w || w.used_percent == null) return null;
  if (w.resets_at && w.resets_at <= now() && cap > 0 && cap < w.resets_at) return 100;
  return 100 - w.used_percent;
};
const fmtEta = (ts?: number) => {
  if (!ts) return "—";
  const d = Math.floor(ts - now());
  if (d <= 0) return "已重置";
  const h = Math.floor(d / 3600), m = Math.floor((d % 3600) / 60);
  return h >= 24 ? `${Math.floor(h/24)}d${h%24}h` : `${h}h${String(m).padStart(2,"0")}m`;
};
const ringDash = (pct: number, r: number) => {
  const C = 2 * Math.PI * r;
  return `${(pct / 100 * C).toFixed(1)} ${C.toFixed(1)}`;
};
const statusColor = (s: string) => s === "dead" ? "#E0524D" : s === "cool" ? "#2BA0C0" : s === "low" ? "#E0901C" : "#27B26B";
const statusText = (s: string) => s === "dead" ? "死" : s === "cool" ? "冷却" : s === "low" ? "低" : "活";
const fmtCd = (sec: number) => `${Math.floor(sec/60)}:${String(Math.round(sec%60)).padStart(2,"0")}`;
const getStatus = (slot: Slot): string => {
  if (slot.auth_dead) return "dead";
  if ((slot.cooling_until ?? 0) > now()) return "cool";
  const q = slot.quota; const cap = q?.captured_at ?? 0;
  const p = winRem(q?.primary, cap);
  if (p != null && p <= 20) return "low";
  return "live";
};

// ---- theme ----
const THEMES = {
  dark: {
    appBg:"#0e1117", chromeBg:"#0c1015", chromeBorder:"rgba(255,255,255,.07)", titleText:"#cfd6df",
    railBg:"#0a0e12", railBorder:"rgba(255,255,255,.06)",
    text:"#eef2f7", text2:"#aab3c0", muted:"#6b7480", email:"#8b95a1", faint:"#454d57",
    heroBg:"#131c20", heroBorder:"rgba(45,212,191,.25)",
    cardBg:"#141a22", cardBorder:"rgba(255,255,255,.06)", curCardBg:"rgba(45,212,191,.07)",
    accent:"#2dd4bf", accentText:"#06231f", accentTextSoft:"#9fe9df", accentSoft:"rgba(45,212,191,.10)", accentBorder:"rgba(45,212,191,.34)",
    ringTrack:"rgba(255,255,255,.09)", barTrack:"rgba(255,255,255,.09)",
    ghostBorder:"rgba(255,255,255,.12)", ghostText:"#aab3c0", ghostBg:"rgba(255,255,255,.02)",
    toastBg:"rgba(20,26,34,.94)", toastText:"#eef2f7", toastBorder:"rgba(45,212,191,.3)",
    divider:"rgba(255,255,255,.08)",
    sunBg:"transparent", sunColor:"#6b7480", moonBg:"#2dd4bf", moonColor:"#06231f",
  },
  light: {
    appBg:"#eef1f5", chromeBg:"#f7f9fb", chromeBorder:"rgba(0,0,0,.1)", titleText:"#39414b",
    railBg:"#e7ebf0", railBorder:"rgba(0,0,0,.06)",
    text:"#161b22", text2:"#4d5663", muted:"#8a93a0", email:"#6b7682", faint:"#aab2bd",
    heroBg:"#ffffff", heroBorder:"rgba(14,159,142,.3)",
    cardBg:"#ffffff", cardBorder:"rgba(0,0,0,.07)", curCardBg:"rgba(14,159,142,.05)",
    accent:"#0e9f8e", accentText:"#ffffff", accentTextSoft:"#0c8576", accentSoft:"rgba(14,159,142,.09)", accentBorder:"rgba(14,159,142,.4)",
    ringTrack:"rgba(0,0,0,.09)", barTrack:"rgba(0,0,0,.08)",
    ghostBorder:"rgba(0,0,0,.12)", ghostText:"#4d5663", ghostBg:"#ffffff",
    toastBg:"rgba(255,255,255,.97)", toastText:"#161b22", toastBorder:"rgba(14,159,142,.35)",
    divider:"rgba(0,0,0,.1)",
    sunBg:"#0e9f8e", sunColor:"#ffffff", moonBg:"transparent", moonColor:"#8a93a0",
  },
};
type Theme = typeof THEMES.dark;

// ---- Ring component ----
function Ring({ pct, r, sw, color, track, children, size }: { pct: number; r: number; sw: number; color: string; track: string; children?: React.ReactNode; size: number }) {
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={track} strokeWidth={sw} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" transform={`rotate(-90 ${size/2} ${size/2})`}
          stroke={color} strokeWidth={sw} strokeLinecap="round"
          strokeDasharray={ringDash(clamp(pct), r)}
          style={{ transition: "stroke-dasharray .6s cubic-bezier(.4,0,.2,1), stroke .35s ease" }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        {children}
      </div>
    </div>
  );
}

// ---- Ghost button ----
function GhostBtn({ t, onClick, children, accent }: { t: Theme; onClick: () => void; children: React.ReactNode; accent?: boolean }) {
  const [hover, setHover] = useState(false);
  return (
    <span onClick={onClick} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 11px",
        border: `1px solid ${accent ? t.accentBorder : (hover ? t.accentBorder : t.ghostBorder)}`,
        borderRadius: 8, fontSize: 11, color: accent ? t.accentTextSoft : t.ghostText,
        background: accent ? t.accentSoft : t.ghostBg, cursor: "pointer", userSelect: "none",
        filter: hover && accent ? "brightness(1.12)" : undefined,
        transition: "border-color .2s, filter .15s" }}>
      {children}
    </span>
  );
}

// ---- Account card ----
function AccountCard({ aid, slot, isCurrent, isBest, status, t, onSelect }: {
  aid: string; slot: Slot; isCurrent: boolean; isBest: boolean; status: string; t: Theme; onSelect: () => void;
}) {
  const [hover, setHover] = useState(false);
  const q = slot.quota; const cap = q?.captured_at ?? 0;
  const h5 = winRem(q?.primary, cap); const wk = winRem(q?.secondary, cap);
  const isDead = status === "dead"; const isCool = status === "cool";
  const sc = statusColor(status);
  const cdSec = isCool ? Math.max(0, (slot.cooling_until ?? 0) - now()) : 0;

  return (
    <div onClick={onSelect} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ background: isCurrent ? t.curCardBg : t.cardBg,
        border: `1px solid ${isCurrent ? t.accent : t.cardBorder}`,
        borderRadius: 12, padding: 12, display: "flex", gap: 11, alignItems: "center",
        cursor: "pointer", userSelect: "none",
        transform: hover ? "translateY(-2px)" : undefined,
        boxShadow: hover ? "0 10px 26px rgba(0,0,0,.4)" : undefined,
        transition: "background .3s, border-color .3s, transform .15s, box-shadow .15s" }}>

      <Ring pct={isDead ? 0 : (h5 ?? 0)} r={21} sw={5} color={sc} track={t.ringTrack} size={52}>
        <span style={{ fontSize: 13, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums" }}>
          {isDead ? "—" : clamp(h5 ?? 0)}
        </span>
      </Ring>

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{slot.label ?? "?"}</span>
          <span style={{ fontSize: 9.5, fontWeight: 600, color: sc }}>{statusText(status)}</span>
          {isBest && <span style={{ fontSize: 8, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 5px", borderRadius: 4 }}>USE</span>}
          {isCurrent && <span style={{ marginLeft: "auto", fontSize: 8.5, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, padding: "1px 6px", borderRadius: 999 }}>当前</span>}
        </div>
        <div style={{ fontSize: 10.5, color: t.email, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{slot.email}</div>

        {!isDead && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'" }}>周</span>
              <div style={{ flex: 1, height: 4, borderRadius: 2, background: t.barTrack, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${clamp(wk ?? 0)}%`, background: sc, borderRadius: 2, transition: "width .55s cubic-bezier(.4,0,.2,1), background-color .35s ease" }} />
              </div>
              <span style={{ fontSize: 10, color: t.text2, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{clamp(wk ?? 0)}%</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
              {isCool ? <span style={{ color: "#2BA0C0", fontWeight: 600 }}>❄ 冷却 {fmtCd(cdSec)}</span> : <span>↻ {fmtEta(q?.primary?.resets_at)}</span>}
              <span>到期 {slot.sub_until?.slice(0, 10) ?? "—"}</span>
            </div>
          </>
        )}

        {isDead && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginTop: 1 }}>
            <span style={{ fontSize: 9.5, color: "#E0524D", fontWeight: 600 }}>token 失效 · 已到期</span>
            <span style={{ fontSize: 10, fontWeight: 700, color: t.accentText, background: t.accent, padding: "3px 10px", borderRadius: 6, cursor: "pointer", flexShrink: 0 }}>复活</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ---- Main App ----
export default function App() {
  const [state, setState] = useState<AppState>({});
  const [tokens, setTokens] = useState<Record<string, TokenInfo>>({});
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [spinning, setSpinning] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const toastRef = useRef<ReturnType<typeof setTimeout>>();

  const t = THEMES[theme];

  const showToast = useCallback((msg: string) => {
    if (toastRef.current) clearTimeout(toastRef.current);
    setToast(msg);
    toastRef.current = setTimeout(() => setToast(null), 2100);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [s, tk] = await Promise.all([invoke<AppState>("read_state"), invoke<Record<string, TokenInfo>>("read_auth_tokens")]);
      setState(s); setTokens(tk);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { refresh(); const id = setInterval(refresh, 10_000); return () => clearInterval(id); }, [refresh]);

  const run = async (args: string[], msg: string) => {
    try { await invoke("run_rotate", { args }); } catch (e) { console.error(e); }
    await refresh();
    showToast(msg);
  };

  const slots = state.slots ?? {};
  const active = state.active;
  const ordered = Object.entries(slots).sort((a, b) => {
    const sa = getStatus(a[1]), sb = getStatus(b[1]);
    if (sa === "dead" && sb !== "dead") return 1;
    if (sb === "dead" && sa !== "dead") return -1;
    const pa = winRem(a[1].quota?.primary, a[1].quota?.captured_at ?? 0) ?? 0;
    const pb = winRem(b[1].quota?.primary, b[1].quota?.captured_at ?? 0) ?? 0;
    return pb - pa;
  });

  const aliveSlots = ordered.filter(([, s]) => !s.auth_dead && !((s.cooling_until ?? 0) > now()));
  const bestAid = aliveSlots.length > 0 ? aliveSlots[0][0] : null;
  const bestSlot = bestAid ? slots[bestAid] : null;
  const bestH5 = bestSlot ? winRem(bestSlot.quota?.primary, bestSlot.quota?.captured_at ?? 0) : null;
  const bestWk = bestSlot ? winRem(bestSlot.quota?.secondary, bestSlot.quota?.captured_at ?? 0) : null;

  const counts = { total: ordered.length, live: ordered.filter(([,s]) => getStatus(s) === "live" || getStatus(s) === "low").length, cool: ordered.filter(([,s]) => getStatus(s) === "cool").length, dead: ordered.filter(([,s]) => getStatus(s) === "dead").length };
  const summary = `${counts.total} nodes · ${counts.live} 活 · ${counts.cool} 冷 · ${counts.dead} 死`;

  const refreshAll = async () => {
    setSpinning(true);
    await run(["refresh-all", "--notify"], `已刷新全池 · ${counts.total} 个号`);
    setTimeout(() => setSpinning(false), 750);
  };

  return (
    <div style={{ width: "100vw", height: "100vh", display: "flex", flexDirection: "column", background: t.appBg, color: t.text, fontFamily: "'Space Grotesk'", transition: "background-color .35s ease, color .35s ease" }}>

      {/* ---- Title bar ---- */}
      <div data-tauri-drag-region style={{ height: 38, flexShrink: 0, display: "flex", alignItems: "center", padding: "0 14px", gap: 8, borderBottom: `1px solid ${t.chromeBorder}`, background: t.chromeBg, position: "relative", transition: "background-color .35s ease" }}>
        <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57" }} />
        <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e" }} />
        <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840" }} />
        <span style={{ position: "absolute", left: 0, right: 0, textAlign: "center", fontSize: 12.5, fontWeight: 600, letterSpacing: ".02em", color: t.titleText, pointerEvents: "none" }}>CodexBar</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 2, padding: 2, border: `1px solid ${t.ghostBorder}`, borderRadius: 8 }}>
            <span onClick={() => setTheme("light")} style={{ display: "grid", placeItems: "center", width: 24, height: 20, borderRadius: 6, cursor: "pointer", color: t.sunColor, background: t.sunBg, transition: "background .25s, color .25s" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9 17.7 6.3M6.3 17.7 4.9 19.1"/></svg>
            </span>
            <span onClick={() => setTheme("dark")} style={{ display: "grid", placeItems: "center", width: 24, height: 20, borderRadius: 6, cursor: "pointer", color: t.moonColor, background: t.moonBg, transition: "background .25s, color .25s" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
            </span>
          </div>
          <span style={{ fontSize: 11, color: t.muted, fontFamily: "'JetBrains Mono'" }}>v0.1.0</span>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* ---- Sidebar ---- */}
        <div style={{ width: 52, flexShrink: 0, borderRight: `1px solid ${t.railBorder}`, background: t.railBg, display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 4, transition: "background-color .35s ease" }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, display: "grid", placeItems: "center", color: t.muted }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>
          </div>
          <div style={{ width: 34, height: 34, borderRadius: 9, display: "grid", placeItems: "center", color: t.accentText, background: t.accent }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="12" width="4" height="9" rx="1"/><rect x="10" y="7" width="4" height="14" rx="1"/><rect x="17" y="3" width="4" height="18" rx="1"/></svg>
          </div>
          <div style={{ width: 34, height: 34, borderRadius: 9, display: "grid", placeItems: "center", color: t.muted }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3.5h6v3H9z" fill="currentColor" stroke="none"/></svg>
          </div>
          <div style={{ width: 34, height: 34, borderRadius: 9, display: "grid", placeItems: "center", color: t.muted }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/></svg>
          </div>
          <span style={{ marginTop: "auto", fontSize: 9, color: t.faint, fontFamily: "'JetBrains Mono'" }}>0.1</span>
        </div>

        {/* ---- Content ---- */}
        <div style={{ flex: 1, minWidth: 0, padding: "16px 20px", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* header row */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 13 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-.01em" }}>总览</span>
              <span style={{ fontSize: 11.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{summary}</span>
            </div>
            <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
              <GhostBtn t={t} onClick={refreshAll}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ animation: spinning ? "cbSpin .7s linear" : "none", transformOrigin: "center" }}><path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4"/></svg>
                刷新全池
              </GhostBtn>
              <GhostBtn t={t} onClick={() => run(["refresh-all", "--notify"], "各号 5h 额度已刷新")} accent>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4"/></svg>
                刷新各号
                <span style={{ fontSize: 9.5, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 5px", borderRadius: 4, letterSpacing: ".02em" }}>+1%</span>
              </GhostBtn>
              <span style={{ width: 1, height: 18, background: t.divider, margin: "0 1px" }} />
              <GhostBtn t={t} onClick={() => run(["cool", "300"], `已冷却 ${slots[active ?? ""]?.label ?? "当前号"}`)}>冷却当前号</GhostBtn>
              <GhostBtn t={t} onClick={() => run(["uncool", "all"], "已清除所有冷却")}>清除冷却</GhostBtn>
            </div>
          </div>

          {/* Hero card */}
          {bestSlot && bestAid && (
            <div style={{ display: "flex", alignItems: "center", gap: 18, background: t.heroBg, border: `1px solid ${t.heroBorder}`, borderRadius: 14, padding: "15px 18px", marginBottom: 13, transition: "background-color .35s ease, border-color .35s ease" }}>
              <Ring pct={clamp(bestH5 ?? 0)} r={33} sw={6} color={t.accent} track={t.ringTrack} size={80}>
                <span style={{ fontSize: 19, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
                  {clamp(bestH5 ?? 0)}<span style={{ fontSize: 10, color: t.muted }}>%</span>
                </span>
                <span style={{ fontSize: 8.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>5h</span>
              </Ring>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".14em", color: t.accent, fontFamily: "'JetBrains Mono'" }}>现在该用 · USE NOW</div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 9, marginTop: 3 }}>
                  <span style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-.01em" }}>{bestSlot.label}</span>
                  <span style={{ fontSize: 12, color: t.email, fontFamily: "'JetBrains Mono'" }}>{bestSlot.email}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 13, marginTop: 8, fontSize: 12, color: t.text2, fontFamily: "'JetBrains Mono'" }}>
                  <span>5h <b style={{ color: t.accent }}>{clamp(bestH5 ?? 0)}%</b></span>
                  <span style={{ color: t.faint }}>·</span>
                  <span>周 <b style={{ color: t.accent }}>{clamp(bestWk ?? 0)}%</b></span>
                  <span style={{ color: t.faint }}>·</span>
                  <span>↻ {fmtEta(bestSlot.quota?.primary?.resets_at)}</span>
                  <span style={{ color: t.faint }}>·</span>
                  <span>订阅至 {bestSlot.sub_until?.slice(0, 10) ?? "—"}</span>
                </div>
              </div>
              {bestAid === active ? (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "10px 16px", borderRadius: 9, fontSize: 12.5, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, background: t.accentSoft, flexShrink: 0 }}>✓ 当前使用中</span>
              ) : (
                <span onClick={() => run(["switch", bestSlot.label ?? ""], `当前号 → ${bestSlot.label}`)}
                  style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "10px 16px", borderRadius: 9, fontSize: 12.5, fontWeight: 700, color: t.accentText, background: t.accent, flexShrink: 0, cursor: "pointer", userSelect: "none" }}>
                  设为当前号 →
                </span>
              )}
            </div>
          )}

          {/* Card grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 11, flex: 1, overflow: "auto", alignContent: "start" }}>
            {ordered.map(([aid, slot]) => (
              <AccountCard key={aid} aid={aid} slot={slot} isCurrent={aid === active} isBest={aid === bestAid}
                status={getStatus(slot)} t={t}
                onSelect={() => { if (!slot.auth_dead) run(["switch", slot.label ?? ""], `当前号 → ${slot.label}`); }} />
            ))}
          </div>
        </div>
      </div>

      {/* ---- Toast ---- */}
      {toast && (
        <div style={{ position: "absolute", bottom: 22, left: "50%", transform: "translateX(-50%)", display: "flex", alignItems: "center", gap: 9, padding: "10px 16px", background: t.toastBg, border: `1px solid ${t.toastBorder}`, borderRadius: 10, boxShadow: "0 12px 30px rgba(0,0,0,.3)", fontSize: 12.5, fontWeight: 600, color: t.toastText, backdropFilter: "blur(8px)", animation: "cbToast .25s cubic-bezier(.2,.8,.2,1)", zIndex: 50 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: t.accent }} />{toast}
        </div>
      )}
    </div>
  );
}
