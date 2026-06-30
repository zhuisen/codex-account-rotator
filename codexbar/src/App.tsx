import { useEffect, useState, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { THEMES, STATUS_COLORS, STATUS_TEXT, type Theme } from "./theme";
import { type AppState, type TokenInfo, type Account, slotToAccount, recommended, clamp, fmtCd } from "./helpers";
import Ring from "./components/Ring";
import Toast from "./components/Toast";
import GhostButton from "./components/GhostButton";
import LogsPage from "./pages/LogsPage";
import SettingsPage, { getSettings } from "./pages/SettingsPage";
import { notify } from "./hooks/useNotify";
import "./App.css";

type Page = "overview" | "logs" | "settings";

// ---- SVG icons (inline, matching design handoff) ----
const IconBolt = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>;
const IconChart = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="12" width="4" height="9" rx="1"/><rect x="10" y="7" width="4" height="14" rx="1"/><rect x="17" y="3" width="4" height="18" rx="1"/></svg>;
const IconClip = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3.5h6v3H9z" fill="currentColor" stroke="none"/></svg>;
const IconGear = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/></svg>;
const IconRefresh = ({ spin }: { spin?: boolean }) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ animation: spin ? "cbSpin .7s linear" : "none", transformOrigin: "center" }}><path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4"/></svg>;
const IconSun = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9 17.7 6.3M6.3 17.7 4.9 19.1"/></svg>;
const IconMoon = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>;

