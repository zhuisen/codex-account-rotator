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

export default function DisclosureBanner({ t, badge, note, tone = "amber", action }: {
  t: Theme;
  /** 左侧短徽章，如 `覆盖 3/7` / `额度 读不到`。9.5px 等宽，不换行。 */
  badge: string;
  note: string;
  tone?: Tone;
  /**
   * 可选的行内动作。
   *
   * ★ 加它的理由很具体：本仓披露铁律要求「告警文本要说**做什么**」，而有些告警的
   *   「做什么」是**在这个 app 里点一下**（例：未接入轮换 → 去设置页接入）。
   *   把用户支去别处读文档，等于把可执行的一步降级成一句说明。
   * ⚠️ 仍然**只放导航类动作**，不在披露条里直接执行有副作用的操作 ——
   *   那会让一条「提示」变成一个「按钮」，而用户是来读信息的。
   */
  action?: { label: string; onClick: () => void };
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
      {action && (
        <span onClick={action.onClick}
              style={{ marginLeft: "auto", flex: "none", cursor: "pointer", whiteSpace: "nowrap",
                       fontSize: 10.5, fontWeight: 700, color: c, alignSelf: "center",
                       border: `1px solid ${hexA(c, .5)}`, borderRadius: 7, padding: "3px 9px" }}>
          {action.label}
        </span>
      )}
    </div>
  );
}

/** `#rrggbb` → `rgba(...)`。边框与底色都要按色调走，写死一套就没法复用给红/灰两档。 */
function hexA(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
