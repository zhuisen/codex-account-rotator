import { STATUS_COLORS, STATUS_TEXT, type Theme } from "../theme";
import type { Account } from "../helpers";
import Ring from "./Ring";

export default function AccountRow({ a, isCurrent, isBest, t, onSelect }: {
  a: Account; isCurrent: boolean; isBest: boolean; t: Theme; onSelect: () => void;
}) {
  const sc = STATUS_COLORS[a.status] ?? STATUS_COLORS.live;
  const isDead = a.status === "dead";
  const mainPct = a.windows[0]?.pct ?? -1;
  const glowColor = mainPct >= 0 && mainPct <= 10 && !isDead ? "#E0524D" : mainPct >= 0 && mainPct <= 20 && !isDead ? "#E0901C" : undefined;

  return (
    <div className="mb-row" onClick={onSelect} style={{
      background: `linear-gradient(90deg, ${isDead ? "rgba(224,82,77,.08)" : `${sc}1a`} 0%, ${t.cardBg} 100%)`,
      border: `1px solid ${t.cardBorder}`,
      borderLeft: `3px solid ${sc}`,
      opacity: isDead ? 0.6 : 1,
    }}>
      <Ring pct={mainPct < 0 || isDead ? 0 : mainPct} r={17} sw={4} color={sc} track={t.ringTrack} size={42} glow={glowColor}>
        <span style={{ fontSize: 11, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{isDead || mainPct < 0 ? "—" : mainPct}</span>
      </Ring>
      <div className="mb-row-info">
        <div className="mb-row-name-line">
          <span className="mb-row-name" style={{ color: t.text }}>{a.node}</span>
          <span className="mb-row-status" style={{ color: sc }}>{STATUS_TEXT[a.status]}</span>
          {isBest && <span className="mb-row-badge-use" style={{ color: t.accentText, background: t.accent }}>USE</span>}
          {isCurrent && <span className="mb-row-badge-cur" style={{ color: t.accent, border: `1px solid ${t.accentBorder}` }}>当前</span>}
        </div>
        <div className="mb-row-email" style={{ color: t.email }}>{a.email}</div>
        {!isDead && a.windows.length > 0 && (
          <div className="mb-row-windows" style={{ color: t.text2 }}>
            {a.windows.map(w => {
              const c = w.pct <= 10 ? "#E0524D" : w.pct <= 30 ? "#E0901C" : sc;
              return <span key={w.label}>{w.label} <b style={{ color: c }}>{w.pct}%</b> <span style={{ color: t.muted }}>↻{w.reset}</span></span>;
            })}
          </div>
        )}
        {isDead && <span className="mb-row-dead">token 失效</span>}
      </div>
      <div className="mb-row-exp">
        <span className="mb-row-exp-text" style={{ color: t.muted }}>到期 {a.exp}</span>
      </div>
    </div>
  );
}
