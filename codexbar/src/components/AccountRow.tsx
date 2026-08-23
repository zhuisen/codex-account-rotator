import { STATUS_COLORS, STATUS_TEXT, type Theme } from "../theme";
import { type Account, quotaColor, maskId } from "../helpers";
import Ring from "./Ring";
import PlanBadge from "./PlanBadge";
import CardBadge, { isCardExpiring, AMBER } from "./CardBadge";

export default function AccountRow({ a, isCurrent, isBest, bestPct, privacy, t, onSelect,
                                     onSwitch, switching }: {
  a: Account; isCurrent: boolean; isBest: boolean; bestPct: number; privacy: boolean; t: Theme;
  /** 点行本身 = 弹出主界面(既有行为,不变) */
  onSelect: () => void;
  /**
   * 尾部「切换」按钮(用户 2026-08-11 要求)。**只在传了它时才渲染** —— 调用方负责判断
   * 当前号/失效号不该给(切到自己没意义,切到死号会立刻 failover 回来)。
   *
   * 它与 `onSelect` 是两个动作叠在同一行上,所以按钮**必须 stopPropagation**:
   * 否则点「切换」会同时把主窗口弹出来,而这个按钮存在的意义正是"不用开主窗口就能换号"。
   */
  onSwitch?: () => void;
  /** 该号正在切换中。切号要跑一次 CLI,没有这个状态按钮会看起来没反应、诱发连点。 */
  switching?: boolean;
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
              color: delta === 0 ? t.accent : delta <= -50 ? AMBER : t.text2,
              background: delta === 0 ? t.accentSoft : delta <= -50 ? "rgba(224,144,28,.12)" : t.ghostBg,
            }}>{delta === 0 ? "最优" : `${delta}%`}</span>
          )}
        </div>

        <div className="mb-row-sub">
          <span className="mb-row-email" style={{ color: t.text2 }}>{maskId(a.email, privacy)}</span>
          <span className="mb-row-exp-text" title={a.expStale ? "OpenAI 上次复核订阅早于这个日期,所以「已过期」是拿陈旧快照下的结论 —— 续费不在它视野里。刷新 token 也拉不到新状态,要等 OpenAI 自己复核。" : undefined} style={{ color: t.muted }}>到期 {a.exp}{a.expStale && <span style={{ color: "#E0901C" }}>*</span>}</span>
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

      {/* 尾部悬浮「切换」。绝对定位 ⇒ 不占布局,显隐时整行不跳;渐变遮罩避免与「↻重置」叠字。 */}
      {onSwitch && (
        <div className="mb-row-switch-wrap"
             style={{ background: `linear-gradient(to right, transparent, ${t.cardBg} 30px)` }}>
          <span className="mb-row-switch"
                title={`切到 ${a.node}(不打开主界面)`}
                onClick={(e) => { e.stopPropagation(); if (!switching) onSwitch(); }}
                style={{
                  color: switching ? t.muted : t.accent,
                  border: `1px solid ${switching ? t.ghostBorder : t.accentBorder}`,
                  background: switching ? t.ghostBg : t.accentSoft,
                  cursor: switching ? "default" : "pointer",
                }}>
            {switching ? "切换中…" : "切换"}
          </span>
        </div>
      )}
    </div>
  );
}
