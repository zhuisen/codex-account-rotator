import { useState, useMemo, useEffect } from "react";
import { getVersion } from "@tauri-apps/api/app";
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
import TrafficPage from "./pages/TrafficPage";
import PlatformPage from "./pages/PlatformPage";
import type { Range } from "./traffic";
import { colorOf } from "./traffic";
import SettingsPage, { getSettings, patchSettings, TRAY_STYLES } from "./pages/SettingsPage";
import { useStore } from "./hooks/useStore";
import { useExpiryWatch } from "./hooks/useExpiryWatch";
import { useDeadWatch } from "./hooks/useDeadWatch";
import { useAutoSwitch } from "./hooks/useAutoSwitch";
import { useKeyboard } from "./hooks/useKeyboard";
import { fmtAgo, CARD_WARN_DAYS, maskId } from "./helpers";
import { usePrivacy } from "./hooks/usePrivacy";
import { useTraffic } from "./hooks/useTraffic";
import { useGrokQuota } from "./hooks/useGrokQuota";
import GrokCard from "./components/GrokCard";
import { IconTicket } from "./components/CardBadge";
import ProbeButton from "./components/ProbeButton";
import PlanBadge from "./components/PlanBadge";
import "./App.css";

// 平台详情页不进导航栏,只能从流量总览钻取(图例行 / 卡片「明细→」/ 点图层),用户定稿 2026-08-09。
type Page = "overview" | "traffic" | "logs" | "settings";

const IconChart = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="12" width="4" height="9" rx="1"/><rect x="10" y="7" width="4" height="14" rx="1"/><rect x="17" y="3" width="4" height="18" rx="1"/></svg>;
// 流量总览 = 四宫格(交接稿 §0)
const IconGrid = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="8" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/><rect x="13" y="13" width="8" height="8" rx="2"/></svg>;
const IconClip = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3.5h6v3H9z" fill="currentColor" stroke="none"/></svg>;
// ★ 真齿轮(带齿廓),不是 circle+8 条直射线 —— 那个画出来和标题栏的 `IconSun` 几乎同一个图形,
//   侧栏第 4 格看着像"亮度"而不是"设置"(用户 2026-08-09 实测截图)。
/** 侧栏折叠/展开。双人字形指向「往哪边收」——比单箭头更明确它是个开关而不是"下一页"。 */
const IconChevrons = ({ open }: { open: boolean }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round"
       style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .18s ease" }}>
    <path d="M13 17l5-5-5-5M6 17l5-5-5-5" />
  </svg>
);

const IconGear = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);
const IconRefresh = ({ spin }: { spin?: boolean }) => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ animation: spin ? "cbSpin .7s linear" : "none", transformOrigin: "center" }}><path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4"/></svg>;
const IconSun = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9 17.7 6.3M6.3 17.7 4.9 19.1"/></svg>;
const IconEye = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><path d="M1.6 12S5.3 5.5 12 5.5 22.4 12 22.4 12 18.7 18.5 12 18.5 1.6 12 1.6 12z"/><circle cx="12" cy="12" r="3"/></svg>;
const IconEyeOff = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><path d="M9.9 5.8A9.6 9.6 0 0 1 12 5.5c6.7 0 10.4 6.5 10.4 6.5a18 18 0 0 1-3.4 4.2M6.2 7.8A18 18 0 0 0 1.6 12S5.3 18.5 12 18.5c1.6 0 3-.4 4.3-.9M3 3l18 18"/></svg>;
const IconMoon = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>;

