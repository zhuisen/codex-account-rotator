import { useState, useEffect, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { open as openExternal } from "@tauri-apps/plugin-shell";
// ★ 版本号只从 tauri 运行期取,前端不再写死。此前"版本号同步 5 处"里有 3 处在前端,
//   发一次版要手改三个字符串,漏一个就显示错版本。现在只剩 tauri.conf.json + Cargo.toml 两处。
import logo from "../../src-tauri/icons/128x128@2x.png";
import { enable as enableAutostart, disable as disableAutostart, isEnabled as isAutostartEnabled } from "@tauri-apps/plugin-autostart";
import type { Theme } from "../theme";
import Seg from "../components/Seg";
import { platformColor } from "../theme";
import { useCacheMode } from "../hooks/useCacheMode";
import { usePlatformPrefs } from "../hooks/usePlatformPrefs";
import type { TrafficData, PlatformPrefs } from "../traffic";
import { CACHE_MODES, cacheModeLabel, cacheModeDesc, orderedKeys, fmtTok } from "../traffic";

/** 菜单栏标题样式(用户 2026-08-12 从 demo 里三选一)。索引与 Rust 的 TRAY_STYLE 一一对应。 */
export const TRAY_STYLES = ["full", "mid", "min", "today"] as const;
export type TrayStyle = (typeof TRAY_STYLES)[number];
export const trayStyleLabel = (v: TrayStyle): string =>
  v === "full" ? "完整" : v === "mid" ? "简" : v === "min" ? "极简" : "今日";
/** 预览用的示例串。**和 Rust 的 `format_tray_title` 必须一致** —— 两处各写一份迟早分叉。 */
export const trayStyleSample = (v: TrayStyle): string => {
  return (v === "full" ? "pro1 周 67% ↻5d21h"
            : v === "mid" ? "pro1 67%"
            : v === "min" ? "67%"
            : "67% 🔹 1.29B");
};
export const trayStyleDesc = (v: TrayStyle): string =>
  v === "full" ? "标签 + 窗口 + 余量 + 重置倒计时。信息最全，也最宽（约 148px），菜单栏挤时最先被系统截掉。"
  : v === "mid" ? "标签 + 余量。知道是哪个号、还剩多少，但不占重置倒计时那段宽度。"
  : v === "min" ? "只有余量百分比，最窄（约 48px）。适合菜单栏很挤、只想扫一眼的场景。"
  : "余量 + 今日全平台 token。账号池与用量并到一行；今日数每几分钟变一次，宽度会小幅抖动。";

interface Settings {
  autoSwitchEnabled: boolean;
  autoSwitchThreshold: number;
  subExpiryWarnDays: number;
  tokenExpiryWarnHours: number;
  dockVisible: boolean;
  trayStyle: TrayStyle;
}

const DEFAULTS: Settings = {
  autoSwitchEnabled: false,
  autoSwitchThreshold: 15,
  subExpiryWarnDays: 7,
  tokenExpiryWarnHours: 48,
  dockVisible: false,        // 默认保持纯菜单栏形态(现有行为)
  trayStyle: "full",         // 默认沿用现状,不动老用户的菜单栏
};

const KEY = "codexbar_settings";

function load(): Settings {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return DEFAULTS; }
}
function save(s: Settings) { localStorage.setItem(KEY, JSON.stringify(s)); }

export function getSettings(): Settings { return load(); }

