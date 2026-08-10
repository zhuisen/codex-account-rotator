import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { open as openExternal } from "@tauri-apps/plugin-shell";
// ★ 版本号只从 tauri 运行期取,前端不再写死。此前"版本号同步 5 处"里有 3 处在前端,
//   发一次版要手改三个字符串,漏一个就显示错版本。现在只剩 tauri.conf.json + Cargo.toml 两处。
import logo from "../../src-tauri/icons/128x128@2x.png";
import { enable as enableAutostart, disable as disableAutostart, isEnabled as isAutostartEnabled } from "@tauri-apps/plugin-autostart";
import type { Theme } from "../theme";

interface Settings {
  autoSwitchEnabled: boolean;
  autoSwitchThreshold: number;
  subExpiryWarnDays: number;
  tokenExpiryWarnHours: number;
  dockVisible: boolean;
}

const DEFAULTS: Settings = {
  autoSwitchEnabled: false,
  autoSwitchThreshold: 15,
  subExpiryWarnDays: 7,
  tokenExpiryWarnHours: 48,
  dockVisible: false,        // 默认保持纯菜单栏形态(现有行为)
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

      <Row label="在程序坞显示" desc="开启后**主界面打开时**在 Dock 占一格,可 ⌘Tab 切换;关掉主界面立刻让出位置。即时生效,无需重启">
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
