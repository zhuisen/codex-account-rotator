import { useState } from "react";
import type { Theme } from "../theme";

export interface Layer {
  key: string;
  name: string;
  color: string;
  /** 与 labels 等长 */
  values: number[];
}

/** 交接稿 §1:viewBox 1130×224,绘图区左移 34 留 y 轴标签位 → 可绘宽 1096(hover 吸附公式用的就是它)。 */
const VW = 1130, PL = 34, PW = VW - PL;

/**
 * 单调三次插值(Fritsch–Carlson)。
 *
 * ★ 交接稿 §1 写的是 Catmull-Rom,这里**刻意偏离**:普通样条在陡降处会过冲到基线以下,
 *   token 量不可能为负,画出负填充就是画一个不存在的事实;堆叠模式下相邻两条带还会互相穿插。
 *   单调插值保证区间内不超出两端点值域 —— 同样圆润,但不说谎。(项目 CLAUDE.md §5 已用
 *   「峰后归零 / 全零突增 / 单调递增」三组数据验证过采样点永不越界。)
 */
function monotonePath(pts: [number, number][]): string {
  const n = pts.length;
  if (n === 0) return "";
  if (n === 1) return `M ${pts[0][0]} ${pts[0][1]}`;
  if (n === 2) return `M ${pts[0][0]} ${pts[0][1]} L ${pts[1][0]} ${pts[1][1]}`;
  const dx: number[] = [], dy: number[] = [], d: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1][0] - pts[i][0]);
    dy.push(pts[i + 1][1] - pts[i][1]);
    d.push(dy[i] / (dx[i] || 1));
  }
  const m: number[] = [d[0]];
  for (let i = 1; i < n - 1; i++) m.push(d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2);
  m.push(d[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / d[i], b = m[i + 1] / d[i], s = a * a + b * b;
    if (s > 9) { const tau = 3 / Math.sqrt(s); m[i] = tau * a * d[i]; m[i + 1] = tau * b * d[i]; }
  }
  let path = `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    path += ` C ${(pts[i][0] + h).toFixed(2)} ${(pts[i][1] + m[i] * h).toFixed(2)}`
          + ` ${(pts[i + 1][0] - h).toFixed(2)} ${(pts[i + 1][1] - m[i + 1] * h).toFixed(2)}`
          + ` ${pts[i + 1][0].toFixed(2)} ${pts[i + 1][1].toFixed(2)}`;
  }
  return path;
}

/**
 * 一条**真正的带**:上边界 = 本层累计线,下边界 = 前一层累计线(倒序回来闭合)。
 *
 * ★ 原画法是「每层都填到基线的完整面积,自上而下叠画靠遮挡形成 band」。那样**最上层那张 path
 * 覆盖整个图区** —— 一旦 hover 让上面的层降到 opacity .25,最上层的整块颜色就透出来:
 * 0.2% 的 Grok 看起来占满全图(用户 2026-08-09 实测截图)。当初「堆叠带必须不透明」那条约束
 * 就是在给这个画法打补丁,不是设计意图;改成画真带后透明度/高亮才真正可用。
 *
 * 倒序那半段复用同一个单调插值:Fritsch–Carlson 在点序反转下对称(dx、dy 同时变号 ⇒ 斜率 d 不变),
 * 所以相邻两条带的公共边界逐点重合,不会出现缝隙或重叠。
 */
function bandPath(top: [number, number][], base: [number, number][]): string {
  const up = monotonePath(top);
  const down = monotonePath([...base].reverse());
  return `${up} L ${down.slice(2)} Z`;   // 去掉下半段开头的 "M ",接成一条闭合路径
}

/** 一个 `08-09` / `14:00` 标签约占 40px(10px mono),按内容区宽 ~946px 反推能放多少个不重叠。 */
const MAX_X_LABELS = 22;

export default function StackedArea({
  labels, layers, height = 224, fmt, t, dimmed, tipTitle, onPick, xTick,
}: {
  labels: string[];
  /** 自下而上:占比大的放前面(贴基线更稳定,细带被夹在中间会来回跳) */
  layers: Layer[];
  height?: number;
  fmt: (n: number) => string;
  t: Theme;
  /** 图例 hover 联动:非该 key 的层降到 .25 */
  dimmed?: string | null;
  tipTitle?: (i: number) => string;
  onPick?: (key: string) => void;
  /** 横轴标签抽稀间隔。留空 = 按可绘宽度自动算(**推荐**:两个页面各写一份阈值迟早分叉,
   *  实测 30d 档因为调用方写的是 `>30` 才抽稀、正好 30 个时不生效,标签糊成一团)。 */
  xTick?: number;
}): React.ReactElement | null {
  /**
   * ★ `hover` 只是"某个数据集里的索引",它**不携带自己属于哪一档**。切档位必须让整个实例作废,
   * 靠调用方传 `key`(见下面 `hv` 的注释)。组件自己清不干净 —— 试过并被用户实测推翻两次。
   */
  const [hover, setHover] = useState<number | null>(null);
  const n = labels.length;
  if (!n || !layers.length) return null;

  const x = (i: number) => PL + (n === 1 ? PW / 2 : (i * PW) / (n - 1));

  // 逐点累加成堆叠上沿
  const tops: number[][] = [];
  const acc = new Array(n).fill(0);
  for (const L of layers) {
    const top = L.values.map((v, i) => (acc[i] += v || 0));
    tops.push([...top]);
  }
  const peak = Math.max(1, ...tops[tops.length - 1]);
  const y = (v: number) => (1 - v / peak) * height;

  // 0 也走同一套刻度渲染:原来单独用 bottom:-6 画,会掉到横轴标签行里去(实测截图)
  const ticks = [1, 0.75, 0.5, 0.25, 0];
  /**
   * ★★ 切档位的 hover 残留:**必须由调用方传 `key={档位}` 解决**,组件内部清不掉。
   *
   * 用户 2026-08-09 报「快速连续切日期会出现上一个日期的数据」,我先加了
   * `useEffect(() => setHover(null), [labels.length, layers.length])` + 这条 clamp,**实测仍复现**。
   * 三方(codex)复核后确认这套补丁在原理上就挡不住,三条独立原因:
   *   1. React 复用同一个组件实例,旧 `hover` 直接活到新数据集里;
   *   2. `hover` 只是数字,不带"我属于哪一档"。切档后同一个索引往往**仍然在范围内**,
   *      于是 clamp 放行 —— clamp 防的是越界,不是语义过期;
   *   3. `labels.length` 不是数据集 identity:不同档位可能等长(30d ↔ 今日第 30 小时),
   *      连点还会跳过中间长度;而且 effect 在 commit 之后才跑,新数据至少先用旧 `hover` 画一帧,
   *      排队中的旧 `mousemove` 也会写回同一个 state。
   * `key` 一换就卸载重建,上面三条同时消失。这条 clamp 只留作纯防御(调用方漏传 key 时兜底)。
   */
  const hv = hover != null && hover >= 0 && hover < n ? hover : null;

  return (
    <div style={{ position: "relative", paddingLeft: 0, marginTop: 14 }}
         onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${VW} ${height}`} preserveAspectRatio="none"
           style={{ width: "100%", height, display: "block" }}>
        {ticks.filter((f) => f > 0).map((f) => (
          <line key={f} x1={PL} x2={VW} y1={y(peak * f)} y2={y(peak * f)}
                stroke="rgba(255,255,255,.07)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        <line x1={PL} x2={VW} y1={height} y2={height}
              stroke="rgba(255,255,255,.16)" strokeWidth={1} vectorEffect="non-scaling-stroke" />

        {/* 每层画自己的带(上沿=本层累计线,下沿=前一层累计线),不再互相遮挡 */}
        {layers.map((L, li) => {
          const top = tops[li].map((v, i) => [x(i), y(v)] as [number, number]);
          const base: [number, number][] = li === 0
            ? tops[0].map((_, i) => [x(i), height] as [number, number])
            : tops[li - 1].map((v, i) => [x(i), y(v)] as [number, number]);
          const dim = dimmed && dimmed !== L.key ? 0.22 : 1;
          return (
            <path key={L.key} d={bandPath(top, base)} fill={L.color} opacity={dim}
                  style={{ cursor: onPick ? "pointer" : "default", transition: "opacity .18s" }}
                  onClick={() => onPick?.(L.key)} />
          );
        })}

        {/* ★ 被高亮的那层额外描一条上沿线。占比很小的层(本机 Grok=0.2%)带高不足 1px,
            光靠填充**高亮了也看不见** —— 描边保证"这层在哪儿"始终可读:降序堆叠下最小的那层在最顶上,
            它的上沿就是总量包络线,描出来正好说明"这一薄层贴在顶部"。非高亮态不描,免得加假轮廓。 */}
        {dimmed && layers.map((L, li) => (L.key === dimmed ? (
          <path key={`hl-${L.key}`} fill="none" stroke={L.color} strokeWidth={2}
                vectorEffect="non-scaling-stroke" pointerEvents="none"
                d={monotonePath(tops[li].map((v, i) => [x(i), y(v)] as [number, number]))} />
        ) : null))}

        {/* ★ `key={hv}`:索引一变就整组替换,而不是原地改属性。用户 2026-08-09 截到一帧
            **标题+明细行是 08:00、总计+参考线是 10:00** 的混合态(两个索引的真实数值,已用逐索引
            断言确认各自都对)。React 单次提交本该原子,复现不出来;但浮层是全 app 唯一带
            `backdrop-filter` 且每次 hover 都改 `left` 的元素,合成层撕裂是排除不掉的解释。
            打 key 让"部分子节点没更新"在 React 层面不可能发生,代价只是一个极小子树的重建。 */}
        {hv != null && (
          <g key={`hv-${hv}`}>
            <line x1={x(hv)} x2={x(hv)} y1={0} y2={height}
                  stroke="rgba(255,255,255,.28)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            {layers.map((L, li) => (tops[li][hv] > 0 ? (
              <circle key={L.key} cx={x(hv)} cy={y(tops[li][hv])} r={4.5}
                      fill={L.color} stroke="#0c0f13" strokeWidth={2}
                      vectorEffect="non-scaling-stroke" />
            ) : null))}
          </g>
        )}

        {/* 透明命中带:按 x 吸附最近数据点(§2 的 idx 公式) */}
        <rect x={PL} y={0} width={PW} height={height} fill="transparent"
              onMouseMove={(e) => {
                const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
                const i = Math.round(((e.clientX - r.left) / r.width) * (n - 1));
                setHover(Math.max(0, Math.min(n - 1, i)));
              }} />
      </svg>

      {/* ★ 轴刻度走 HTML 绝对定位标注层而非 SVG <text>:preserveAspectRatio=none 会把 <text>
          横向拉伸变形,而且 HTML 层字体渲染更清晰(交接稿 §1 也推荐此方案)。 */}
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
        <span style={{ position: "absolute", left: 0, top: -13, fontSize: 9.5, color: t.muted,
                       fontFamily: "'JetBrains Mono'" }}>token</span>
        {ticks.map((f) => (
          // 峰值那档贴着顶线往下画、0 那档贴着基线往上画,否则会分别撞上「token」单位标签和横轴日期行
          <span key={f} style={{ position: "absolute", left: 0, top: `${(1 - f) * 100}%`,
                                 transform: f === 1 ? "translateY(0)"
                                          : f === 0 ? "translateY(-100%)" : "translateY(-50%)",
                                 fontSize: 10, color: t.text2,
                                 fontFamily: "'JetBrains Mono'" }}>{f ? fmt(peak * f) : "0"}</span>
        ))}
      </div>

      {/* 横轴标签:居中于数据点 x */}
      <div style={{ position: "relative", height: 16, marginTop: 4 }}>
        {/* 抽稀序列**从末尾锚定**:最后一个标签一定落在节奏上,不会与倒数第二个挤在一起
            (实测 30d 档 `08-08` 与 `08-09` 重叠 —— 那是"强制渲染最后一个"造成的) */}
        {labels.map((d, i) => ((n - 1 - i) % Math.max(1, xTick ?? Math.ceil(n / MAX_X_LABELS)) === 0 ? (
          // 首尾不居中:最后一个点在 x=VW,居中会让一半标签溢出被裁掉(实测「08-」)
          <span key={d} style={{ position: "absolute", left: `${(x(i) / VW) * 100}%`,
                                 transform: i === 0 ? "translateX(0)"
                                          : i === n - 1 ? "translateX(-100%)" : "translateX(-50%)",
                                 fontSize: 10, color: t.text2,
                                 whiteSpace: "nowrap", fontFamily: "'JetBrains Mono'" }}>
            {d.length > 10 ? d.slice(11) + ":00" : d.slice(5)}
          </span>
        ) : null))}
      </div>

      {/* 浮层:130px / 60% 不透明 / blur6 / >55% 翻边(§2) */}
      {hv != null && (
        <div key={`tip-${hv}`} style={{
          position: "absolute", top: 8, pointerEvents: "none", width: 130,
          left: `calc(${(x(hv) / VW) * 100}% + ${x(hv) / VW <= 0.55 ? 14 : -144}px)`,
          background: "rgba(10,13,16,.6)", backdropFilter: "blur(6px)",
          border: "1px solid rgba(255,255,255,.12)", borderRadius: 8, padding: "7px 9px",
          fontFamily: "'JetBrains Mono'", color: "#eef2f7",
        }}>
          <div style={{ fontSize: 9.5, color: "#8a93a0", marginBottom: 4 }}>
            {tipTitle ? tipTitle(hv) : labels[hv]}
          </div>
          {/* layers 是自下而上的**降序**(大的贴基线),浮层直接按这个顺序列 = 大的先读 */}
          {layers.map((L, li) => {
            const v = li === 0 ? tops[0][hv] : tops[li][hv] - tops[li - 1][hv];
            return v > 0 ? (
              <div key={L.key} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10,
                                        padding: "1px 0" }}>
                <span style={{ width: 7, height: 7, borderRadius: 2, background: L.color, flexShrink: 0 }} />
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>{L.name}</span>
                <span style={{ fontVariantNumeric: "tabular-nums" }}>{fmt(v)}</span>
              </div>
            ) : null;
          })}
          <div style={{ borderTop: "1px solid rgba(255,255,255,.12)", marginTop: 4, paddingTop: 4,
                        display: "flex", justifyContent: "space-between", fontSize: 10,
                        color: t.accent, fontWeight: 700 }}>
            <span>总计</span><span>{fmt(tops[tops.length - 1][hv])}</span>
          </div>
        </div>
      )}
    </div>
  );
}