export default function App() {
  const { accounts, hero, currentNode, slots, counts, tokens, lastRefreshAt, loadingAction, toast, refresh, run, showToast } = useStore();
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  // 版本号运行期从 tauri 取,别再写死(发版时漏改前端字符串是老毛病)
  const [ver, setVer] = useState("");
  useEffect(() => { getVersion().then(setVer).catch(() => {}); }, []);
  const [page, setPage] = useState<Page>("overview");
  const [trafficRange, setTrafficRange] = useState<Range>(14);
  const [drill, setDrill] = useState<string | null>(null);   // 平台详情:null = 停在总览
  const [detailModal, setDetailModal] = useState<AccountDetail | null>(null);
  const [selectedCard, setSelectedCard] = useState<string | null>(null);
  const [autoSwitch, setAutoSwitch] = useState(() => getSettings().autoSwitchEnabled);
  // 侧栏折叠态。**默认折叠**（DEFAULTS.navOpen = false），选择会记住 —— 每次启动都弹回默认的开关很烦人。
  const [navOpen, setNavOpen] = useState(() => getSettings().navOpen);

  /**
   * ★★ **窄窗自动折叠侧栏**（用户 2026-08-24 定稿：「尺寸小到一定程度后，需要折叠起侧边栏」）。
   *
   * 侧栏展开 176px / 折叠 52px，差 **124px** —— 正好是三列九宫格在窄窗下缺的那一点。
   * 实测（`uishot/sweep.py`，账号卡自然宽 637）：
   *   · 展开：**≥860 干净**，840 起单张卡溢出
   *   · 折叠：**≥740 干净**，720 起溢出
   * 差值 120px 与侧栏宽度差吻合，所以阈值取展开态的下限 860，窗口下限取折叠态的 740。
   * 两个数**必须一起改**，闸在 `tests/test_narrow_window_nowrap.py`。
   *
   * ★ **这是显示层的临时覆盖，不改用户偏好**。变窄时只 `setNavOpen(false)`、**不写
   * localStorage**；变宽时从偏好里读回来。否则用户拖窄一次，"侧栏默认展开"这个设置就被
   * 永久抹掉了 —— 那是拿一次布局意外去改一条长期偏好。
   * ★ 窄窗下用户仍可手动展开（那条路径照旧写偏好），一直保持到下次跨过阈值。
   *
   * ★ 为什么不做等比缩放：试过 `zoom`，**在 WKWebView 里语义与 Chrome 不同**，
   * 真机上把版面撑爆（用户 2026-08-24 截图），而 harness 跑的是 Chrome、全程报"干净"——
   * 用错引擎验证得到的假绿。折叠侧栏是纯 React 状态，两个引擎行为一致。
   */
  useEffect(() => {
    const NARROW_W = 860;
    let narrow = window.innerWidth < NARROW_W;
    if (narrow) setNavOpen(false);
    const onResize = () => {
      const now = window.innerWidth < NARROW_W;
      if (now === narrow) return;            // 只在**跨过阈值**时动作,不是每次 resize 都覆盖
      narrow = now;
      setNavOpen(now ? false : getSettings().navOpen);
    };
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); };
  }, []);
  const { privacy, toggle: togglePrivacy } = usePrivacy();

  const t = THEMES[theme];
  const win = useMemo(() => getCurrentWindow(), []);
  const summary = `${counts.total} nodes · ${counts.live} 活 · ${counts.cool} 冷 · ${counts.dead} 死`;

  // ★ Dock 显示开关在 localStorage,Rust 侧读不到 —— 每次启动由主窗口 webview 应用一次,
  //   否则重启后 Dock 图标会消失(设置还开着,行为却回到纯菜单栏)。
  useEffect(() => {
    const st = getSettings();
    invoke("set_dock_visible", { on: st.dockVisible }).catch(() => {});
    // 菜单栏标题样式同理:Rust 侧的 TRAY_STYLE 是进程内 atomic,重启就回默认,
    // 得由主窗口 webview 每次启动重新告诉它一次。
    invoke("set_tray_style", { style: TRAY_STYLES.indexOf(st.trayStyle) }).catch(() => {});
  }, []);

  // menubar → 主窗口的三个跳转入口。齿轮=设置;今日 Tab 底栏=流量总览;点平台图例行=该平台详情。
  useEffect(() => {
    const uns = [
      listen("navigate-settings", () => { setPage("settings"); void invoke("set_main_visible", { show: true }); }),
      listen("navigate-traffic", () => { setDrill(null); setPage("traffic"); void invoke("set_main_visible", { show: true }); }),
      listen<string>("navigate-platform", (e) => {
        setDrill(e.payload); setPage("traffic"); void invoke("set_main_visible", { show: true });
      }),
    ];
    return () => { uns.forEach((u) => { void u.then((f) => f()); }); };
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

  // ★ 一次取满最大窗口(90d),换档位纯前端切片。scan.py 内部恒扫 max(days,90),所以五个档位的
  //   底层数据本就一样;每换一档重调一次 IPC 等于白付一次全量扫描。
  //   进页面才取,不在启动时取 —— 账号池才是启动要的东西。
  //   取数走 `useTraffic`:先画上次的快照(一次文件读),再后台重扫,所以进页面不再有那 1~4 秒白屏。
  const { data: traffic, raw: trafficRaw, cacheMode, prefs: platPrefs, busy: trafficBusy,
          err: trafficErr, refresh: refreshTraffic } = useTraffic({ enabled: page === "traffic" });
  /**
   * ★ 这是全 app 唯一一条会**主动联网**的数据路径(`useTraffic` 扫的是本机盘,零消耗不联网),
   *   所以 `enabled` 是白名单不是黑名单:**只有这两个页面**要看 grok 额度。
   *   **只有总览**(用户 2026-08-24 两次定稿:先要「号的额度在上面」,后要「grok 的用量
   *   不要放在 AI 用量信息里,放在总览里就好」)。用量页、日志页、设置页一律不触发 ——
   *   那一页整页都是"本机盘扫出来的 token 消耗",而 grok 额度是云端账单,本来就不同源。
   *
   *   频次仍有四道闸:sidecar 新鲜度 10min · `visibilityState` 门(窗口隐藏时零请求) ·
   *   Rust 侧 `GROK_COALESCE_SECS=300` 双检 · 设置页「后台自动刷新」总开关。
   *   ⚠️ 已知取舍:总览是默认页,所以**每次启动 app 会打一次**(token 已过期时连请求都不发,
   *   本地短路)。这个端点不计费、不消耗额度,换来的是打开窗口时数字已经在那儿。
   */
  const { snap: grokSnap, busy: grokBusy, err: grokErr, refresh: refreshGrok } =
    useGrokQuota({ enabled: page === "overview" });

  // ★ `name` 是展开态显示的中文名，`tip` 只在**折叠态**当悬浮提示 —— 展开后标签已经在那儿，
  //   再挂一个 title 是重复。原来 traffic 的 tip 写死「Claude / Codex / Grok」三家，
  //   而现在有 6 个平台，顺手改掉。
  const sidebarItems: { id: Page; Icon: React.FC; name: string; tip: string }[] = [
    { id: "overview", Icon: IconChart, name: "总览", tip: "总览" },
    { id: "traffic", Icon: IconGrid, name: "AI用量信息", tip: "AI用量信息（各 AI CLI 的本机用量）" },
    { id: "logs", Icon: IconClip, name: "日志", tip: "日志" },
    { id: "settings", Icon: IconGear, name: "设置", tip: "设置" },
  ];

  return (
    // ★ `cb-light` 供 App.css 的滚动条规则按主题反色 —— 白色拇指在浅色底上等于隐形。
    //   加这个 class 之前那条规则是**死规则**(写完顺手核了一下才发现根节点没有它)。
    <div className={theme === "light" ? "cb-light" : undefined}
         style={{ width: "100vw", height: "100vh", display: "flex", flexDirection: "column", background: t.appBg, color: t.text, fontFamily: "'Space Grotesk'", borderRadius: 12, overflow: "hidden", boxShadow: t.shadow, transition: "background-color .35s ease, color .35s ease" }}>

      {/* Title bar */}
      <div data-tauri-drag-region style={{ height: 38, flexShrink: 0, display: "flex", alignItems: "center", padding: "0 14px", gap: 8, borderBottom: `1px solid ${t.chromeBorder}`, background: t.chromeBg, position: "relative", transition: "background-color .35s ease" }}>
        <span onClick={() => { invoke("set_main_visible", { show: false }).catch(() => {}); }} style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57", cursor: "pointer" }} title="隐藏" />
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
          <span style={{ fontSize: 11, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{ver ? `v${ver}` : ""}</span>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Sidebar */}
        {/* ★ 侧栏可折叠（用户 2026-08-16）。**默认折叠**，展开后每项带中文名。
            宽度过渡 .18s；`prefers-reduced-motion` 下不过渡（媒体查询在 App.css 的 .cb-rail）。
            展开态用 `alignItems: stretch` 让每项占满宽度 —— 图标居中、文字左对齐的行
            如果宽度只包住内容，点击热区会缩到文字上，"点空白没反应"就是这么来的。 */}
        <div className="cb-rail" style={{ width: navOpen ? 176 : 52, flexShrink: 0, borderRight: `1px solid ${t.railBorder}`, background: t.railBg, display: "flex", flexDirection: "column", alignItems: navOpen ? "stretch" : "center", padding: navOpen ? "14px 8px" : "14px 0", gap: 4, overflow: "hidden", transition: "width .18s ease, background-color .35s ease" }}>
          {sidebarItems.map((it) => (
            <div key={it.id} onClick={() => setPage(it.id)}
                 title={navOpen ? undefined : it.tip}
                 style={{ height: 34, width: navOpen ? "100%" : 34, borderRadius: 9,
                          display: "flex", alignItems: "center",
                          justifyContent: navOpen ? "flex-start" : "center",
                          gap: 10, padding: navOpen ? "0 10px" : 0, flexShrink: 0,
                          cursor: "pointer", color: page === it.id ? t.accentText : t.muted,
                          background: page === it.id ? t.accent : "transparent",
                          transition: "background .2s, color .2s" }}>
              <span style={{ display: "grid", placeItems: "center", flexShrink: 0 }}><it.Icon /></span>
              {navOpen && (
                <span style={{ fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap" }}>{it.name}</span>
              )}
            </div>
          ))}
            {/* 折叠开关钉在底部：它是外壳控件，不该混进上面那组「去哪一页」里。
                折叠态下和导航项一样是 34×34 居中，避免出现第二种尺寸。 */}
            <div onClick={() => { const n = !navOpen; setNavOpen(n); patchSettings({ navOpen: n }); }}
                 title={navOpen ? "折叠侧栏" : "展开侧栏"}
                 style={{ marginTop: "auto", height: 34, width: navOpen ? "100%" : 34,
                          borderRadius: 9, display: "flex", alignItems: "center",
                          justifyContent: navOpen ? "flex-start" : "center",
                          gap: 10, padding: navOpen ? "0 10px" : 0, flexShrink: 0,
                          cursor: "pointer", color: t.muted, transition: "color .2s" }}>
              <span style={{ display: "grid", placeItems: "center", flexShrink: 0 }}>
                <IconChevrons open={navOpen} />
              </span>
              {navOpen && <span style={{ fontSize: 11.5, whiteSpace: "nowrap" }}>折叠</span>}
            </div>
            <span style={{ fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'",
                           textAlign: navOpen ? "left" : "center", paddingLeft: navOpen ? 10 : 0,
                           marginTop: 6, flexShrink: 0 }}>{ver ? ver.split(".").slice(0, 2).join(".") : ""}</span>
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0, padding: "16px 20px", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {page === "overview" && (
            <>
              {/* ★ `flexWrap` + `rowGap`:空间不够时**整块**换行,而不是把里面的按钮压扁。
                  断字是 bug(见 GhostButton/ProbeButton 的 nowrap),换行只是变高、零信息损失。 */}
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between",
                            marginBottom: 12, flexWrap: "wrap", rowGap: 8, columnGap: 12 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, minWidth: 0 }}>
                  {/* ★ 标题**永不断字**。窄窗下曾被劈成「总 / 览」(用户 2026-08-24 截图)。 */}
                  <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-.01em",
                                 whiteSpace: "nowrap", flexShrink: 0 }}>总览</span>
                  {/* ★ 这行摘要是**第一个该让位**的:窄窗下它的信息价值最低(下面每张卡都写着状态),
                      所以给 `minWidth:0` + 省略号,让它先缩,把空间让给按钮。 */}
                  <span style={{ fontSize: 11.5, color: t.muted, fontFamily: "'JetBrains Mono'",
                                 whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                                 minWidth: 0 }}>{summary}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
                <div style={{ display: "flex", gap: 7, alignItems: "center",
                              flexWrap: "wrap", justifyContent: "flex-end", rowGap: 7 }}>
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
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: autoSwitch ? t.accent : t.muted, animation: autoSwitch ? "cbDotPulse 2s ease-in-out infinite" : "none" }} />
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
                        <span style={{ fontSize: 12, color: t.text2, fontFamily: "'JetBrains Mono'" }}>{maskId(cur.email, privacy)}</span>
                      </div>
                      {/* ★ **每一段 nowrap、段与段之间才允许换行。**
                          窄窗实测(760px)曾把日期劈成「订阅至 2026- / 09-08」、「至 2026- / 09-21」——
                          **断开的日期比断开的按钮更糟**:它会被读成另一个日期,而不是"看起来挤"。
                          与 GhostButton/ProbeButton 的 nowrap 是同一个病根(用户 2026-08-24 报的头部
                          断字只是它的第一处),所以同批一起修,别只补被点名的那一处。 */}
                      <div style={{ display: "flex", alignItems: "center", gap: 13, marginTop: 8, fontSize: 12, color: t.text2, fontFamily: "'JetBrains Mono'", flexWrap: "wrap", rowGap: 6 }}>
                        {cur.windows.map((w, i) => (
                          <span key={w.label} style={{ whiteSpace: "nowrap" }}>{i > 0 && <span style={{ color: t.muted, marginRight: 13 }}>·</span>}{w.label} <b style={{ color: sc }}>{w.pct}%</b> <span style={{ color: t.muted }}>↻{w.reset}</span></span>
                        ))}
                        {cur.windows.length > 0 && <span style={{ color: t.muted }}>·</span>}
                        <span style={{ whiteSpace: "nowrap" }} title={cur.expStale ? "OpenAI 上次复核订阅早于这个日期,所以「已过期」是拿陈旧快照下的结论 —— 续费不在它视野里。刷新 token 也拉不到新状态,要等 OpenAI 自己复核。" : undefined}>订阅至 {cur.exp}{cur.expStale && <span style={{ color: "#E0901C" }}>*</span>}</span>
                        {cur.cards > 0 && (
                          <>
                            <span style={{ color: t.muted }}>·</span>
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 5, whiteSpace: "nowrap", color: cur.cardDays != null && cur.cardDays <= CARD_WARN_DAYS ? "#f2b45c" : t.accent }}>
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
                        // 改名按 aid 不按 label:cmd_rename 两者都认,而 aid 唯一 —— 重名时不会改到别的号上
                        return (
                        <AccountCard key={a.aid} a={a} isCurrent={a.aid === currentNode} isBest={hero?.aid === a.aid} isSelected={selectedCard === a.aid} shortcut={shortcutIdx >= 0 && shortcutIdx < 9 ? shortcutIdx + 1 : undefined} bestPct={bestPct} probing={loadingAction === `probe-${a.aid}`} privacy={privacy} t={t}
                          onSelect={() => setSelectedCard(selectedCard === a.aid ? null : a.aid)}
                          onSwitch={() => run(`switch-${a.aid}`, ["switch", a.node], `当前号 → ${a.node}`)}
                          onShowDetail={(aid) => { invoke<AccountDetail>("read_account_detail", { aid }).then(d => setDetailModal(d)).catch(() => {}); }}
                          onRemove={(label) => run(`remove-${label}`, ["remove", label], `已删除 ${label}`)}
                          onProbe={(label) => run(`probe-${a.aid}`, ["probe", label], `探针 ${label}`)}
                          onRename={(next) => run(`rename-${a.aid}`, ["rename", a.aid, next], `${a.node} → ${next}`)} />
                      );})}
                      {/* ★ grok 卡。**渲染在格子里,但绝不进 `alive` 数组** —— 那个数组同时驱动
                          ⌘1~⌘9 切号(`aliveByLabel[idx]` 直接 switch)、计数徽章、探针全池的号数、
                          自动切号。混进去 ⌘4 会"切"到一个切不了的东西上,而且不报错。
                          闸在 tests/test_grok_not_in_pool_ui.py。 */}
                      <GrokCard t={t} color={colorOf(traffic, "grok")} snap={grokSnap}
                                disabled={!!platPrefs.by?.grok?.off}
                                privacy={privacy} busy={grokBusy} err={grokErr}
                                onRefresh={refreshGrok}
                                onOpen={() => { setDrill("grok"); setPage("traffic"); }} />
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

          {page === "traffic" && (drill
            ? <PlatformPage t={t} data={traffic} raw={trafficRaw} cacheMode={cacheMode}
                            pk={drill} range={trafficRange}
                            setRange={setTrafficRange} onBack={() => setDrill(null)} busy={trafficBusy} />
            : <TrafficPage t={t} data={traffic} raw={trafficRaw} cacheMode={cacheMode} prefs={platPrefs}
                           range={trafficRange} setRange={setTrafficRange}
                           onDrill={setDrill} busy={trafficBusy} err={trafficErr}
                           onRefresh={refreshTraffic} />)}
          {page === "logs" && <LogsPage t={t} />}
          {page === "settings" && <SettingsPage t={t} />}
        </div>
      </div>

      {detailModal && <DetailModal detail={detailModal} privacy={privacy} t={t} onClose={() => setDetailModal(null)} />}
      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}
