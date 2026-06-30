import { useEffect, useState, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { THEMES, STATUS_COLORS, STATUS_TEXT, type Theme } from "./theme";
import { type AppState, type TokenInfo, type Account, slotToAccount, recommended, clamp, fmtCd } from "./helpers";
import Ring from "./components/Ring";
import Toast from "./components/Toast";
import "./App.css";

function AccountRow({ a, isCurrent, isBest, t, onSelect }: {
  a: Account; isCurrent: boolean; isBest: boolean; t: Theme; onSelect: () => void;
}) {
  const sc = STATUS_COLORS[a.status] ?? STATUS_COLORS.live;
  const isDead = a.status === "dead";
  const isCool = a.status === "cool";

  return (
    <div onClick={onSelect} style={{
      display: "flex", gap: 8, alignItems: "center", padding: "7px 12px",
      background: isCurrent ? t.curCardBg : "transparent", borderRadius: 8,
      cursor: "pointer", userSelect: "none", transition: "background .2s ease",
    }}>
      <Ring pct={isDead ? 0 : a.h5} r={15} sw={3.5} color={sc} track={t.ringTrack} size={36}>
        <span style={{ fontSize: 10, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{isDead ? "—" : a.h5}</span>
      </Ring>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: t.text }}>{a.node}</span>
          <span style={{ fontSize: 8.5, fontWeight: 600, color: sc }}>{STATUS_TEXT[a.status]}</span>
          {isBest && <span style={{ fontSize: 7, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 4px", borderRadius: 3 }}>USE</span>}
          {isCurrent && <span style={{ fontSize: 7, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, padding: "0px 4px", borderRadius: 999 }}>当前</span>}
          <span style={{ marginLeft: "auto", fontSize: 8, color: t.faint, fontFamily: "'JetBrains Mono'" }}>{a.exp}</span>
        </div>
        {!isDead && (
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ fontSize: 8, color: t.muted, fontFamily: "'JetBrains Mono'" }}>周</span>
            <div style={{ flex: 1, height: 3, borderRadius: 1.5, background: t.barTrack, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${clamp(a.wk)}%`, background: sc, borderRadius: 1.5, transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
            </div>
            <span style={{ fontSize: 8.5, color: t.text2, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{a.wk}%</span>
            <span style={{ fontSize: 8, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
              {isCool ? `❄${fmtCd(a.cooldownSec)}` : `↻${a.h5reset}`}
            </span>
          </div>
        )}
        {isDead && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 8, color: "#E0524D", fontWeight: 600 }}>token 失效</span>
            <span style={{ fontSize: 8.5, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 7px", borderRadius: 4, cursor: "pointer" }}>复活</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function MenuBar() {
  const [state, setState] = useState<AppState>({});
  const [tokens, setTokens] = useState<Record<string, TokenInfo>>({});
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [toast, setToast] = useState<string | null>(null);
  const [cooldowns, setCooldowns] = useState<Record<string, number>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
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
  useEffect(() => {
    const id = setInterval(() => {
      setCooldowns(prev => {
        const next = { ...prev }; let changed = false;
        for (const aid of Object.keys(next)) { if (next[aid] > 0) { next[aid]--; changed = true; } if (next[aid] <= 0) delete next[aid]; }
        return changed ? next : prev;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const run = async (actionId: string, args: string[], msg: string) => {
    setLoadingAction(actionId);
    try { await invoke("run_rotate", { args }); } catch (e) { console.error(e); }
    await refresh(); setLoadingAction(null); showToast(msg);
  };

  // macOS keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.metaKey) return;
      if (e.key === "w") { e.preventDefault(); import("@tauri-apps/api/window").then(m => m.getCurrentWindow().hide()); }
      if (e.key === "r" && !e.shiftKey) { e.preventDefault(); refresh(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [refresh]);

  const slots = state.slots ?? {};
  const accounts: Account[] = Object.entries(slots)
    .map(([aid, sl]) => { const a = slotToAccount(aid, sl, tokens); if (cooldowns[aid] != null) a.cooldownSec = cooldowns[aid]; if (a.cooldownSec > 0 && a.status !== "dead") a.status = "cool"; return a; })
    .sort((a, b) => { if (a.status === "dead" && b.status !== "dead") return 1; if (b.status === "dead" && a.status !== "dead") return -1; return b.h5 - a.h5; });

  const currentNode = state.active;
  const hero = recommended(accounts);
  const counts = { live: accounts.filter(a => a.status === "live" || a.status === "low").length, cool: accounts.filter(a => a.status === "cool").length, dead: accounts.filter(a => a.status === "dead").length };

  return (
    <div style={{ width: "100%", height: "100vh", display: "flex", flexDirection: "column", background: t.appBg, color: t.text, fontFamily: "'Space Grotesk'", borderRadius: 16, overflow: "hidden", position: "relative", transition: "background-color .35s ease, color .35s ease" }}>
      {/* Header — clean: logo + name + status dots + theme toggle (one gear only) */}
      <div style={{ display: "flex", alignItems: "center", padding: "10px 14px 8px", gap: 7, borderBottom: `1px solid ${t.chromeBorder}` }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill={t.accent}><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>
        <span style={{ fontSize: 12.5, fontWeight: 700 }}>CodexBar</span>
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: 4 }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: STATUS_COLORS.live }} /><span style={{ fontSize: 9.5, color: t.muted }}>{counts.live}</span>
          {counts.cool > 0 && <><span style={{ width: 5, height: 5, borderRadius: "50%", background: STATUS_COLORS.cool }} /><span style={{ fontSize: 9.5, color: t.muted }}>{counts.cool}</span></>}
          {counts.dead > 0 && <><span style={{ width: 5, height: 5, borderRadius: "50%", background: STATUS_COLORS.dead }} /><span style={{ fontSize: 9.5, color: t.muted }}>{counts.dead}</span></>}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ display: "flex", gap: 1, padding: 1, border: `1px solid ${t.ghostBorder}`, borderRadius: 6 }}>
            <span onClick={() => setTheme("light")} style={{ display: "grid", placeItems: "center", width: 18, height: 16, borderRadius: 4, cursor: "pointer", color: t.sunColor, background: t.sunBg }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9 17.7 6.3M6.3 17.7 4.9 19.1"/></svg>
            </span>
            <span onClick={() => setTheme("dark")} style={{ display: "grid", placeItems: "center", width: 18, height: 16, borderRadius: 4, cursor: "pointer", color: t.moonColor, background: t.moonBg }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
            </span>
          </div>
        </div>
      </div>

      {/* Hero — with metric line like the main window */}
      {hero && (
        <div style={{ display: "flex", alignItems: "center", gap: 11, margin: "10px 14px 0", padding: "10px 12px", background: t.heroBg, border: `1px solid ${t.heroBorder}`, borderRadius: 12, transition: "background-color .35s ease" }}>
          <Ring pct={hero.h5} r={22} sw={4.5} color={t.accent} track={t.ringTrack} size={52}>
            <span style={{ fontSize: 14, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{hero.h5}</span>
          </Ring>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 8.5, fontWeight: 700, letterSpacing: ".12em", color: t.accent, fontFamily: "'JetBrains Mono'" }}>现在该用</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 1 }}>
              <span style={{ fontSize: 16, fontWeight: 700 }}>{hero.node}</span>
              <span style={{ fontSize: 9, color: t.email, fontFamily: "'JetBrains Mono'" }}>{hero.email}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4, fontSize: 10, color: t.text2, fontFamily: "'JetBrains Mono'" }}>
              <span>5h <b style={{ color: t.accent }}>{hero.h5}%</b></span>
              <span style={{ color: t.faint }}>·</span>
              <span>周 <b style={{ color: t.accent }}>{hero.wk}%</b></span>
              <span style={{ color: t.faint }}>·</span>
              <span>↻{hero.h5reset}</span>
            </div>
          </div>
          {hero.aid === currentNode ? (
            <span style={{ fontSize: 10.5, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, background: t.accentSoft, padding: "7px 12px", borderRadius: 8, flexShrink: 0 }}>✓ 使用中</span>
          ) : (
            <span onClick={() => run("switch-hero", ["switch", hero.node], `当前号 → ${hero.node}`)} style={{ fontSize: 10.5, fontWeight: 700, color: t.accentText, background: t.accent, padding: "7px 12px", borderRadius: 8, flexShrink: 0, cursor: "pointer", opacity: loadingAction?.startsWith("switch") ? 0.6 : 1 }}>{loadingAction?.startsWith("switch") ? "切换中…" : "设为当前"}</span>
          )}
        </div>
      )}

      {/* List */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 16px 4px", fontSize: 10.5, color: t.muted }}>
        <span>全部账号</span><span>{accounts.length} 个</span>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 2px", maxHeight: 286 }}>
        {accounts.map(a => (
          <AccountRow key={a.aid} a={a} isCurrent={a.aid === currentNode} isBest={hero?.aid === a.aid} t={t}
            onSelect={() => { if (a.status !== "dead") run(`switch-${a.aid}`, ["switch", a.node], `当前号 → ${a.node}`); }} />
        ))}
      </div>

      {/* Bottom 2x2 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7, padding: "10px 14px 14px", borderTop: `1px solid ${t.chromeBorder}` }}>
        {[
          { id: "refresh-all", label: "刷新全池", loadingLabel: "刷新中…", icon: true, accent: false, action: () => run("refresh-all", ["refresh-all", "--notify"], "已刷新全池") },
          { id: "refresh-each", label: "刷新各号", loadingLabel: "探测中…", icon: true, accent: true, badge: "+1%", action: () => run("refresh-each", ["refresh-all", "--notify"], "各号 5h +1%") },
          { id: "cool", label: "冷却当前号", loadingLabel: "冷却中…", icon: false, accent: false, action: () => run("cool", ["cool", "300"], "已冷却当前号") },
          { id: "uncool", label: "清除冷却", loadingLabel: "解冻中…", icon: false, accent: false, action: () => run("uncool", ["uncool", "all"], "已清除冷却") },
        ].map((btn) => {
          const isLoading = loadingAction === btn.id;
          return (
          <span key={btn.id} onClick={isLoading ? undefined : btn.action} style={{
            display: "flex", alignItems: "center", justifyContent: "center", gap: 5, padding: "8px 0",
            border: `1px solid ${btn.accent ? t.accentBorder : t.ghostBorder}`, borderRadius: 8,
            fontSize: 11, color: btn.accent ? t.accentTextSoft : t.ghostText,
            background: btn.accent ? t.accentSoft : t.ghostBg,
            cursor: isLoading ? "default" : "pointer", userSelect: "none",
            opacity: isLoading ? 0.6 : 1, transition: "opacity .2s",
          }}>
            {isLoading ? <><span style={{ width: 12, height: 12, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", animation: "cbSpin .65s linear infinite", display: "inline-block" }} />{btn.loadingLabel}</> : <>
              {btn.icon && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4"/></svg>}
              {btn.label}
              {btn.badge && <span style={{ fontSize: 8.5, fontWeight: 700, color: t.accentText, background: t.accent, padding: "1px 4px", borderRadius: 3 }}>{btn.badge}</span>}
            </>}
          </span>
        );})}
      </div>

      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}
