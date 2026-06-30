import { useState } from "react";
import type { Theme } from "../theme";

interface Settings {
  autoSwitchEnabled: boolean;
  autoSwitchThreshold: number;
  subExpiryWarnDays: number;
  tokenExpiryWarnHours: number;
}

const DEFAULTS: Settings = {
  autoSwitchEnabled: true,
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

  const Row = ({ label, desc, children }: { label: string; desc: string; children: React.ReactNode }) => (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderBottom: `1px solid ${t.divider}` }}>
      <div><div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{label}</div><div style={{ fontSize: 10.5, color: t.muted, marginTop: 2 }}>{desc}</div></div>
      {children}
    </div>
  );

  const Toggle = ({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) => (
    <div onClick={() => onChange(!on)} style={{
      width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer",
      background: on ? t.accent : t.barTrack, transition: "background .2s",
    }}>
      <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: on ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
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

      <Row label="额度低自动切号" desc="当前号额度低于阈值时,自动切到更满的号">
        <Toggle on={s.autoSwitchEnabled} onChange={v => update({ autoSwitchEnabled: v })} />
      </Row>
      {s.autoSwitchEnabled && (
        <Row label="自动切号阈值" desc="当前号最吃紧额度低于此值(%)时触发">
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
          CodexBar v0.1.0<br />
          Tauri 2 + React · macOS<br />
          github.com/zhuisen/codex-account-rotator
        </div>
      </div>
    </div>
  );
}