// ---- Account card (3x2 grid) ----
function AccountCard({ a, isCurrent, isBest, t, onSelect }: {
  a: Account; isCurrent: boolean; isBest: boolean; t: Theme; onSelect: () => void;
}) {
  const [hover, setHover] = useState(false);
  const sc = STATUS_COLORS[a.status] ?? STATUS_COLORS.live;
  const isDead = a.status === "dead";
  const isCool = a.status === "cool";

  return (
    <div onClick={onSelect} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ background: isCurrent ? t.curCardBg : t.cardBg, border: `1px solid ${isCurrent ? t.accent : t.cardBorder}`,
        borderRadius: 12, padding: 12, display: "flex", gap: 11, alignItems: "center",
        cursor: "pointer", userSelect: "none",
        transform: hover ? "translateY(-2px)" : undefined,
        boxShadow: hover ? t.cardHoverShadow : undefined,
        transition: "background .3s ease, border-color .3s ease, transform .15s ease, box-shadow .15s ease" }}>

      <Ring pct={isDead ? 0 : a.h5} r={21} sw={5} color={sc} track={t.ringTrack} size={52}>
        <span style={{ fontSize: 13, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{isDead ? "—" : a.h5}</span>
      </Ring>

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>{a.node}</span>
          <span style={{ fontSize: 9.5, fontWeight: 600, color: sc }}>{STATUS_TEXT[a.status]}</span>
          {isBest && <span style={{ fontSize: 8, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 5px", borderRadius: 4 }}>USE</span>}
          {isCurrent && <span style={{ marginLeft: "auto", fontSize: 8.5, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, padding: "1px 6px", borderRadius: 999 }}>当前</span>}
        </div>
        <div style={{ fontSize: 10.5, color: t.email, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.email}</div>

        {!isDead && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'" }}>周</span>
              <div style={{ flex: 1, height: 4, borderRadius: 2, background: t.barTrack, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${clamp(a.wk)}%`, background: sc, borderRadius: 2, transition: "width .55s cubic-bezier(.4,0,.2,1), background-color .35s ease" }} />
              </div>
              <span style={{ fontSize: 10, color: t.text2, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{a.wk}%</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
              {isCool ? <span style={{ color: "#2BA0C0", fontWeight: 600 }}>❄ 冷却 {fmtCd(a.cooldownSec)}</span> : <span>↻ {a.h5reset}</span>}
              <span>到期 {a.exp}</span>
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
  const [page, setPage] = useState<Page>("overview");
  const [spinning, setSpinning] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [cooldowns, setCooldowns] = useState<Record<string, number>>({});
  const toastRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      const now = Date.now() / 1000;
      const cds: Record<string, number> = {};
      for (const [aid, sl] of Object.entries(s.slots ?? {})) {
        const cd = (sl.cooling_until ?? 0) - now;
        if (cd > 0) cds[aid] = Math.round(cd);
      }
      setCooldowns(cds);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { refresh(); const id = setInterval(refresh, 10_000); return () => clearInterval(id); }, [refresh]);
  useEffect(() => { const u = listen("state-changed", () => refresh()); return () => { u.then(f => f()); }; }, [refresh]);

  const notifiedRef = useRef<Set<string>>(new Set());

  // cooldown countdown (1s)
  useEffect(() => {
    const id = setInterval(() => {
      setCooldowns(prev => {
        const next = { ...prev };
        let changed = false;
        for (const aid of Object.keys(next)) {
          if (next[aid] > 0) { next[aid]--; changed = true; }
          if (next[aid] <= 0) delete next[aid];
        }
        return changed ? next : prev;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const run = async (args: string[], msg: string) => {
    try { await invoke("run_rotate", { args }); } catch (e) { console.error(e); }
    await refresh();
    showToast(msg);
  };

  const slots = state.slots ?? {};
  const accounts: Account[] = Object.entries(slots)
    .map(([aid, sl]) => {
      const a = slotToAccount(aid, sl, tokens);
      if (cooldowns[aid] != null) a.cooldownSec = cooldowns[aid];
      if (a.cooldownSec > 0 && a.status !== "dead") a.status = "cool";
      return a;
    })
    .sort((a, b) => {
      if (a.status === "dead" && b.status !== "dead") return 1;
      if (b.status === "dead" && a.status !== "dead") return -1;
      return b.h5 - a.h5;
    });

  const currentNode = state.active;

  // expiry warnings (check every 60s)
  useEffect(() => {
    const check = () => {
      const settings = getSettings();
      const n = Date.now() / 1000;
      for (const a of accounts) {
        const key = `${a.aid}-${a.exp}`;
        if (notifiedRef.current.has(key)) continue;
        if (a.exp && a.exp !== "—") {
          const subTs = new Date(a.exp).getTime() / 1000;
          const daysLeft = (subTs - n) / 86400;
          if (daysLeft <= settings.subExpiryWarnDays && daysLeft > 0) {
            notify("订阅即将到期", `${a.node} 订阅还剩 ${Math.ceil(daysLeft)} 天 (${a.exp})`);
            notifiedRef.current.add(key);
          } else if (daysLeft <= 0) {
            notify("订阅已到期", `${a.node} 订阅已到期 — 续费否则无 codex 额度`);
            notifiedRef.current.add(key);
          }
        }
        const tokKey = `tok-${a.aid}`;
        if (!notifiedRef.current.has(tokKey) && tokens[a.aid]?.exp) {
          const tokH = (tokens[a.aid].exp! - n) / 3600;
          if (tokH <= settings.tokenExpiryWarnHours && tokH > 0) {
            notify("Token 即将过期", `${a.node} access token 还剩 ${Math.round(tokH)}h`);
            notifiedRef.current.add(tokKey);
          }
        }
      }
    };
    check();
    const id = setInterval(check, 60_000);
    return () => clearInterval(id);
  }, [accounts, tokens]);
  const hero = recommended(accounts);
  const counts = { total: accounts.length, live: accounts.filter(a => a.status === "live" || a.status === "low").length, cool: accounts.filter(a => a.status === "cool").length, dead: accounts.filter(a => a.status === "dead").length };
  const summary = `${counts.total} nodes · ${counts.live} 活 · ${counts.cool} 冷 · ${counts.dead} 死`;

  const refreshAll = async () => { setSpinning(true); await run(["refresh-all", "--notify"], `已刷新全池 · ${counts.total} 个号`); setTimeout(() => setSpinning(false), 750); };

  const sidebarItems: { id: Page; Icon: React.FC; tip: string }[] = [
    { id: "overview" as Page, Icon: IconBolt, tip: "快捷" },
    { id: "overview" as Page, Icon: IconChart, tip: "总览" },
    { id: "logs" as Page, Icon: IconClip, tip: "日志" },
    { id: "settings" as Page, Icon: IconGear, tip: "设置" },
  ];

  const win = getCurrentWindow();

  // macOS keyboard shortcuts (lost when decorations:false)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.metaKey) return;
      switch (e.key) {
        case "w": e.preventDefault(); win.hide(); break;
        case "q": e.preventDefault(); std_process_exit(); break;
        case "m": e.preventDefault(); win.minimize(); break;
        case ",": e.preventDefault(); setPage("settings"); break;
        case "r": if (!e.shiftKey) { e.preventDefault(); refresh(); } break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [win, refresh]);

  const std_process_exit = async () => {
    try { win.close(); } catch { /* fallback */ }
  };

  return (
    <div style={{ width: "100vw", height: "100vh", display: "flex", flexDirection: "column", background: t.appBg, color: t.text, fontFamily: "'Space Grotesk'", borderRadius: 12, overflow: "hidden", boxShadow: t.shadow, transition: "background-color .35s ease, color .35s ease" }}>

      {/* ---- Title bar (38px) ---- */}
      <div data-tauri-drag-region style={{ height: 38, flexShrink: 0, display: "flex", alignItems: "center", padding: "0 14px", gap: 8, borderBottom: `1px solid ${t.chromeBorder}`, background: t.chromeBg, position: "relative", transition: "background-color .35s ease" }}>
        <span onClick={() => win.hide()} style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57", cursor: "pointer" }} title="隐藏" />
        <span onClick={() => win.minimize()} style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e", cursor: "pointer" }} title="最小化" />
        <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840" }} />
        <span data-tauri-drag-region style={{ position: "absolute", left: 0, right: 0, textAlign: "center", fontSize: 12.5, fontWeight: 600, letterSpacing: ".02em", color: t.titleText, pointerEvents: "none" }}>CodexBar</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 2, padding: 2, border: `1px solid ${t.ghostBorder}`, borderRadius: 8 }}>
            <span onClick={() => setTheme("light")} style={{ display: "grid", placeItems: "center", width: 24, height: 20, borderRadius: 6, cursor: "pointer", color: t.sunColor, background: t.sunBg, transition: "background .25s, color .25s" }}><IconSun /></span>
            <span onClick={() => setTheme("dark")} style={{ display: "grid", placeItems: "center", width: 24, height: 20, borderRadius: 6, cursor: "pointer", color: t.moonColor, background: t.moonBg, transition: "background .25s, color .25s" }}><IconMoon /></span>
          </div>
          <span style={{ fontSize: 11, color: t.muted, fontFamily: "'JetBrains Mono'" }}>v0.1.0</span>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* ---- Sidebar (52px) ---- */}
        <div style={{ width: 52, flexShrink: 0, borderRight: `1px solid ${t.railBorder}`, background: t.railBg, display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 4, transition: "background-color .35s ease" }}>
          {sidebarItems.map((it, i) => (
            <div key={i} onClick={() => setPage(it.id)} style={{ width: 34, height: 34, borderRadius: 9, display: "grid", placeItems: "center", cursor: "pointer", color: (i === 1 && page === "overview") || (it.id === page && i > 1) ? t.accentText : t.muted, background: (i === 1 && page === "overview") || (it.id === page && i > 1) ? t.accent : "transparent", transition: "background .2s, color .2s" }} title={it.tip}><it.Icon /></div>
          ))}
          <span style={{ marginTop: "auto", fontSize: 9, color: t.faint, fontFamily: "'JetBrains Mono'" }}>0.1</span>
        </div>

        {/* ---- Content ---- */}
        <div style={{ flex: 1, minWidth: 0, padding: "16px 20px", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {page === "overview" && (
            <>
              {/* header */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 13 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-.01em" }}>总览</span>
                  <span style={{ fontSize: 11.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{summary}</span>
                </div>
                <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
                  <GhostButton t={t} onClick={refreshAll}><IconRefresh spin={spinning} />刷新全池</GhostButton>
                  <GhostButton t={t} onClick={() => run(["refresh-all", "--notify"], "各号 5h 额度 +1%")} accent>
                    <IconRefresh />刷新各号<span style={{ fontSize: 9.5, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 5px", borderRadius: 4, letterSpacing: ".02em" }}>+1%</span>
                  </GhostButton>
                  <span style={{ width: 1, height: 18, background: t.divider, margin: "0 1px" }} />
                  <GhostButton t={t} onClick={() => run(["cool", "300"], `已冷却 ${slots[currentNode ?? ""]?.label ?? "当前号"}`)}>冷却当前号</GhostButton>
                  <GhostButton t={t} onClick={() => run(["uncool", "all"], "已清除所有冷却")}>清除冷却</GhostButton>
                </div>
              </div>

              {/* Hero */}
              {hero && (
                <div style={{ display: "flex", alignItems: "center", gap: 18, background: t.heroBg, border: `1px solid ${t.heroBorder}`, borderRadius: 14, padding: "15px 18px", marginBottom: 13, boxShadow: t.heroShadow, transition: "background-color .35s ease, border-color .35s ease" }}>
                  <Ring pct={hero.h5} r={33} sw={6} color={t.accent} track={t.ringTrack} size={80}>
                    <span style={{ fontSize: 19, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1, marginTop: -1 }}>{hero.h5}<span style={{ fontSize: 10, color: t.muted }}>%</span></span>
                    <span style={{ fontSize: 8.5, color: t.muted, fontFamily: "'JetBrains Mono'", lineHeight: 1, marginTop: 2 }}>5h</span>
                  </Ring>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".14em", color: t.accent, fontFamily: "'JetBrains Mono'" }}>现在该用 · USE NOW</div>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 9, marginTop: 3 }}>
                      <span style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-.01em" }}>{hero.node}</span>
                      <span style={{ fontSize: 12, color: t.email, fontFamily: "'JetBrains Mono'" }}>{hero.email}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 13, marginTop: 8, fontSize: 12, color: t.text2, fontFamily: "'JetBrains Mono'" }}>
                      <span>5h <b style={{ color: t.accent }}>{hero.h5}%</b></span>
                      <span style={{ color: t.faint }}>·</span>
                      <span>周 <b style={{ color: t.accent }}>{hero.wk}%</b></span>
                      <span style={{ color: t.faint }}>·</span>
                      <span>↻ {hero.h5reset}</span>
                      <span style={{ color: t.faint }}>·</span>
                      <span>订阅至 {hero.exp}</span>
                    </div>
                  </div>
                  {hero.aid === currentNode ? (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "10px 16px", borderRadius: 9, fontSize: 12.5, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, background: t.accentSoft, flexShrink: 0 }}>✓ 当前使用中</span>
                  ) : (
                    <span onClick={() => run(["switch", hero.node], `当前号 → ${hero.node}`)} style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "10px 16px", borderRadius: 9, fontSize: 12.5, fontWeight: 700, color: t.accentText, background: t.accent, flexShrink: 0, cursor: "pointer", userSelect: "none" }}>设为当前号 →</span>
                  )}
                </div>
              )}

              {/* Card grid */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 11, flex: 1, overflow: "auto", alignContent: "start" }}>
                {accounts.map(a => (
                  <AccountCard key={a.aid} a={a} isCurrent={a.aid === currentNode} isBest={hero?.aid === a.aid} t={t}
                    onSelect={() => { if (!a.status.startsWith("dead")) run(["switch", a.node], `当前号 → ${a.node}`); }} />
                ))}
              </div>
            </>
          )}

          {page === "logs" && <LogsPage t={t} />}
          {page === "settings" && <SettingsPage t={t} />}
        </div>
      </div>

      {/* Toast */}
      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}
