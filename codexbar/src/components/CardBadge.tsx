import { CARD_WARN_DAYS, type Account } from "../helpers";
import { CARD_TYPE as Z, type Theme } from "../theme";

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

// ★ 非 compact 那档读 `CARD_TYPE`（总览卡的统一字号标尺）；compact 是菜单栏专用，**不跟着放大**。
const SIZE = (compact?: boolean) => compact
  ? { font: 8.5, pad: "1px 6px", icon: 9, gap: 4 }
  : { font: Z.badgeFont, pad: Z.badgePad, icon: Z.badgeIcon, gap: 5 };

/** 三种形态共用的外壳。**只有它决定高度** —— 见 `CardBadgeGhost` 的说明。 */
const shell = (compact?: boolean) => {
  const s = SIZE(compact);
  return {
    display: "inline-flex", alignItems: "center", gap: s.gap, flexShrink: 0,
    fontSize: s.font, fontWeight: 700, padding: s.pad, borderRadius: 999,
    fontVariantNumeric: "tabular-nums",
    // ★ 行高写死，让盒高与**字形**无关：中文「重置卡」的行盒比拉丁数字高 2px，
    //   占位里没有中文就会比真徽章矮 2px，而这 2px 会原样变成细条的错位。
    // ★★ **只给主窗口那档**。占位（CardBadgeGhost）只在主窗口用，菜单栏根本没有占位，
    //    却会被这条行高连累 —— 实测 compact 徽章 14 → 15.89px（宽度不变）。
    //    sweep 只查折行/溢出/压扁，量不到 2px 的高度变化，所以它会一路绿着。
    ...(compact ? null : { lineHeight: 1.4 }),
    // 描边算进盒高（各 1px）。放进壳里而不是只写在有徽章那支，否则占位比真徽章矮 2px，
    // 而这 2px 会被弹性留白原样转成细条的错位。有徽章那支在后面覆盖成实色。
    border: "1px solid transparent",
  } as const;
};

/**
 * 与 CardBadge **同壳**的隐形占位。
 *
 * 总览卡片的条形区是从卡片**底边往上推**的（见 AccountCard 的弹性留白），
 * 于是「页脚有多高」直接决定上面那些细条落在哪条线上 —— 而页脚高度本来会随
 * 「这个号有没有重置卡」「这张是不是 grok 卡」变化，同一排卡就会错开半行。
 * 让没有徽章的页脚也占同一个壳，那条水平线就与内容无关了。
 *
 * ★ 复用同一份壳而不是写死一个像素高度：字号或内边距一改，占位自动跟上；
 *   写死的话它会在某次调字号后**静默失准**，而且看不出是这里的问题。
 */
export function CardBadgeGhost({ compact }: { compact?: boolean }) {
  return (
    <span aria-hidden style={{ ...shell(compact), visibility: "hidden" }}>
      {/* 文案要与真徽章**同字形类**（中文 + 拉丁）。只写 `0` 的话行盒比中文矮 2px ——
          CJK 与拉丁的行盒不一样高，占位就白占了。内容不可见，这里只借它的高度。 */}
      <IconTicket size={SIZE(compact).icon} />重置卡 ×0
    </span>
  );
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
    // ★ 走同一个壳（透明描边、无底色），否则「无重置卡」的页脚比有徽章的矮 9px，
    //   把这张卡的细条整体顶下去半行。菜单栏那版不画，也就没有这个问题。
    return compact ? null : (
      <span style={{ ...shell(), fontWeight: 400, color: t.muted, fontFamily: "'JetBrains Mono'" }}>
        <IconTicket size={SIZE().icon} />无重置卡
      </span>
    );
  }

  const expiring = isCardExpiring(a);
  const size = SIZE(compact);

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
        ...shell(compact),
        color: expiring ? AMBER_TEXT : t.accent,
        background: expiring ? "rgba(224,144,28,.14)" : t.accentSoft,
        border: `1px solid ${expiring ? "rgba(224,144,28,.5)" : t.accentBorder}`,
        animation: expiring ? "cbPulse 2s infinite" : "none",
      }}>
      <IconTicket size={size.icon} />{label}
    </span>
  );
}
