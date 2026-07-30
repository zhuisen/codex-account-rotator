import { useState, useEffect } from "react";
import { enable as enableAutostart, disable as disableAutostart, isEnabled as isAutostartEnabled } from "@tauri-apps/plugin-autostart";
import type { Theme } from "../theme";

interface Settings {
  autoSwitchEnabled: boolean;
  autoSwitchThreshold: number;
  subExpiryWarnDays: number;
  tokenExpiryWarnHours: number;
}

const DEFAULTS: Settings = {
  autoSwitchEnabled: false,
  autoSwitchThreshold: 15,
  subExpiryWarnDays: 7,
  tokenExpiryWarnHours: 48,
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
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <span style={{ fontSize: 20, fontWeight: 700, marginBottom: 12 }}>设置</span>

      <Row label="开机自启" desc="登录 macOS 时自动启动 CodexBar(后台常驻菜单栏)">
        <div onClick={toggleAutostart} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: autostartBusy ? "default" : "pointer",
          background: autostart ? t.accent : t.barTrack, transition: "background .2s", opacity: autostartBusy ? 0.6 : 1,
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: autostart ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
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

      <div style={{ marginTop: 20, padding: "12px 0", borderTop: `1px solid ${t.divider}` }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: t.muted, marginBottom: 6 }}>关于</div>
        <div style={{ fontSize: 11, color: t.faint, fontFamily: "'JetBrains Mono'", lineHeight: 1.8 }}>
          CodexBar v0.4.3<br />
          Tauri 2 + React · macOS<br />
          github.com/zhuisen/codex-account-rotator
        </div>
      </div>
    </div>
  );
}
