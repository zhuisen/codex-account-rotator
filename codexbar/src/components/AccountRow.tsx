import { STATUS_COLORS, STATUS_TEXT, type Theme } from "../theme";
import { type Account, quotaColor, maskId } from "../helpers";
import Ring from "./Ring";
import PlanBadge from "./PlanBadge";
import CardBadge, { isCardExpiring, AMBER } from "./CardBadge";

export default function AccountRow({ a, isCurrent, isBest, bestPct, privacy, t, onSelect }: {
  a: Account; isCurrent: boolean; isBest: boolean; bestPct: number; privacy: boolean; t: Theme; onSelect: () => void;
}) {
  const isDead = a.status === "dead";
  const isCool = a.status === "cool";
  const sc = STATUS_COLORS[a.status] ?? STATUS_COLORS.live;
  const pct = a.windows[0]?.pct ?? -1;
  const known = pct >= 0 && !isDead;
  const qc = isDead || isCool ? sc : quotaColor(pct);
  const glow = known && pct <= 20 ? (pct <= 10 ? "#E0524D" : "#E0901C") : undefined;
  const expiring = isCardExpiring(a);
  const delta = known && bestPct >= 0 ? pct - bestPct : null;

  // Left rail encodes ONE thing, in priority order: an expiring card outranks "is current", which
  // outranks the quota level. Same order as the card border so the two surfaces agree.
  const rail = expiring ? AMBER : isCurrent ? t.accent : qc;

  return (
    <div className="mb-row" onClick={onSelect} style={{
      background: t.cardBg,
      border: `1px solid ${expiring ? "rgba(224,144,28,.35)" : t.cardBorder}`,
      borderLeft: `3px solid ${rail}`,
      opacity: isDead ? 0.6 : 1,
    }}>
      <Ring pct={known ? pct : 0} r={18} sw={4.5} color={qc} track={t.ringTrack} size={46} glow={glow}>
        <span style={{ fontSize: 12, fontWeight: 700, color: t.text, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{known ? pct : "—"}</span>
      </Ring>

      <div className="mb-row-info">
        <div className="mb-row-name-line">
          <span className="mb-row-name" style={{ color: t.text }}>{a.node}</span>
            <PlanBadge plan={a.plan} t={t} />
          <span className="mb-row-status" style={{ color: sc }}>{STATUS_TEXT[a.status]}</span>
          {isBest && <span className="mb-row-badge-use" style={{ color: t.accentText, background: t.accent }}>USE</span>}
          {isCurrent && <span className="mb-row-badge-cur" style={{ color: t.accent, border: `1px solid ${t.accentBorder}` }}>当前</span>}
          {isCurrent ? (
            <span className="mb-row-delta" style={{ color: t.accent, background: t.accentSoft }}>✓ 当前</span>
          ) : delta != null && (
            <span className="mb-row-delta" style={{
              color: delta === 0 ? t.accent : delta <= -50 ? AMBER : t.email,
              background: delta === 0 ? t.accentSoft : delta <= -50 ? "rgba(224,144,28,.12)" : t.ghostBg,
            }}>{delta === 0 ? "最优" : `${delta}%`}</span>
          )}
        </div>

        <div className="mb-row-sub">
          <span className="mb-row-email" style={{ color: t.email }}>{maskId(a.email, privacy)}</span>
          <span className="mb-row-exp-text" style={{ color: t.muted }}>到期 {a.exp}</span>
        </div>

        <div className="mb-row-meta">
          {known && a.windows[0] ? (
            <>
              <span style={{ fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{a.windows[0].label}</span>
              <div className="mb-row-bar" style={{ background: t.barTrack }}>
                <div style={{ height: "100%", width: `${pct}%`, background: qc, borderRadius: 2, transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
              </div>
              <span style={{ fontSize: 9.5, fontWeight: 600, color: pct < 50 ? AMBER : t.text2, fontVariantNumeric: "tabular-nums" }}>{pct}%</span>
              <span style={{ fontSize: 9, color: t.muted, fontFamily: "'JetBrains Mono'" }}>↻{a.windows[0].reset}</span>
            </>
          ) : (
            <span className="mb-row-dead">{isDead ? "token 失效 · 需重登" : "未探测"}</span>
          )}
          <CardBadge a={a} t={t} compact />
        </div>
      </div>
    </div>
  );
}
