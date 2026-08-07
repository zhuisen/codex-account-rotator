import { useState, useEffect, useRef, useCallback, Fragment } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { LogicalSize } from "@tauri-apps/api/dpi";
import { THEMES, STATUS_COLORS } from "./theme";
import Toast from "./components/Toast";
import AccountRow from "./components/AccountRow";
import ProbeButton from "./components/ProbeButton";
import { useStore } from "./hooks/useStore";
import { fmtAgo } from "./helpers";
import { usePrivacy } from "./hooks/usePrivacy";
import "./App.css";
import "./menubar.css";

const PANEL_W = 412;          // must match inner_size / toggle_menubar in lib.rs
const PANEL_H_MIN = 220;
const PANEL_H_MAX = 760;

function loadTheme(): "dark" | "light" {
  try {
    const v = localStorage.getItem("codexbar_theme");
    if (v === "light" || v === "dark") return v;
  } catch { /* ignore */ }
  return "dark";
}

const IconBolt = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>;
const IconRefresh = ({ size = 13 }: { size?: number }) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4"/></svg>;
const IconEye = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M1.6 12S5.3 5.5 12 5.5 22.4 12 22.4 12 18.7 18.5 12 18.5 1.6 12 1.6 12z"/><circle cx="12" cy="12" r="3"/></svg>;
const IconEyeOff = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9.9 5.8A9.6 9.6 0 0 1 12 5.5c6.7 0 10.4 6.5 10.4 6.5a18 18 0 0 1-3.4 4.2M6.2 7.8A18 18 0 0 0 1.6 12S5.3 18.5 12 18.5c1.6 0 3-.4 4.3-.9M3 3l18 18"/></svg>;
const IconWarn = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 1 21h22L12 2zm1 14h-2v2h2v-2zm0-7h-2v5h2V9z"/></svg>;

