import type { Theme } from "../theme";
import type { GrokAccount } from "../grok";
import { grokReasonNote, grokReasonTone } from "../grok";

const TONE = { amber: "#E0901C", red: "#E0524D", muted: null as string | null };

/**
 * grok 额度取不到时的**紧凑标记**：一个感叹号，说明只在悬浮时出现。
 *
 * ★★ 为什么从整条横幅退到一个字符（用户 2026-08-24 定稿）：
 * grok 的 access token 寿命就是 **6 小时**，所以「已过期」这个提示**按设计每天必然出现几次**，
 * 而且用户什么都不用做 —— 起一次 grok 就自愈。
 * 项目铁律「把警报放在眼睛已经在的地方」的前提是**它是个警报**；一个天天弹、又能自愈的横幅
 * 不是警报，是噪音，**而噪音会训练人忽略真警报** —— 那正是那条铁律真正要防的事。
 * 所以这里是那条规则的**例外，不是违反**：把常态噪音降到一个字符，给真警报腾出注意力。
 *
 * ★ **不可退让的那半仍然成立**：数字绝不假装是活的。
 * 有上次读数就画出来但**强制琥珀 + 标「旧」**，没有就画 `—`。见 `GrokCard` / `GrokRow`。
 * 换句话说：省掉的是**解释**，不是**披露**。
 *
 * ★ 色调仍按 reason 分（`grokReasonTone`）：`unauthorized`（token 被撤销、需要重新登录）是红，
 * 其余自愈类是琥珀。**红色那个不是自愈的**，一眼能与常态噪音分开。
 */
export default function GrokStaleMark({ t, a, note, tone, size = 11 }: {
  t: Theme;
  /** 有账号数据时,文案与色调都从它推导(`grokReasonNote` 仍是唯一出处)。 */
  a?: GrokAccount | null;
  /** 没有账号数据的场景 —— 目前只有一种:读**本机 sidecar** 失败(IO 层)。
   *  ★ 这条不能省成静默:那是"我们自己读不到文件",与"xAI 那边有问题"是两回事,
   *  两者都不能和"额度确实是 0"长成一个样。 */
  note?: string;
  tone?: keyof typeof TONE;
  size?: number;
}) {
  const resolved = tone ?? (a ? grokReasonTone(a) : "red");
  const text = note ?? (a ? grokReasonNote(a) : "");
  const c = TONE[resolved] ?? t.muted;
  return (
    <span
      // ★ 全部说明都在 `title` 里 —— 这是**刻意**的取舍，理由见文件头。
      //   `grokReasonNote` 仍是唯一文案出处，一个字都没少，只是换了呈现位置。
      title={text}
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
