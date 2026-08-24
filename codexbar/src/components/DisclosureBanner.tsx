import type { Theme } from "../theme";

/**
 * 「这份数字有保留」的统一披露条。
 *
 * 从 `PlatformPage` 的 `CoverageBanner` 抽出来的**同视觉**通用件 —— 度量逐条保留，
 * 抽出的只是壳，**文案仍归各调用方所有**（`coverageNote` / `grokReasonNote` 各写各的）。
 * 两处共用像素、各自拥有措辞，是项目里"判定单一真源"那条的正常形态。
 *
 * ★ 为什么必须是横幅而不是 `title`：项目铁律「把警报放在眼睛已经在的地方」。
 *   反例是 erp-v3 那两条「利润被高估」的警告，在 tooltip 里躺了几个月没人看见。
 */
const TONES = {
  amber: "#E0901C",
  red: "#E0524D",
  muted: null as string | null,   // 用主题的三级中性色，随明暗主题走
};

export type Tone = keyof typeof TONES;

export default function DisclosureBanner({ t, badge, note, tone = "amber" }: {
  t: Theme;
  /** 左侧短徽章，如 `覆盖 3/7` / `额度 读不到`。9.5px 等宽，不换行。 */
  badge: string;
  note: string;
  tone?: Tone;
}) {
  const c = TONES[tone] ?? t.muted;
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start",
                  border: `1px solid ${hexA(c, .35)}`,
                  background: hexA(c, t.isDark ? .09 : .10),
                  borderRadius: 9, padding: "7px 10px", marginBottom: 10 }}>
      <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 9.5, fontWeight: 700, color: c,
                     whiteSpace: "nowrap", paddingTop: 1, letterSpacing: ".03em" }}>
        {badge}
      </span>
      <span style={{ fontSize: 10.5, lineHeight: 1.55, color: t.text2 }}>{note}</span>
    </div>
  );
}

/** `#rrggbb` → `rgba(...)`。边框与底色都要按色调走，写死一套就没法复用给红/灰两档。 */
function hexA(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