export default function MenuBar() {
  const { accounts, hero, currentNode, counts, lastRefreshAt, cardAlert, loadingAction, toast, refresh, run, showToast } = useStore();
  const [theme, setTheme] = useState<"dark" | "light">(loadTheme);
  const rootRef = useRef<HTMLDivElement>(null);
  const { privacy, toggle: togglePrivacy } = usePrivacy();
  const t = THEMES[theme];

  const toggleTheme = (v: "dark" | "light") => {
    setTheme(v);
    try { localStorage.setItem("codexbar_theme", v); } catch { /* ignore */ }
  };

  /** Reveal the main window and dismiss the popover. */
  const openMain = useCallback(async (navigateTo?: string) => {
    try {
      const [{ WebviewWindow }, { emit }] = await Promise.all([
        import("@tauri-apps/api/webviewWindow"),
        import("@tauri-apps/api/event"),
      ]);
      const main = await WebviewWindow.getByLabel("main");
      if (main) { await main.show(); await main.setFocus(); await main.center(); }
      if (navigateTo) await emit(navigateTo);
      getCurrentWindow().hide();
    } catch (e) { console.error(e); }
  }, []);

  // The panel is content-sized in the design (`height: fit-content`), but a Tauri window has a fixed
  // frame — so measure and follow. Without this the popover keeps a 580px frame and paints dead space
  // below a short pool, or clips a long one.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    let last = 0;
    const apply = () => {
      const h = Math.min(PANEL_H_MAX, Math.max(PANEL_H_MIN, Math.ceil(el.scrollHeight)));
      if (Math.abs(h - last) < 2) return;
      last = h;
      getCurrentWindow().setSize(new LogicalSize(PANEL_W, h)).catch(() => {});
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.metaKey) return;
      if (e.key === "w") { e.preventDefault(); getCurrentWindow().hide(); }
      if (e.key === "r" && !e.shiftKey) { e.preventDefault(); refresh(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [refresh]);

  const alive = accounts.filter(a => a.status !== "dead");
  const dead = accounts.filter(a => a.status === "dead");
  const bestPct = alive.reduce((m, a) => Math.max(m, a.windows[0]?.pct ?? -1), -1);

  const actions = [
    { id: "refresh-all", label: "刷新全池", loadingLabel: "刷新中…", accent: true, badge: "免费",
      hint: "读取 Codex 官方额度接口(GET),不消耗额度",
      action: () => run("refresh-all", ["refresh-all", "--notify"], "已刷新全池") },
    { id: "health", label: "检查 token", loadingLabel: "检查中…", accent: false, badge: undefined as string | undefined,
      hint: "逐号问服务端 token 是否被作废(零消耗,不刷新 token);发现失效会记录。约 10s",
      action: () => run("health", ["health"], "已检查 token") },
  ];

  return (
    <div ref={rootRef} className="mb-root" style={{ background: t.appBg, color: t.text, border: `1px solid ${t.chromeBorder}` }}>

      {/* Header */}
      <div className="mb-header" style={{ background: t.chromeBg, borderBottom: `1px solid ${t.chromeBorder}` }}>
        <span style={{ color: t.accent, display: "grid", placeItems: "center" }}><IconBolt /></span>
        <span className="mb-header-logo">CodexBar</span>
        <div className="mb-status-dots">
          <span className="mb-dot" style={{ background: STATUS_COLORS.live }} /><span className="mb-dot-count" style={{ color: STATUS_COLORS.live }}>{counts.live}</span>
          {counts.cool > 0 && <><span className="mb-dot" style={{ background: STATUS_COLORS.cool }} /><span className="mb-dot-count" style={{ color: t.muted }}>{counts.cool}</span></>}
          {counts.dead > 0 && <><span className="mb-dot" style={{ background: STATUS_COLORS.dead }} /><span className="mb-dot-count" style={{ color: t.muted }}>{counts.dead}</span></>}
        </div>
        <div className="mb-theme-toggle">
          <div className="mb-theme-group" style={{ border: `1px solid ${t.ghostBorder}` }}>
            <span className="mb-theme-btn" onClick={() => toggleTheme("light")} style={{ color: t.sunColor, background: t.sunBg }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9 17.7 6.3M6.3 17.7 4.9 19.1"/></svg>
            </span>
            <span className="mb-theme-btn" onClick={() => toggleTheme("dark")} style={{ color: t.moonColor, background: t.moonBg }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
            </span>
          </div>
          <span className="mb-settings-btn" onClick={togglePrivacy}
            title={privacy ? "打码中 — 邮箱已遮蔽,可安全截图。点击恢复" : "打码:遮蔽邮箱,方便截图分享"}
            style={{ color: privacy ? t.accent : t.muted }}>
            {privacy ? <IconEyeOff /> : <IconEye />}
          </span>
          <span className="mb-settings-btn" onClick={() => openMain("navigate-settings")} title="设置" style={{ color: t.muted }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3.2"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/></svg>
          </span>
        </div>
      </div>

      {/* Sub-header */}
      <div className="mb-list-header">
        <span className="mb-list-title" style={{ color: t.muted }}>可用账号</span>
        {lastRefreshAt && (
          <span className="mb-refreshed" style={{ color: t.faint }}><IconRefresh size={10} />上次刷新 {fmtAgo(lastRefreshAt)}</span>
        )}
        <span className="mb-list-count" style={{ color: t.muted, marginLeft: lastRefreshAt ? undefined : "auto" }}>{alive.length} 个</span>
      </div>

      {/* Expiring reset-card banner */}
      {cardAlert && (
        <div className="mb-banner" style={{ background: "rgba(224,144,28,.1)", border: "1px solid rgba(224,144,28,.45)" }}>
          <span className="mb-banner-icon" style={{ color: "#f2b45c" }}><IconWarn /></span>
          <div className="mb-banner-body">
            <div className="mb-banner-title" style={{ color: "#f2b45c" }}>
              重置卡即将到期 — {cardAlert.node} · {cardAlert.cardsExpiring || 1} 张 {Math.max(1, Math.ceil(cardAlert.cardDays ?? 0))} 天后作废
            </div>
            <div className="mb-banner-sub" style={{ color: "#b08d55" }}>
              {cardAlert.node} 共 {cardAlert.cards} 张 · 用卡可立即把周额度重置为 100%
            </div>
          </div>
          {/* Redeeming is interactive-TUI only: the consume endpoint is server-gated on the window
              being eligible, and firing it blind would burn a card for a `nothingToReset`. So this
              slot tells you how instead of pretending to do it. */}
          <span className="mb-banner-hint"
            title="重置卡只能在交互式 TUI 里用,且服务端要求当前周窗口“需要重置”才放行(codex exec 无效)"
            onClick={() => showToast("终端运行 codex → 输入 /usage → Redeem usage limit reset")}
            style={{ color: "#1c1104", background: "#E0901C", cursor: "pointer" }}>用卡: /usage</span>
        </div>
      )}

      {/* Account list — clicking any account reveals the main window */}
      <div className="mb-list">
        {alive.map(a => (
          <AccountRow key={a.aid} a={a} isCurrent={a.aid === currentNode} isBest={hero?.aid === a.aid}
            bestPct={bestPct} privacy={privacy} t={t} onSelect={() => openMain()} />
        ))}

        {dead.length > 0 && (
          <details className="mb-dead-fold">
            <summary className="mb-dead-summary" style={{ color: t.muted, borderTop: `1px solid ${t.chromeBorder}` }}>
              <span className="mb-dead-dot" style={{ background: STATUS_COLORS.dead }} />
              {dead.length} 个失效账号
              <span className="mb-dead-chevron">▸</span>
            </summary>
            <div className="mb-dead-list">
              {dead.map(a => (
                <AccountRow key={a.aid} a={a} isCurrent={a.aid === currentNode} isBest={false} bestPct={bestPct} privacy={privacy} t={t} onSelect={() => openMain()} />
              ))}
            </div>
          </details>
        )}
      </div>

      {/* Bottom actions — 三格。第三格是唯一会花额度的,靠 ProbeButton 的琥珀+两段确认与前两格区分 */}
      <div className="mb-actions" style={{ borderTop: `1px solid ${t.chromeBorder}` }}>
        {actions.map((btn, i) => {
          const isLoading = loadingAction === btn.id;
          return (
            <Fragment key={btn.id}>
              {i > 0 && <span className="mb-action-divider" style={{ background: t.chromeBorder }} />}
              <span title={btn.hint}
                className={`mb-action-btn${isLoading ? " loading" : ""}`}
                onClick={isLoading ? undefined : btn.action}
                style={{ color: btn.accent ? t.accent : t.ghostText, background: btn.accent ? "rgba(45,212,191,.07)" : "transparent" }}>
                {isLoading ? <><span className="mb-spinner" />{btn.loadingLabel}</> : <>
                  <IconRefresh />
                  {btn.label}
                  {btn.badge && <span className="mb-action-badge" style={{ color: t.accentText, background: t.accent }}>{btn.badge}</span>}
                </>}
              </span>
            </Fragment>
          );
        })}
        <span className="mb-action-divider" style={{ background: t.chromeBorder }} />
        <ProbeButton t={t} variant="menubar" label="探针"
          hint={`对 ${alive.length} 个号各发一次真实补全(问 hi 要求答 ok),证明"真的还能干活"——token 有效但订阅到期/模型权限被撤/被限流,只有这个测得出来。⚠️ 消耗周额度(实测单次 <1%)`}
          loading={loadingAction === "probe-all"} loadingText="探测中…"
          onConfirm={() => run("probe-all", ["probe", "--all"], "探针 全池")} />
      </div>

      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}
