import { useState, useEffect } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { THEMES, STATUS_COLORS } from "./theme";
import Ring from "./components/Ring";
import Toast from "./components/Toast";
import AccountRow from "./components/AccountRow";
import { useStore } from "./hooks/useStore";
import "./App.css";
import "./menubar.css";

function loadTheme(): "dark" | "light" {
  try {
    const v = localStorage.getItem("codexbar_theme");
    if (v === "light" || v === "dark") return v;
  } catch { /* ignore */ }
  return "dark";
}

export default function MenuBar() {
  const { accounts, hero, currentNode, counts, loadingAction, toast, refresh, run } = useStore();
  const [theme, setTheme] = useState<"dark" | "light">(loadTheme);
  const t = THEMES[theme];

  const toggleTheme = (v: "dark" | "light") => {
    setTheme(v);
    try { localStorage.setItem("codexbar_theme", v); } catch { /* ignore */ }
  };

  const openSettings = async () => {
    try {
      const [{ WebviewWindow }, { emit }] = await Promise.all([
        import("@tauri-apps/api/webviewWindow"),
        import("@tauri-apps/api/event"),
      ]);
      const main = await WebviewWindow.getByLabel("main");
      if (main) { await main.show(); await main.setFocus(); await main.center(); }
      await emit("navigate-settings");
      getCurrentWindow().hide();
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.metaKey) return;
      if (e.key === "w") { e.preventDefault(); getCurrentWindow().hide(); }
      if (e.key === "r" && !e.shiftKey) { e.preventDefault(); refresh(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [refresh]);

  const heroIsCurrent = hero?.aid === currentNode;
  const aliveAccounts = accounts.filter(a => a.status !== "dead");
  const deadAccounts = accounts.filter(a => a.status === "dead");

  return (
    <div className="mb-root" style={{ background: t.appBg, color: t.text, boxShadow: t.shadow }}>
      {/* Header */}
      <div className="mb-header" style={{ borderBottom: `1px solid ${t.chromeBorder}` }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill={t.accent}><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>
        <span className="mb-header-logo">CodexBar</span>
        <div className="mb-status-dots">
          <span className="mb-dot" style={{ background: STATUS_COLORS.live }} /><span className="mb-dot-count" style={{ color: t.muted }}>{counts.live}</span>
          {counts.cool > 0 && <><span className="mb-dot" style={{ background: STATUS_COLORS.cool }} /><span className="mb-dot-count" style={{ color: t.muted }}>{counts.cool}</span></>}
          {counts.dead > 0 && <><span className="mb-dot" style={{ background: STATUS_COLORS.dead }} /><span className="mb-dot-count" style={{ color: t.muted }}>{counts.dead}</span></>}
        </div>
        <div className="mb-theme-toggle">
          <div className="mb-theme-group" style={{ border: `1px solid ${t.ghostBorder}` }}>
            <span className="mb-theme-btn" onClick={() => toggleTheme("light")} style={{ color: t.sunColor, background: t.sunBg }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9 17.7 6.3M6.3 17.7 4.9 19.1"/></svg>
            </span>
            <span className="mb-theme-btn" onClick={() => toggleTheme("dark")} style={{ color: t.moonColor, background: t.moonBg }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
            </span>
          </div>
          <span className="mb-settings-btn" onClick={openSettings} title="设置" style={{ color: t.muted }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/></svg>
          </span>
        </div>
      </div>

      {/* Hero — only show full card when there's a better option to switch to */}
      {hero && !heroIsCurrent && (
        <div className="mb-hero" style={{ background: t.heroBg, border: `1px solid ${t.heroBorder}` }}>
          <Ring pct={hero.tightest < 0 ? 0 : hero.tightest} r={24} sw={5} color={t.accent} track={t.ringTrack} size={58}>
            <span style={{ fontSize: 15, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{hero.tightest < 0 ? "—" : hero.tightest}</span>
          </Ring>
          <div className="mb-hero-info">
            <div className="mb-hero-label" style={{ color: t.accent }}>建议切到</div>
            <div className="mb-hero-name">{hero.node}</div>
            <div className="mb-hero-email" style={{ color: t.email }}>{hero.email}</div>
            {hero.windows.length > 0 && (
              <div className="mb-hero-windows" style={{ color: t.text2 }}>
                {hero.windows.map(w => <span key={w.label}>{w.label} <b style={{ color: t.accent }}>{w.pct}%</b> <span style={{ color: t.muted }}>↻{w.reset}</span></span>)}
              </div>
            )}
          </div>
          <span className="mb-hero-action"
            onClick={() => run("switch-hero", ["switch", hero.node], `当前号 → ${hero.node}`)}
            style={{ color: t.accentText, background: t.accent, opacity: loadingAction?.startsWith("switch") ? 0.6 : 1 }}>
            {loadingAction?.startsWith("switch") ? "切换中…" : "切换 →"}
          </span>
        </div>
      )}

      {/* Account list */}
      <div className="mb-list-header" style={{ color: t.muted }}>
        <span>可用账号</span><span>{aliveAccounts.length} 个</span>
      </div>
      <div className="mb-list">
        {aliveAccounts.map(a => (
          <AccountRow key={a.aid} a={a} isCurrent={a.aid === currentNode} isBest={hero?.aid === a.aid} t={t}
            onSelect={() => { if (a.aid !== currentNode) run(`switch-${a.aid}`, ["switch", a.node], `当前号 → ${a.node}`); }} />
        ))}

        {/* Dead accounts — collapsed by default */}
        {deadAccounts.length > 0 && (
          <details className="mb-dead-fold">
            <summary className="mb-dead-summary" style={{ color: t.muted, borderTop: `1px solid ${t.chromeBorder}` }}>
              <span className="mb-dead-dot" style={{ background: STATUS_COLORS.dead }} />
              {deadAccounts.length} 个失效账号
              <span className="mb-dead-chevron">▸</span>
            </summary>
            <div className="mb-dead-list">
              {deadAccounts.map(a => (
                <AccountRow key={a.aid} a={a} isCurrent={a.aid === currentNode} isBest={false} t={t} onSelect={() => {}} />
              ))}
            </div>
          </details>
        )}

        <div className="mb-list-spacer" />
      </div>

      {/* Bottom actions — only refresh, no cool/uncool in menu bar */}
      <div className="mb-actions" style={{ background: t.chromeBorder, borderTop: `1px solid ${t.chromeBorder}` }}>
        {[
          { id: "refresh-all", label: "刷新全池", loadingLabel: "刷新中…", accent: true, badge: "免费" as string | undefined, hint: "读取 Codex 官方额度接口(GET),不消耗额度", action: () => run("refresh-all", ["refresh-all", "--notify"], "已刷新全池") },
          { id: "health", label: "检查token", loadingLabel: "检查中…", accent: false, badge: undefined as string | undefined, hint: "只读检查各号 token 是否存活,不刷新 token", action: () => run("health", ["health"], "已检查 token") },
        ].map((btn) => {
          const isLoading = loadingAction === btn.id;
          return (
            <span key={btn.id} title={btn.hint}
              className={`mb-action-btn${isLoading ? " loading" : ""}`}
              onClick={isLoading ? undefined : btn.action}
              style={{ color: btn.accent ? t.accentTextSoft : t.ghostText, background: btn.accent ? t.accentSoft : t.appBg }}>
              {isLoading ? <><span className="mb-spinner" />{btn.loadingLabel}</> : <>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4"/></svg>
                {btn.label}
                {btn.badge && <span className="mb-action-badge" style={{ color: t.accentText, background: t.accent }}>{btn.badge}</span>}
              </>}
            </span>
          );
        })}
      </div>

      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}