export default function SettingsPage({ t }: { t: Theme }) {
  const [s, setS] = useState(load);
  const update = (patch: Partial<Settings>) => {
    const next = { ...s, ...patch }; setS(next); save(next);
  };

  const { mode: cacheMode, setMode: setCacheMode } = useCacheMode();
  const [confirmQuit, setConfirmQuit] = useState(false);
  const [autostart, setAutostart] = useState(false);
  const [autostartBusy, setAutostartBusy] = useState(false);
  useEffect(() => { isAutostartEnabled().then(setAutostart).catch(() => {}); }, []);
  const toggleAutostart = async () => {
    if (autostartBusy) return;
    setAutostartBusy(true);
    try {
      if (autostart) { await disableAutostart(); setAutostart(false); }
      else { await enableAutostart(); setAutostart(true); }
    } catch (e) { console.error(e); }
    setAutostartBusy(false);
  };

  const Row = ({ label, desc, children }: { label: string; desc: string; children: React.ReactNode }) => (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderBottom: `1px solid ${t.divider}` }}>
      <div><div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{label}</div><div style={{ fontSize: 10.5, color: t.muted, marginTop: 2 }}>{desc}</div></div>
      {children}
    </div>
  );

  const NumInput = ({ value, onChange, min, max, suffix }: { value: number; onChange: (v: number) => void; min: number; max: number; suffix: string }) => (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <input type="range" min={min} max={max} value={value} onChange={e => onChange(Number(e.target.value))}
        style={{ width: 80, accentColor: t.accent }} />
      <span style={{ fontSize: 12, fontWeight: 600, color: t.accent, fontFamily: "'JetBrains Mono'", minWidth: 40 }}>{value}{suffix}</span>
    </div>
  );

  return (
    // ★ 外层内容区是 `overflow: hidden`(App.tsx),**每个页面自带滚动容器**是本项目的约定 ——
    //   总览和用量页都有,设置页原来漏了,于是窗口一矮下面的「关于」整块就被裁掉、没有滚动条
    //   (用户 2026-08-09 实测截图)。加页面时别忘这一条。
    <div style={{ display: "flex", flexDirection: "column", gap: 0,
                  minHeight: 0, height: "100%", overflowY: "auto",
                  // 滚动条压住右侧滑块/开关不好点,给一点右内边距
                  paddingRight: 4 }}>
      <span style={{ fontSize: 20, fontWeight: 700, marginBottom: 12, flexShrink: 0 }}>设置</span>

      <Row label="开机自启" desc="登录 macOS 时自动启动 CodexBar(后台常驻菜单栏)">
        <div onClick={toggleAutostart} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: autostartBusy ? "default" : "pointer",
          background: autostart ? t.accent : t.barTrack, transition: "background .2s", opacity: autostartBusy ? 0.6 : 1,
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: autostart ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>

      {/* desc 是纯文本、不过 markdown —— 写 `**x**` 会原样渲染成星号(2026-08-12 截图里抓到) */}
      <Row label="在程序坞显示" desc="开启后，主界面打开时在 Dock 占一格，可 ⌘Tab 切换；关掉主界面立刻让出位置。即时生效，无需重启">
        <div onClick={() => {
          const next = !s.dockVisible;
          update({ dockVisible: next });
          invoke("set_dock_visible", { on: next }).catch(() => {});
        }} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer",
          background: s.dockVisible ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: s.dockVisible ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>

      {/* ★ 菜单栏标题样式。Rust 侧存在 `TRAY_STYLE`(atomic),这里改完立刻调命令刷标题;
          启动时由 App.tsx 再应用一次 —— 否则重启后 Rust 回到默认 0,设置还显示着别的档。 */}
      <Row label="菜单栏标题" desc={trayStyleDesc(s.trayStyle)}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0, marginLeft: 12 }}>
          <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono'", color: t.text2,
                         background: t.isDark ? "#0e1319" : t.cardBg, whiteSpace: "nowrap",
                         border: `1px solid ${t.cardBorder}`, padding: "4px 9px", borderRadius: 7 }}>
            {trayStyleSample(s.trayStyle)}
          </span>
          <Seg opts={TRAY_STYLES} cur={s.trayStyle} label={trayStyleLabel} t={t}
               on={(v) => {
                 update({ trayStyle: v });
                 invoke("set_tray_style", { style: TRAY_STYLES.indexOf(v) }).catch(() => {});
               }} />
        </div>
      </Row>

      <PlatformSection t={t} />

      {/* ★ 缓存计入口径。**token 数与费用同时跟着变** —— 两者都由那四个互不相交的类算出来,
          只改一个会让「总费用」和「总 token」说的不是同一批数据。改动即时同步到菜单栏「今日」
          (走 Tauri 事件广播;两个 webview 的 localStorage 不互通)。 */}
      <Row label="缓存计入口径" desc={cacheModeDesc(cacheMode)}>
        {/* `Row` 是 space-between,右侧控件默认可被压缩。这一格是三档中文标签(比其余行的开关宽得多),
            窗口拉窄时会被左边那段说明文字挤到变形 —— 固定住它,让说明文字去换行。 */}
        <div style={{ flexShrink: 0, marginLeft: 12 }}>
          <Seg opts={CACHE_MODES} cur={cacheMode} on={setCacheMode} label={cacheModeLabel} t={t} />
        </div>
      </Row>

      <Row label="额度低自动切号" desc="当前号额度低于阈值时自动切到最佳号(默认关)">
        <div onClick={() => update({ autoSwitchEnabled: !s.autoSwitchEnabled })} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer",
          background: s.autoSwitchEnabled ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: s.autoSwitchEnabled ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>
      {s.autoSwitchEnabled && (
        <Row label="自动切号阈值" desc="当前号剩余额度低于此值(%)时触发">
          <NumInput value={s.autoSwitchThreshold} onChange={v => update({ autoSwitchThreshold: v })} min={5} max={50} suffix="%" />
        </Row>
      )}
      <Row label="订阅到期预警" desc="订阅剩余天数 ≤ 此值时在卡片和通知中提醒">
        <NumInput value={s.subExpiryWarnDays} onChange={v => update({ subExpiryWarnDays: v })} min={1} max={30} suffix="天" />
      </Row>
      <Row label="Token 过期预警" desc="access token 剩余小时 ≤ 此值时提醒">
        <NumInput value={s.tokenExpiryWarnHours} onChange={v => update({ tokenExpiryWarnHours: v })} min={6} max={120} suffix="h" />
      </Row>

      {/* The tray no longer carries a native menu (both mouse buttons open the popover instead), so
          this is the quit path. Confirm first — with the Dock icon off (the default) a stray click
          here would leave the menu bar empty with no obvious way back. */}
      <Row label="退出 CodexBar" desc="完全退出(菜单栏图标消失);仅关闭窗口用 ⌘W">
        {!confirmQuit ? (
          <span onClick={() => setConfirmQuit(true)} style={{ fontSize: 11.5, fontWeight: 600, color: "#E0524D", border: "1px solid #E0524D40", padding: "6px 13px", borderRadius: 8, cursor: "pointer", userSelect: "none" }}>退出</span>
        ) : (
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span onClick={() => invoke("quit_app").catch(() => {})} style={{ fontSize: 11.5, fontWeight: 700, color: "#fff", background: "#E0524D", padding: "6px 13px", borderRadius: 8, cursor: "pointer", userSelect: "none" }}>确认退出</span>
            <span onClick={() => setConfirmQuit(false)} style={{ fontSize: 11.5, color: t.muted, padding: "6px 10px", cursor: "pointer", userSelect: "none" }}>取消</span>
          </div>
        )}
      </Row>

      <About t={t} />
    </div>
  );
}

