import { useState, useMemo, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { THEMES } from "./theme";
import Ring from "./components/Ring";
import Toast from "./components/Toast";
import GhostButton from "./components/GhostButton";
import AccountCard from "./components/AccountCard";
import DetailModal, { type AccountDetail } from "./components/DetailModal";
import LogsPage from "./pages/LogsPage";
import TokensPage from "./pages/TokensPage";
import SettingsPage, { getSettings } from "./pages/SettingsPage";
import { useStore } from "./hooks/useStore";
import { useExpiryWatch } from "./hooks/useExpiryWatch";
import { useDeadWatch } from "./hooks/useDeadWatch";
import { useAutoSwitch } from "./hooks/useAutoSwitch";
import { useKeyboard } from "./hooks/useKeyboard";
import { fmtAgo, CARD_WARN_DAYS, maskId } from "./helpers";
import { usePrivacy } from "./hooks/usePrivacy";
import { IconTicket } from "./components/CardBadge";
import ProbeButton from "./components/ProbeButton";
import PlanBadge from "./components/PlanBadge";
import "./App.css";

type Page = "overview" | "tokens" | "logs" | "settings";

const IconChart = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="12" width="4" height="9" rx="1"/><rect x="10" y="7" width="4" height="14" rx="1"/><rect x="17" y="3" width="4" height="18" rx="1"/></svg>;
const IconChart2 = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 20h18M6 20V9m5 11V4m5 16v-7"/></svg>;
const IconClip = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3.5h6v3H9z" fill="currentColor" stroke="none"/></svg>;
const IconGear = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/></svg>;
const IconRefresh = ({ spin }: { spin?: boolean }) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ animation: spin ? "cbSpin .7s linear" : "none", transformOrigin: "center" }}><path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4"/></svg>;
const IconSun = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9 17.7 6.3M6.3 17.7 4.9 19.1"/></svg>;
const IconEye = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><path d="M1.6 12S5.3 5.5 12 5.5 22.4 12 22.4 12 18.7 18.5 12 18.5 1.6 12 1.6 12z"/><circle cx="12" cy="12" r="3"/></svg>;
const IconEyeOff = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><path d="M9.9 5.8A9.6 9.6 0 0 1 12 5.5c6.7 0 10.4 6.5 10.4 6.5a18 18 0 0 1-3.4 4.2M6.2 7.8A18 18 0 0 0 1.6 12S5.3 18.5 12 18.5c1.6 0 3-.4 4.3-.9M3 3l18 18"/></svg>;
const IconMoon = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>;

