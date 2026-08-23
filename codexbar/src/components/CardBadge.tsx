import { CARD_WARN_DAYS, type Account } from "../helpers";
import type { Theme } from "../theme";

export const IconTicket = ({ size = 10 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M3 8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2a2 2 0 1 0 0 4v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a2 2 0 1 0 0-4z" />
  </svg>
);

export const AMBER = "#E0901C";
export const AMBER_TEXT = "#f2b45c";

/** True when this account holds a card that is about to lapse. Single source of truth for the badge,
 *  the card border, the row's left rail and the pool banner, so they can never disagree. */
export function isCardExpiring(a: Account): boolean {
  return a.cards > 0 && a.cardDays != null && a.cardDays <= CARD_WARN_DAYS;
}

/**
 * Reset-card badge. Three states from the handoff §4: expiring (amber + halo), holding (accent),
 * none (grey text, main window only).
 *
 * `compact` is the menubar row variant — same semantics, the handoff just specifies smaller type
 * there, and the expiring label collapses to bare "N天" because the row has no room for the noun.
 */
export default function CardBadge({ a, t, compact }: { a: Account; t: Theme; compact?: boolean }) {
  if (a.cards <= 0) {
    return compact ? null : (
      <span style={{ fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>无重置卡</span>
    );
  }

  const expiring = isCardExpiring(a);
  const size = compact
    ? { font: 8.5, pad: "1px 6px", icon: 9, gap: 4 }
    : { font: 9.5, pad: "2px 8px", icon: 10, gap: 5 };

  // Days is a float; "0.4 天" reads as already gone, so round UP — a card with 10 hours left is
  // still usable today and must not be labelled 0.
  const days = Math.max(1, Math.ceil(a.cardDays ?? 0));
  // The COUNT is always shown. The expiring suffix names how many of them actually lapse, because
  // "2 张" + "2 天后到期" side by side otherwise reads as "both cards die in 2 days" — the common
  // real case is a stack where only the oldest is about to go.
  // Kept short on purpose: the card's badge row only has ~200px next to the 到期 date, and a longer
  // phrasing ("N 张 N 天后到期") pushed the date onto a second line. Full wording is in the tooltip.
  const some = expiring && a.cardsExpiring > 0 && a.cardsExpiring < a.cards;
  const nOf = some ? `${a.cardsExpiring}张` : "";
  const label = compact
    ? `×${a.cards}${expiring ? `·${nOf}${days}天` : ""}`
    : `重置卡 ×${a.cards}${expiring ? ` · ${nOf}剩${days}天` : ""}`;

  return (
    <span
      title={a.cardExp
        ? `共 ${a.cards} 张 · 最早一张到期 ${a.cardExp}${a.cardsExpiring ? ` · ${a.cardsExpiring} 张在 ${CARD_WARN_DAYS} 天内作废` : ""}`
        : `共 ${a.cards} 张 · 到期未知(运行 codex-rotate credits 取明细)`}
      style={{
        display: "inline-flex", alignItems: "center", gap: size.gap, flexShrink: 0,
        fontSize: size.font, fontWeight: 700, padding: size.pad, borderRadius: 999,
        fontVariantNumeric: "tabular-nums",
        color: expiring ? AMBER_TEXT : t.accent,
        background: expiring ? "rgba(224,144,28,.14)" : t.accentSoft,
        border: `1px solid ${expiring ? "rgba(224,144,28,.5)" : t.accentBorder}`,
        animation: expiring ? "cbPulse 2s infinite" : "none",
      }}>
      <IconTicket size={size.icon} />{label}
    </span>
  );
}
