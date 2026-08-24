import type { Theme } from "../theme";

export interface Kpi {
  k: string;
  v: string;
  /**
   * 原始数值 + 格式化函数。**两个都给了这一格才滚**，否则原样显示 `v`。
   * 像「Claude 73.6%」「—」这类不是纯数的格子不给 —— 把一个占位符从 0 滚上来只会让人以为在加载。
   */
  n?: number;
  fmt?: (x: number) => string;
  /** 主数值颜色,缺省用正文色 */
  c?: string;
  /** 数值下方的小字 */
  sub?: string;
  /** 小字颜色(环比涨绿跌红),缺省 `t.text2` */
  subC?: string;
}

/** 环比 / 涨跌的固定语义色。绿=上涨、红=下跌,与全局设计规范一致。 */
export const UP = "#27B26B";
export const DOWN = "#E0524D";

/**
 * 顶部 KPI 条。**总览页和平台详情页共用这一份。**
 *
 * ★ 抽出来的原因是它已经漂过两次:两页各写一份渲染,总览把「合计 token」改成「总 token」时详情页
 * 没跟上;总览加了「环比」「缓存已省」子行、改成均分居中之后,详情页仍是左侧紧排且没有子行
 * (用户 2026-08-10 实测截图)。同一条 UI 两个实现,迟早在边界上分叉 —— 这里只留一个。
 *
 * 布局用 `space-evenly` 而不是 `justifyContent:center`:后者只是把空白从右边挪成左右各一半,
 * 条目仍然挤在中间。每格文字居中,配合均分才读得整齐。
 */
export default function KpiStrip({ t, items, intro = 1 }: {
  t: Theme; items: Kpi[];
  /** 入场进度 0→1（见 `useIntro`）。缺省 1 = 不动画，老调用点不用改。 */
  intro?: number;
}): React.ReactElement {
  return (
    <div style={{ display: "flex", justifyContent: "space-evenly", alignItems: "flex-start", gap: 18,
                  // ★★ **数字被裁比排版难看严重得多** —— 900px 实测「9.76B」的格子渲染宽 68px、
                  //   自然宽 80px,右边直接切掉,读出来就是另一个数。所以窄了就换行,绝不裁。
                  flexWrap: "wrap", rowGap: 14,
                  padding: "10px 18px", marginBottom: 9, borderRadius: 12,
                  background: t.isDark ? "#0e1319" : t.cardBg, border: `1px solid ${t.cardBorder}` }}>
      {items.map(({ k, v, c, sub, subC, n, fmt }) => (
        <div key={k} style={{ minWidth: "max-content", textAlign: "center", flexShrink: 0 }}>
          {/* 标签 12.5px:从 11 / 12 / 12.5 / 13.5 四档里选的(用户 2026-08-10)。13.5 开始和 29px 的
              数值抢主次,11 又偏小。四档在 1000px 默认窗宽下都不溢出(最大需 701px / 可用 886px)。 */}
          <div style={{ fontSize: 12.5, color: "#10E0E0", fontFamily: "'JetBrains Mono'",
                        letterSpacing: ".04em", whiteSpace: "nowrap" }}>{k}</div>
          {/* ★ hero 数字用 **Space Grotesk**(比例字体),是对「一切数字用等宽」的**知情例外**。
              理由:那条规则的目的是"数字右对齐成列时能对齐",而这一格是**居中的单个数字**,不在列里。
              用户 2026-08-10 从 6 个 demo 里选的 D 档(11 / 29 / 11)。
              `tabular-nums` 仍然保留 —— 这个数每 2 分钟自动刷新,等宽数位能防止 9.85B → 10.1B 时宽度跳动。
              **仅限这一处**:模型行、费率卡那些真正成列的数字仍必须用 JetBrains Mono。 */}
          <div style={{ fontSize: 29, fontWeight: 700, marginTop: 2, whiteSpace: "nowrap",
                        fontFamily: "'Space Grotesk'", fontVariantNumeric: "tabular-nums",
                        letterSpacing: "-.01em", color: c ?? t.text }}>
            {/* ★ 第二道防线:进度必须落在 [0,1) 才用它算 —— 上游钳过一次了，但这一格是
                **用户唯一会盯着看的数字**，画错一次的代价远大于这行判断。 */}
            {n != null && fmt && intro >= 0 && intro < 1 ? fmt(n * intro) : v}
          </div>
          {/* 曾是 9px + `t.faint`(#454d57,实算 2.2:1),用户实测「没看到」。字号定在 11px;
              颜色那一半已由 2026-08-23 的三级灰阶统一解决(`t.muted` 现为 4.55:1),
              闸在 tests/test_theme_contrast.py */}
          {sub && (
            <div style={{ fontSize: 11, color: subC ?? t.text2, fontFamily: "'JetBrains Mono'",
                          marginTop: 3, whiteSpace: "nowrap" }}>{sub}</div>
          )}
        </div>
      ))}
    </div>
  );
}
