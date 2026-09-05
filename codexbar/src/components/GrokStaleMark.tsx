import type { Theme } from "../theme";
import type { GrokAccount } from "../grok";
import { grokReasonNote, grokReasonTone } from "../grok";
import StaleMark, { type Tone } from "./StaleMark";

/**
 * grok 版的降级标记：把 `GrokAccount` 翻成文案 + 色调，画法交给 `StaleMark`。
 *
 * 呈现上的取舍（为什么是一个字符而不是横幅）全部写在 `StaleMark` 的文件头，不在这里重复。
 * 这一层只保留 grok 特有的一件事 ——
 * ★ 色调按 reason 分（`grokReasonTone`）：`unauthorized`（token 被撤销、需要重新登录）是红，
 *   其余自愈类是琥珀。**红色那个不是自愈的**，一眼能与常态噪音分开。
 */
export default function GrokStaleMark({ t, a, note, tone, size = 11 }: {
  t: Theme;
  /** 有账号数据时,文案与色调都从它推导(`grokReasonNote` 仍是唯一出处)。 */
  a?: GrokAccount | null;
  /** 没有账号数据的场景 —— 目前只有一种:读**本机 sidecar** 失败(IO 层)。
   *  ★ 这条不能省成静默:那是"我们自己读不到文件",与"xAI 那边有问题"是两回事,
   *  两者都不能和"额度确实是 0"长成一个样。 */
  note?: string;
  tone?: Tone;
  size?: number;
}) {
  return (
    <StaleMark
      t={t}
      note={note ?? (a ? grokReasonNote(a) : "")}
      tone={tone ?? (a ? grokReasonTone(a) : "red")}
      size={size}
    />
  );
}
