import type { Theme } from "../theme";

const MONO = "'JetBrains Mono'";

import type { PoolKey, PoolPlatform } from "../platforms";

/** @deprecated 名字留给旧引用；真源是 `platforms.ts` 的 `PoolKey`。 */
export type ProviderKey = PoolKey;

/** `PoolPlatform` + 两个**只有渲染时才知道**的字段。 */
export interface ProviderTab extends PoolPlatform {
  /** 平台识别色。★ 走 `colorOf(data, …)` 取，别用 `theme.ts` 的静态表 —— 那是链末兜底。 */
  color: string;
  /** 这一档有几张账号卡。**是"渲染出来几张"而不是"池里有几个"** —— 两者不同的时候，
   *  把后者显示出来等于在说一件界面上看不到的事。 */
  count: number;
}

/**
 * 总览的**供应商分档**（用户 2026-09-13 给的样式：`● Codex 6 │ ● Google 1 │ +`）。
 *
 * ★★ 为什么是分档不是并排分区：三家的账号语义**根本不同** ——
 *   codex 经本地代理逐请求换号、agy 只能在启动前换凭证、grok 是单号只读。
 *   竖着堆在一页里时读者会拿同一套直觉去理解它们，而且每区都只占三分之一屏；
 *   一次只看一家，卡片能用满整行宽度。
 *
 * ★ 计数用 `tabular-nums`：切档时数字宽度不变，pill 不会跟着抖。
 */
export default function ProviderTabs({ items, cur, on, onAdd, t }: {
  items: ProviderTab[];
  cur: ProviderKey;
  on: (k: ProviderKey) => void;
  /** `+` —— 给当前这一档加号。 */
  onAdd: (k: ProviderKey) => void;
  t: Theme;
}): React.ReactElement {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, padding: 3,
                  border: `1px solid ${t.ghostBorder}`, borderRadius: 11,
                  flexShrink: 0 }}>
      {items.map((p) => {
        const on_ = p.key === cur;
        return (
          <span key={p.key} onClick={() => on(p.key)} title={p.note}
                // ★ 身份标记，供 uishot 的 `trails` 探针**按时间**采这一枚 pill 的文字。
                //   它守的是「进过这一档之前，计数是不是已经是真数」—— 那种缺陷是**瞬态**的，
                //   终态快照对它完全沉默（见 `make_harness.py` 的 `trails`）。
                data-provtab={p.key}
                style={{ display: "inline-flex", alignItems: "center", gap: 7,
                         padding: "5px 12px", borderRadius: 8, cursor: "pointer",
                         whiteSpace: "nowrap", userSelect: "none",
                         transition: "background .2s, color .2s",
                         background: on_ ? t.accent : "transparent",
                         color: on_ ? t.accentText : t.text2 }}>
            {/* ★ 识别色圆点在选中态也保留：它是**这一档是谁**的标记，
                而青底是**选中**的标记 —— 两件事，去掉一个就要靠文字猜。 */}
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: p.color,
                           flexShrink: 0 }} />
            <span style={{ fontSize: 12.5, fontWeight: 700 }}>{p.label}</span>
            <span style={{ fontFamily: MONO, fontSize: 11, fontWeight: 700,
                           fontVariantNumeric: "tabular-nums",
                           opacity: on_ ? .72 : 1, color: on_ ? t.accentText : t.muted }}>
              {p.count}
            </span>
          </span>
        );
      })}
      <span onClick={() => onAdd(cur)} title="给当前这一档加一个账号"
            // ★ `lineHeight` 必须等于盒高。uishot 的折行探针判据是「内容盒高 vs 单行高」，
            //   `lineHeight: 1` 时这个 26px 的方块算出 26/15 ⇒ 被判成折行（实测 12 个视图变红）。
            //   它是图标按钮不是文字，但探针只看那两个数 —— 让它们相等比去调探针诚实。
            style={{ display: "grid", placeItems: "center", width: 26, height: 26,
                     borderRadius: 8, cursor: "pointer", color: t.muted,
                     fontSize: 15, lineHeight: "26px", userSelect: "none" }}>+</span>
    </div>
  );
}
