import type { Theme } from "../theme";

export const TONE = { amber: "#E0901C", red: "#E0524D", muted: null as string | null };
export type Tone = keyof typeof TONE;

/**
 * 额度取不到时的**紧凑标记**：一个感叹号，说明只在悬浮时出现。grok / agy 共用的呈现原语。
 *
 * ★★ 为什么从整条横幅退到一个字符（用户 2026-08-24 定稿，起因是 grok）：
 * grok 的 access token 寿命就是 **6 小时**，所以「已过期」这个提示**按设计每天必然出现几次**，
 * 而且用户什么都不用做 —— 起一次 grok 就自愈。
 * 项目铁律「把警报放在眼睛已经在的地方」的前提是**它是个警报**；一个天天弹、又能自愈的横幅
 * 不是警报，是噪音，**而噪音会训练人忽略真警报** —— 那正是那条铁律真正要防的事。
 * 所以这里是那条规则的**例外，不是违反**：把常态噪音降到一个字符，给真警报腾出注意力。
 *
 * ★ agy 让这条理由更强而不是更弱：agy **不常驻**，"没在跑"是它的常态，
 * 那个状态若挂一条横幅，就是一盏永远亮着的灯。
 *
 * ★ **不可退让的那半仍然成立**：数字绝不假装是活的。
 * 有上次读数就画出来但**强制琥珀 + 标旧**，没有就画 `—`。见各家的 Card / Row。
 * 换句话说：省掉的是**解释**，不是**披露**。
 */
export default function StaleMark({ t, note, tone = "red", size = 11 }: {
  t: Theme;
  /** 全部说明。★ 唯一文案出处仍在各家的 `*ReasonNote`，这里只负责画。 */
  note: string;
  tone?: Tone;
  size?: number;
}) {
  const c = TONE[tone] ?? t.muted;
  return (
    <span
      // ★ 说明都在 `title` 里 —— **刻意**的取舍，理由见文件头。一个字都没少，只是换了呈现位置。
      title={note}
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: size + 3, height: size + 3, borderRadius: "50%",
        fontSize: size - 2, fontWeight: 700, lineHeight: 1,
        color: c, border: `1px solid ${c}`,
        cursor: "help", flexShrink: 0, userSelect: "none",
      }}
    >!</span>
  );
}