export default function App() {
  const { accounts, hero, currentNode, slots, counts, tokens, lastRefreshAt, loadingAction, toast, refresh, run, showToast } = useStore();
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [page, setPage] = useState<Page>("overview");
  const [detailModal, setDetailModal] = useState<AccountDetail | null>(null);
  const [selectedCard, setSelectedCard] = useState<string | null>(null);
  const [autoSwitch, setAutoSwitch] = useState(() => getSettings().autoSwitchEnabled);
  const { privacy, toggle: togglePrivacy } = usePrivacy();

  const t = THEMES[theme];
  const win = useMemo(() => getCurrentWindow(), []);
  const summary = `${counts.total} nodes · ${counts.live} 活 · ${counts.cool} 冷 · ${counts.dead} 死`;

  // menubar gear button → jump to settings page + reveal window
  useEffect(() => {
    const un = listen("navigate-settings", () => {
      setPage("settings");
      win.show(); win.setFocus();
    });
    return () => { un.then(f => f()); };
  }, [win]);

  const aliveByLabel = accounts.filter(a => a.status !== "dead").sort((a, b) => a.node.localeCompare(b.node, undefined, { numeric: true }));
  useExpiryWatch(accounts, tokens);
  // Dead-account alerts live in the MAIN window only — the menubar popover renders the same store, so
  // running the watcher in both would double-notify.
  useDeadWatch(accounts, currentNode);
  useAutoSwitch(accounts, currentNode, run);
  useKeyboard(win, refresh, setPage as (p: string) => void, (idx) => {
    const target = aliveByLabel[idx];
    if (target && target.aid !== currentNode) run(`switch-${target.aid}`, ["switch", target.node], `⌘${idx + 1} → ${target.node}`);
  });

  const sidebarItems: { id: Page; Icon: React.FC; tip: string }[] = [
    { id: "overview", Icon: IconChart, tip: "总览" },
    { id: "tokens", Icon: IconChart2, tip: "Token 消耗" },
    { id: "logs", Icon: IconClip, tip: "日志" },
    { id: "settings", Icon: IconGear, tip: "设置" },
  ];

  return (
    <div style={{ width: "100vw", height: "100vh", display: "flex", flexDirection: "column", background: t.appBg, color: t.text, fontFamily: "'Space Grotesk'", borderRadius: 12, overflow: "hidden", boxShadow: t.shadow, transition: "background-color .35s ease, color .35s ease" }}>

      {/* Title bar */}
      <div data-tauri-drag-region style={{ height: 38, flexShrink: 0, display: "flex", alignItems: "center", padding: "0 14px", gap: 8, borderBottom: `1px solid ${t.chromeBorder}`, background: t.chromeBg, position: "relative", transition: "background-color .35s ease" }}>
        <span onClick={() => win.hide()} style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57", cursor: "pointer" }} title="隐藏" />
        <span onClick={() => win.minimize()} style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e", cursor: "pointer" }} title="最小化" />
        <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840" }} />
        <span data-tauri-drag-region style={{ position: "absolute", left: 0, right: 0, textAlign: "center", fontSize: 12.5, fontWeight: 600, letterSpacing: ".02em", color: t.titleText, pointerEvents: "none" }}>CodexBar</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <span onClick={togglePrivacy} title={privacy ? "打码中 — 邮箱与 account_id 已遮蔽,可安全截图。点击恢复" : "打码:遮蔽邮箱与 account_id,方便截图分享"}
            style={{ display: "grid", placeItems: "center", width: 24, height: 20, borderRadius: 6, cursor: "pointer",
                     color: privacy ? t.accentText : t.muted, background: privacy ? t.accent : "transparent", transition: "background .2s, color .2s" }}>
            {privacy ? <IconEyeOff /> : <IconEye />}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: 2, padding: 2, border: `1px solid ${t.ghostBorder}`, borderRadius: 8 }}>
            <span onClick={() => setTheme("light")} style={{ display: "grid", placeItems: "center", width: 24, height: 20, borderRadius: 6, cursor: "pointer", color: t.sunColor, background: t.sunBg, transition: "background .25s, color .25s" }}><IconSun /></span>
            <span onClick={() => setTheme("dark")} style={{ display: "grid", placeItems: "center", width: 24, height: 20, borderRadius: 6, cursor: "pointer", color: t.moonColor, background: t.moonBg, transition: "background .25s, color .25s" }}><IconMoon /></span>
          </div>
          <span style={{ fontSize: 11, color: t.muted, fontFamily: "'JetBrains Mono'" }}>v0.6.0</span>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Sidebar */}
        <div style={{ width: 52, flexShrink: 0, borderRight: `1px solid ${t.railBorder}`, background: t.railBg, display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 4, transition: "background-color .35s ease" }}>
          {sidebarItems.map((it) => (
            <div key={it.id} onClick={() => setPage(it.id)} style={{ width: 34, height: 34, borderRadius: 9, display: "grid", placeItems: "center", cursor: "pointer", color: page === it.id ? t.accentText : t.muted, background: page === it.id ? t.accent : "transparent", transition: "background .2s, color .2s" }} title={it.tip}><it.Icon /></div>
          ))}
          <span style={{ marginTop: "auto", fontSize: 9, color: t.faint, fontFamily: "'JetBrains Mono'" }}>0.6</span>
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0, padding: "16px 20px", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {page === "overview" && (
            <>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 12 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-.01em" }}>总览</span>
                  <span style={{ fontSize: 11.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{summary}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
                <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
                  <GhostButton t={t} onClick={() => run("refresh-all", ["refresh-all", "--notify"], `已刷新全池 · ${counts.total} 个号`)} loading={loadingAction === "refresh-all"} loadingText="刷新中…"><IconRefresh spin={loadingAction === "refresh-all"} />刷新全池</GhostButton>
                  <GhostButton t={t} onClick={() => run("health", ["health"], "已检查各号 token")} accent loading={loadingAction === "health"} loadingText="检查中…">
                    检查 token
                  </GhostButton>
                  <ProbeButton t={t} label="探针 全池"
                    hint={`对 ${counts.total} 个号各发一次真实补全(问 hi 要求答 ok),证明"真的还能干活"——token 有效但订阅到期/模型权限被撤/被限流,只有这个测得出来。⚠️ 消耗周额度(实测单次 <1%),约 ${counts.total * 7}s`}
                    loading={loadingAction === "probe-all"} loadingText="探测中…"
                    onConfirm={() => run("probe-all", ["probe", "--all"], "探针 全池")} />
                  <span onClick={() => {
                    const next = !autoSwitch;
                    setAutoSwitch(next);
                    const s = getSettings(); s.autoSwitchEnabled = next;
                    localStorage.setItem("codexbar_settings", JSON.stringify(s));
                    showToast(next ? "✓ 自动切号 已开启" : "自动切号 已关闭");
                  }} style={{
                    display: "flex", alignItems: "center", gap: 6, padding: "5px 13px", borderRadius: 8, cursor: "pointer", userSelect: "none", fontSize: 11.5, fontWeight: 600, transition: "all .2s",
                    border: `1px solid ${autoSwitch ? t.accentBorder : t.ghostBorder}`,
                    color: autoSwitch ? t.accent : t.ghostText,
                    background: autoSwitch ? t.accentSoft : "transparent",
                  }}>
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: autoSwitch ? t.accent : t.faint, animation: autoSwitch ? "cbDotPulse 2s ease-in-out infinite" : "none" }} />
                    {autoSwitch ? "自动切号 开" : "自动切号"}
                  </span>
                  <span style={{ width: 1, height: 18, background: t.divider, margin: "0 1px" }} />
                  <GhostButton t={t} onClick={() => run("cool", ["cool", "300"], `已冷却 ${slots[currentNode ?? ""]?.label ?? "当前号"}`)} loading={loadingAction === "cool"} loadingText="冷却中…">冷却当前号</GhostButton>
                  <GhostButton t={t} onClick={() => run("uncool", ["uncool", "all"], "已清除所有冷却")} loading={loadingAction === "uncool"} loadingText="解冻中…">清除冷却</GhostButton>
                </div>
                <span style={{ fontSize: 10, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
                  {lastRefreshAt ? `上次全池刷新 ${fmtAgo(lastRefreshAt)}` : "尚未刷新过全池"}
                </span>
                </div>
              </div>

              {(() => {
                const cur = accounts.find(a => a.aid === currentNode);
                const betterExists = hero && hero.aid !== currentNode;
                if (!cur) return null;
                const sc = cur.status === "dead" ? "#E0524D" : t.accent;
                return (
                  <div style={{ display: "flex", alignItems: "center", gap: 18, background: t.heroBg, border: `1px solid ${t.heroBorder}`, borderRadius: 14, padding: "15px 18px", marginBottom: 13, boxShadow: t.heroShadow, transition: "background-color .35s ease, border-color .35s ease" }}>
                    <Ring pct={cur.tightest < 0 ? 0 : cur.tightest} r={33} sw={6} color={sc} track={t.ringTrack} size={80}>
                      <span style={{ fontSize: 19, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1, marginTop: -1 }}>{cur.tightest < 0 ? "—" : cur.tightest}<span style={{ fontSize: 10, color: t.muted }}>%</span></span>
                      <span style={{ fontSize: 8.5, color: t.muted, fontFamily: "'JetBrains Mono'", lineHeight: 1, marginTop: 2 }}>{cur.windows[0]?.label ?? ""}</span>
                    </Ring>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".14em", color: t.accent, fontFamily: "'JetBrains Mono'" }}>当前使用中</div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: 9, marginTop: 3 }}>
                        <span style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-.01em" }}>{cur.node}</span>
                        <PlanBadge plan={cur.plan} t={t} size={10} />
                        <span style={{ fontSize: 12, color: t.email, fontFamily: "'JetBrains Mono'" }}>{maskId(cur.email, privacy)}</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 13, marginTop: 8, fontSize: 12, color: t.text2, fontFamily: "'JetBrains Mono'" }}>
                        {cur.windows.map((w, i) => (
                          <span key={w.label}>{i > 0 && <span style={{ color: t.faint, marginRight: 13 }}>·</span>}{w.label} <b style={{ color: sc }}>{w.pct}%</b> <span style={{ color: t.muted }}>↻{w.reset}</span></span>
                        ))}
                        {cur.windows.length > 0 && <span style={{ color: t.faint }}>·</span>}
                        <span>订阅至 {cur.exp}</span>
                        {cur.cards > 0 && (
                          <>
                            <span style={{ color: t.faint }}>·</span>
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: cur.cardDays != null && cur.cardDays <= CARD_WARN_DAYS ? "#f2b45c" : t.accent }}>
                              <IconTicket size={11} />重置卡 ×{cur.cards}
                              {cur.cardExp
                                ? (cur.cardsExpiring > 0 ? ` · ${cur.cardsExpiring} 张 ${cur.cardExp} 到期` : ` · 至 ${cur.cardExp}`)
                                : " · 到期未知"}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    {betterExists && hero ? (
                      <span onClick={() => run("switch-hero", ["switch", hero.node], `当前号 → ${hero.node}`)} style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 4, padding: "8px 14px", borderRadius: 9, fontSize: 11, fontWeight: 700, color: t.accentText, background: t.accent, flexShrink: 0, cursor: "pointer", userSelect: "none", opacity: loadingAction?.startsWith("switch") ? 0.6 : 1 }}>
                        <span style={{ fontSize: 10, opacity: 0.8 }}>建议切到 {hero.node}({hero.tightest}%)</span>
                        <span>{loadingAction?.startsWith("switch") ? "切换中…" : "切换 →"}</span>
                      </span>
                    ) : (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "10px 16px", borderRadius: 9, fontSize: 12.5, fontWeight: 700, color: t.accent, border: `1px solid ${t.accentBorder}`, background: t.accentSoft, flexShrink: 0 }}>✓ 额度最优</span>
                    )}
                  </div>
                );
              })()}

              {(() => {
                // Grid order is by LABEL, not by quota. The store sorts quota-desc, which made the
                // ⌘N hints (derived from label order) read 1,3,4,2 across the grid — the shortcut
                // numbers have to match reading order to be usable, and the handoff grid is label-
                // ordered too. The "which should I use" answer is the Hero + USE badge, not position.
                const alive = aliveByLabel;
                const dead = accounts.filter(a => a.status === "dead");
                // Delta baseline = best remaining quota among usable accounts.
                const bestPct = alive.reduce((m, a) => Math.max(m, a.windows[0]?.pct ?? -1), -1);
                return (
                  <div style={{ flex: 1, overflow: "auto" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, alignContent: "start" }}>
                      {alive.map((a) => {
                        const shortcutIdx = aliveByLabel.findIndex(x => x.aid === a.aid);
                        return (
                        <AccountCard key={a.aid} a={a} isCurrent={a.aid === currentNode} isBest={hero?.aid === a.aid} isSelected={selectedCard === a.aid} shortcut={shortcutIdx >= 0 && shortcutIdx < 9 ? shortcutIdx + 1 : undefined} bestPct={bestPct} probing={loadingAction === `probe-${a.aid}`} privacy={privacy} t={t}
                          onSelect={() => setSelectedCard(selectedCard === a.aid ? null : a.aid)}
                          onSwitch={() => run(`switch-${a.aid}`, ["switch", a.node], `当前号 → ${a.node}`)}
                          onShowDetail={(aid) => { invoke<AccountDetail>("read_account_detail", { aid }).then(d => setDetailModal(d)).catch(() => {}); }}
                          onRemove={(label) => run(`remove-${label}`, ["remove", label], `已删除 ${label}`)}
                          onProbe={(label) => run(`probe-${a.aid}`, ["probe", label], `探针 ${label}`)} />
                      );})}
                    </div>
                    {dead.length > 0 && (
                      <details style={{ marginTop: 12 }}>
                        <summary style={{ fontSize: 12, color: t.muted, cursor: "pointer", padding: "8px 14px", background: t.cardBg, borderRadius: 10, border: `1px solid ${t.cardBorder}`, userSelect: "none", display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#E0524D" }} />
                          {dead.length} 个失效账号
                        </summary>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: "8px 4px 0" }}>
                          {dead.map(a => (
                            <span key={a.aid} onClick={() => setSelectedCard(selectedCard === a.aid ? null : a.aid)}
                              style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 12px", background: t.cardBg, borderRadius: 8, fontSize: 11, cursor: "pointer", border: selectedCard === a.aid ? `1px solid ${t.accent}` : `1px solid ${t.cardBorder}`, opacity: 0.65 }}>
                              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#E0524D" }} />
                              {a.node} · {maskId(a.email.split("@")[0], privacy)}
                              {selectedCard === a.aid && (
                                <span onClick={(e) => { e.stopPropagation(); run(`remove-${a.node}`, ["remove", a.node], `已删除 ${a.node}`); }}
                                  style={{ fontSize: 10, color: "#E0524D", cursor: "pointer", marginLeft: 4 }}>删除</span>
                              )}
                            </span>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                );
              })()}
            </>
          )}

          {page === "tokens" && <TokensPage t={t} />}
          {page === "logs" && <LogsPage t={t} />}
          {page === "settings" && <SettingsPage t={t} />}
        </div>
      </div>

      {detailModal && <DetailModal detail={detailModal} privacy={privacy} t={t} onClose={() => setDetailModal(null)} />}
      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}