/**
 * AI 平台管理:改名 / 改色 / 停用 / 排序(用户 2026-08-12)。
 *
 * ★ **这里只管"怎么显示",管不了"有没有数据"**。能扫出哪几家由 `traffic/scan.py` 的注册表决定,
 *   新增一家 = 写一个 `_scan_*` 解析器 —— 实测四家四种 token 形状(还有 DeepSeek 这第五种),
 *   做成让用户填路径的表单等于让它去猜字段名,而那正是会静默算错数的做法。
 *
 * ★ **停用 = 整家从数据里移除,总 token / 总费用跟着扣**(用户定稿)。实现在 `useTraffic` 出口,
 *   不在这里 —— 下游 30+ 处自动跟上。这里只写偏好。
 *
 * ★ 排序**只影响列表与图例**。堆叠图层仍按占比降序("占大头的铺满基线比悬在半空清楚",
 *   2026-08-09 看了两版实物定的),这次没动它。
 *
 * 用 ↑↓ 而不是拖拽:四五行的列表,拖拽要处理 HTML5 DnD 的一堆边界,而本项目键盘可达性本来就是 0,
 * 再加一个只能用鼠标的交互没有收益。
 */
function PlatformSection({ t }: { t: Theme }) {
  const { prefs, setPrefs } = usePlatformPrefs();
  // 只读一次快照就够:这里要的是"有哪几家、各自多少量",不需要保鲜,也不该在设置页触发扫描。
  const [snap, setSnap] = useState<TrafficData | null>(null);
  useEffect(() => {
    invoke<string | null>("read_traffic_snapshot")
      .then((raw) => { if (raw) setSnap(JSON.parse(raw) as TrafficData); })
      .catch(() => { /* 没扫过就没有快照,列表回落到偏好里记过的键 */ });
  }, []);

  // ★ 列表必须**包含已停用的**,否则停用之后就再也找不到它、开不回来了。
  //   所以枚举 = 快照里的键 ∪ 偏好里记过的键。
  const keys = useMemo(() => {
    const all = new Set([...Object.keys(snap?.platforms ?? {}), ...Object.keys(prefs.by), ...prefs.order]);
    const vol = (k: string) =>
      Object.values(snap?.platforms[k]?.days ?? {}).reduce((s, b) => s + b.total, 0);
    return orderedKeys([...all], prefs, vol);
  }, [snap, prefs]);

  const patch = (k: string, v: Partial<PlatformPrefs["by"][string]>) =>
    setPrefs({ order: keys, by: { ...prefs.by, [k]: { ...prefs.by[k], ...v } } });

  const move = (i: number, d: -1 | 1) => {
    const next = [...keys];
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setPrefs({ ...prefs, order: next });
  };

  const dirty = prefs.order.length > 0 || Object.keys(prefs.by).length > 0;

  return (
    <div style={{ padding: "12px 0", borderBottom: `1px solid ${t.divider}` }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>AI 平台</div>
        <div style={{ fontSize: 10.5, color: t.muted, flex: 1 }}>
          改名 · 改色 · 停用 · 排序。停用的不计入总 token 与总费用；排序只影响列表与图例，
          堆叠图仍按占比大的贴基线。
        </div>
        {dirty && (
          <span onClick={() => setPrefs({ order: [], by: {} })}
                style={{ fontSize: 10.5, color: t.muted, cursor: "pointer", whiteSpace: "nowrap",
                         border: `1px solid ${t.ghostBorder}`, padding: "3px 9px", borderRadius: 7 }}>
            全部复位
          </span>
        )}
      </div>

      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        {keys.length === 0 && (
          <div style={{ fontSize: 11, color: t.faint }}>还没有扫描过，去「AI用量信息」页跑一次就会出现。</div>
        )}
        {keys.map((k, i) => {
          const p = snap?.platforms[k];
          const o = prefs.by[k] ?? {};
          const off = !!o.off;
          const color = o.color || p?.color || platformColor(k);
          const missing = !p;      // 偏好里有、快照里没有 ⇒ scan.py 已不再注册它
          return (
            <div key={k} style={{
              display: "flex", alignItems: "center", gap: 8, padding: "7px 9px", borderRadius: 9,
              background: t.isDark ? "#0e1319" : t.cardBg, border: `1px solid ${t.cardBorder}`,
              opacity: off ? 0.5 : 1, transition: "opacity .15s",
            }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                {([-1, 1] as const).map((d) => {
                  // 到头了就真的不可点:8px 的箭头本来就难瞄准,再让它"点了没反应"会以为坏了
                  const dead = d < 0 ? i === 0 : i === keys.length - 1;
                  return (
                    <span key={d} onClick={dead ? undefined : () => move(i, d)}
                          title={dead ? "" : d < 0 ? "上移" : "下移"}
                          style={{ fontSize: 10, lineHeight: 1, padding: "2px 5px", borderRadius: 4,
                                   cursor: dead ? "default" : "pointer", userSelect: "none",
                                   color: dead ? t.faint : t.muted,
                                   background: "transparent", transition: "background .12s" }}
                          onMouseEnter={(e) => { if (!dead) e.currentTarget.style.background = "rgba(255,255,255,.07)"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
                      {d < 0 ? "▲" : "▼"}
                    </span>
                  );
                })}
              </div>

              {/* 原生取色器:WKWebView 里可用,不必自己造一个色板 */}
              <input type="color" value={color} onChange={(e) => patch(k, { color: e.target.value })}
                     title={`${k} 的识别色（图表 / 图例 / 徽章共用）`}
                     style={{ width: 22, height: 22, padding: 0, border: "none", borderRadius: 6,
                              background: "transparent", cursor: "pointer", flexShrink: 0 }} />

              <input value={o.name ?? p?.name ?? k} onChange={(e) => patch(k, { name: e.target.value })}
                     placeholder={p?.name ?? k}
                     style={{ width: 108, fontSize: 12, fontFamily: "'JetBrains Mono'", color: t.text,
                              background: "transparent", border: `1px solid ${t.ghostBorder}`,
                              borderRadius: 6, padding: "3px 7px", outline: "none" }} />

              <span style={{ fontSize: 9.5, color: t.faint, fontFamily: "'JetBrains Mono'" }}>{k}</span>

              {missing && (
                <span title="偏好里还留着它，但当前扫描结果里没有这一家（scan.py 未注册或该 CLI 未安装）"
                      style={{ fontSize: 9, fontWeight: 700, color: "#E0901C" }}>无数据</span>
              )}

              <span style={{ marginLeft: "auto", fontSize: 10, color: t.muted,
                             fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap" }}>
                {p ? fmtTok(Object.values(p.days).reduce((s, b) => s + b.total, 0)) : "—"}
              </span>

              <div onClick={() => patch(k, { off: !off })}
                   title={off ? "启用：重新计入总量与图表" : "停用：从图表与总量中完全移除（可随时开回来）"}
                   style={{ width: 34, height: 20, borderRadius: 10, padding: 2, cursor: "pointer",
                            background: off ? t.barTrack : t.accent, transition: "background .2s", flexShrink: 0 }}>
                <div style={{ width: 16, height: 16, borderRadius: 8, background: "#fff",
                              transform: off ? "translateX(0)" : "translateX(14px)", transition: "transform .2s" }} />
              </div>
            </div>
          );
        })}
      </div>

      <DiscoverPanel t={t} />

      <div style={{ fontSize: 10, color: t.faint, marginTop: 9, lineHeight: 1.6 }}>
        ⚠️ <b>新增一家平台不在这里</b>。能扫出哪几家由 <code>traffic/scan.py</code> 的注册表决定——
        加一家等于写一个解析器（实测四家四种 token 形状，DeepSeek 还是第五种），
        做成填路径的表单就只能去猜字段名，那正是会静默算错数的做法。
      </div>
    </div>
  );
}

/**
 * 「扫描新数据源」。产出**体检报告**,不自动启用任何东西。
 *
 * ★ 为什么不能一键启用:接一家的实质是写解析器。这个扫描能自动测出的只有「口径」
 *   (哪些字段加起来恒等于 total ⇒ 缓存要不要减),而**测不出去重规则** ——
 *   OpenClaw 那次朴素求和虚高 4.08x,靠的是找到 `responseId` 才消掉的,那一步没法自动。
 *   所以判定干净也只代表"值得写",不代表"可以直接用"。
 *
 * 判定状态四档,颜色对应:ok 青 / ambiguous 琥珀 / reject 红 / unknown 灰。
 * **判不了是常态**(四家里三家判不了),这不是失败,是它唯一的安全性来源。
 */
function DiscoverPanel({ t }: { t: Theme }) {
  type Cand = {
    root: string; known: boolean; files: number; records: number;
    verdict: string; state: "ok" | "ambiguous" | "reject" | "unknown";
    models: { model: string; total: number }[];
  };
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ candidates: Cand[]; roots: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      setRes(JSON.parse(await invoke<string>("run_discover")));
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    } finally {
      setBusy(false);
    }
  };

  const COLOR: Record<Cand["state"], string> = {
    ok: t.accent, ambiguous: "#E0901C", reject: "#E0524D", unknown: t.muted,
  };

  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${t.divider}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span onClick={() => { void run(); }}
              title="遍历本机候选目录,找还有哪些地方存着 AI token 用量。只读本地文件,不联网、不碰凭证"
              style={{ fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap",
                       color: busy ? t.muted : t.accentText,
                       background: busy ? t.barTrack : t.accent,
                       padding: "6px 13px", borderRadius: 8,
                       cursor: busy ? "default" : "pointer", userSelect: "none" }}>
          {busy ? "扫描中…（约 40 秒）" : "扫描新数据源"}
        </span>
        <span style={{ fontSize: 10, color: t.faint, lineHeight: 1.5 }}>
          找本机还有哪些 AI 把用量落了盘，并<b>实测</b>它的口径（哪些字段加起来等于 total ⇒ 缓存要不要减）。
          只出报告，不会自动启用。
        </span>
      </div>

      {err && <div style={{ fontSize: 10.5, color: "#E0524D", marginTop: 8,
                            fontFamily: "'JetBrains Mono'" }}>✗ {err}</div>}

      {res && (
        <div style={{ marginTop: 9, display: "flex", flexDirection: "column", gap: 5 }}>
          <div style={{ fontSize: 10, color: t.faint }}>
            扫了 {res.roots} 个候选目录，{res.candidates.length} 个含 token 用量记录
          </div>
          {res.candidates.map((c) => (
            <div key={c.root} style={{ padding: "7px 10px", borderRadius: 8,
                                       background: t.isDark ? "#0e1319" : t.cardBg,
                                       border: `1px solid ${t.cardBorder}` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 8.5, fontWeight: 700, padding: "2px 6px", borderRadius: 5,
                               color: c.known ? t.muted : t.accentText,
                               background: c.known ? t.ghostBg : t.accent }}>
                  {c.known ? "已注册" : "新发现"}
                </span>
                <span style={{ fontSize: 11.5, fontFamily: "'JetBrains Mono'", color: t.text }}>{c.root}</span>
                <span style={{ marginLeft: "auto", fontSize: 9.5, color: t.faint,
                               fontFamily: "'JetBrains Mono'" }}>
                  {c.files} 文件 · {c.records} 条
                </span>
              </div>
              <div style={{ fontSize: 10, color: COLOR[c.state], marginTop: 4, lineHeight: 1.5 }}>
                {c.verdict}
              </div>
              {c.models.length > 0 && (
                <div style={{ fontSize: 9.5, color: t.muted, marginTop: 3,
                              fontFamily: "'JetBrains Mono'" }}>
                  {c.models.slice(0, 6).map((m) => `${m.model} ${fmtTok(m.total)}`).join(" · ")}
                </div>
              )}
            </div>
          ))}
          <div style={{ fontSize: 9.5, color: t.faint, lineHeight: 1.6, marginTop: 2 }}>
            判定干净（青色）只说明<b>值得接</b>，不等于能直接用：这个扫描测得出口径，
            <b>测不出去重规则</b>。OpenClaw 那次朴素求和虚高 4.08x，是靠找到 <code>responseId</code> 才消掉的。
          </div>
        </div>
      )}
    </div>
  );
}

const REPO = "zhuisen/codex-account-rotator";
const REPO_URL = `https://github.com/${REPO}`;

/** 语义化版本比较。**不能按字符串比** —— 那样 0.10.0 会被判成小于 0.9.0。 */
function isNewer(remote: string, current: string): boolean {
  const parse = (v: string) => v.replace(/^v/, "").split(".").map((x) => parseInt(x, 10) || 0);
  const [a, b, c] = parse(remote), [x, y, z] = parse(current);
  return a !== x ? a > x : b !== y ? b > y : c > z;
}

type UpdateState =
  | { k: "idle" }
  | { k: "busy" }
  | { k: "latest"; v: string }
  | { k: "new"; v: string }
  | { k: "err"; msg: string };

function About({ t }: { t: Theme }) {
  const [ver, setVer] = useState("");
  const [up, setUp] = useState<UpdateState>({ k: "idle" });
  useEffect(() => { getVersion().then(setVer).catch(() => setVer("?")); }, []);

  const check = async () => {
    if (up.k === "busy") return;
    setUp({ k: "busy" });
    try {
      const tag = await invoke<string>("check_update");
      setUp(isNewer(tag, ver) ? { k: "new", v: tag } : { k: "latest", v: tag });
    } catch (e: unknown) {
      setUp({ k: "err", msg: String(e).slice(0, 120) });
    }
  };

  const link: React.CSSProperties = {
    color: t.accent, cursor: "pointer", textDecoration: "none",
    borderBottom: `1px solid ${t.accent}44`,
  };

  return (
    <div style={{ marginTop: 22, paddingTop: 16, borderTop: `1px solid ${t.divider}` }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: t.muted, marginBottom: 12 }}>关于</div>
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <img src={logo} width={64} height={64} alt="CodexBar"
             style={{ borderRadius: 14, flexShrink: 0,
                      boxShadow: "0 4px 16px rgba(0,0,0,.35)" }} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 9 }}>
            <span style={{ fontSize: 19, fontWeight: 700 }}>CodexBar</span>
            <span style={{ fontSize: 12.5, fontWeight: 700, color: t.accent,
                           fontFamily: "'JetBrains Mono'" }}>{ver ? `v${ver}` : "…"}</span>
          </div>
          <div style={{ fontSize: 11, color: t.faint, marginTop: 3,
                        fontFamily: "'JetBrains Mono'" }}>
            Tauri 2 + React · macOS
          </div>
          {/* 外链走 shell 插件在系统浏览器打开;webview 里直接导航会把整个 app 变成网页 */}
          <div style={{ fontSize: 11, marginTop: 7, fontFamily: "'JetBrains Mono'" }}>
            <span style={link} onClick={() => { void openExternal(REPO_URL); }}
                  title="在浏览器打开">github.com/{REPO} ↗</span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12,
                        flexWrap: "wrap" }}>
            <span onClick={() => { void check(); }}
                  title="向远端查最新 tag(私有仓库走 git 凭证)。这是本页唯一联网的动作"
                  style={{ fontSize: 11.5, fontWeight: 600,
                           color: up.k === "busy" ? t.muted : t.accentText,
                           background: up.k === "busy" ? t.barTrack : t.accent,
                           padding: "6px 13px", borderRadius: 8,
                           cursor: up.k === "busy" ? "default" : "pointer", userSelect: "none",
                           transition: "background .15s" }}>
              {up.k === "busy" ? "检查中…" : "检查更新"}
            </span>
            {up.k === "latest" && (
              <span style={{ fontSize: 11, color: "#27B26B", fontFamily: "'JetBrains Mono'" }}>
                ✓ 已是最新（远端 {up.v}）
              </span>
            )}
            {up.k === "new" && (
              <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono'" }}>
                <span style={{ color: "#E0A21C", fontWeight: 700 }}>有新版 {up.v}</span>{" "}
                <span style={link} onClick={() => { void openExternal(`${REPO_URL}/releases`); }}>
                  查看更新说明 ↗
                </span>
                <span style={{ color: t.faint }}>　·　更新：<code>git pull && bash codexbar/scripts/deploy.sh</code></span>
              </span>
            )}
            {up.k === "err" && (
              <span style={{ fontSize: 10.5, color: "#E0524D", fontFamily: "'JetBrains Mono'" }}>
                ✗ {up.msg}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
