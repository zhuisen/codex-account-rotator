import type { Theme } from "../theme";

const MONO = "'JetBrains Mono'";

/**
 * 总览按**供应商**分区（用户 2026-09-13：「总览版块要划分 openai 和 gemini 等」）。
 *
 * ★★ 分区不是装饰，是因为**这三家的账号语义根本不同**，混在一张网格里读者会拿
 *   同一套直觉去理解它们：
 *     · OpenAI(codex) —— 池，经本地代理**每请求**换号，5h/周双窗口，探针要花钱
 *     · Google(agy)   —— 池，**启动前**换凭证（agy 只在启动时读），额度是随时可读的比例
 *     · xAI(grok)     —— 单号只读，周窗口
 *   「为什么 codex 能热切而 agy 不能」这种问题，只有把它们摆在各自的标题下才不会一直被问。
 *
 * ★ 每个分区**各自一张网格**（都带 `data-cards-grid`）。uishot 的对齐闸是「按排比较」的，
 *   分区之后每张网格就是自己的比较集 —— 比原来一张大网格更准，不会拿 grok 卡去跟
 *   codex 卡比高度。
 */
export default function ProviderSection({ title, note, count, children, t }: {
  /** 供应商名，如 `OpenAI` */
  title: string;
  /** 一句话说清这一区的账号是怎么轮换的 —— 三家的机制不同，不写就会被当成一样的。 */
  note: string;
  /** 这一区有几个账号。`undefined` = 不显示（单号的那种区不需要计数）。 */
  count?: number;
  children: React.ReactNode;
  t: Theme;
}): React.ReactElement {
  return (
    <section style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 7 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: t.text2, letterSpacing: ".02em" }}>
          {title}
        </span>
        {count != null && (
          <span style={{ fontFamily: MONO, fontSize: 10, fontWeight: 700, color: t.muted,
                         border: `1px solid ${t.ghostBorder}`, borderRadius: 999,
                         padding: "0 6px", lineHeight: "15px" }}>{count}</span>
        )}
        {/* ★ 说明文字**跟标题同排右对齐**，不另起一行：总览是"一屏看全"的页面，
            三个分区各多一行说明就是多 60px，而那 60px 会把卡片挤到折叠线以下。 */}
        <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10, color: t.muted,
                       whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {note}
        </span>
      </div>
      {children}
    </section>
  );
}
