import { useState } from "react";
import type { Theme } from "../theme";

import { fmtUSD } from "../rates";
import { fmtTok, cacheModeLabel, type TodayView, type CacheMode } from "../traffic";

/**
 * 摘要行专用的紧凑金额（用户 2026-08-24 定稿：「把金额变成整数，少了三个占位符」）。
 *
 * 菜单栏固定 352px，摘要行四块（总量 / 金额 / 环比 / 刷新时刻）实测差 ~20px 就装不下，
 * 而 `$861.76` 的小数点加两位正好 3 个等宽字符 ≈ 23px —— 取整就够了，不必动别的。
 *
 * ★ **`< $10` 仍保两位**：`$0.101` 取整会变成 `$0`，把「有成本」显示成「零成本」——
 * 那是项目铁律「读不到 ≠ 确实没有」的同族错误。省字符不能省到改变含义。
 * 详情页与主窗仍用 `fmtUSD`（那里空间够，精度更有用）。
 */
function compactUSD(n: number): string {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}K`;   // $12.3K
  if (n >= 10) return `$${Math.round(n)}`;              // $862
  return fmtUSD(n);                                     // $9.87 / $0.101
}

const AMBER = "#E0A21C";
const UP = "#27B26B", DOWN = "#E0524D";

/** 交接稿 §2 的 svg 尺寸。这里是**独立的一份小图**,不复用主窗口的 `StackedArea`:
 *  弹窗要的是"无 tooltip、无坐标轴刻度、无 hover"的轻量版,把那些都做成开关反而会让主图长出
 *  一堆只有弹窗用的分支(要明细走底栏「打开流量总览 ↗」,交接稿 §5 就是这么定的)。 */
const VW = 380, VH = 104;
/** 横轴给 6 个时刻标签(§2)。 */
const X_LABELS = 6;

/**
 * Catmull-Rom(§2 明写"与主窗同算法")。
 *
 * ⚠️ 与主窗口的实际实现有意保持一致地**换成单调三次插值**是不必要的:这里每层都是"填到基线"的
 * 独立面积、自下而上叠画,而且不显示数值,轻微过冲不会造成误读。真要改也只改这一处。
 */
function smooth(pts: [number, number][]): string {
  if (!pts.length) return "";
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(i - 1, 0)], p1 = pts[i];
    const p2 = pts[i + 1], p3 = pts[Math.min(i + 2, pts.length - 1)];
    d += ` C${(p1[0] + (p2[0] - p0[0]) / 6).toFixed(1)} ${(p1[1] + (p2[1] - p0[1]) / 6).toFixed(1)}`
       + ` ${(p2[0] - (p3[0] - p1[0]) / 6).toFixed(1)} ${(p2[1] - (p3[1] - p1[1]) / 6).toFixed(1)}`
       + ` ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

/** 只有一个采样点时柱子的宽度(viewBox 单位)。 */
const COL_W = VW * 0.12;

/**
 * ★ **一个小时桶要画成柱,不是面积**(2026-08-13 修)。
 *
 * 一条带至少要两个采样点,原来 `vals.length < 2` 直接 `return ""` —— 于是每天 **00:00–00:59**
 * 整块图必然空白(实测:6 层 path 的 `d` 全是空串,而 svg 仍占满 104 高,就是那块空档)。
 * 补柱子而不是补一条横跨全宽的面积:后者会把"这一个小时"画成横跨整条时间轴的一段,
 * 那是在画一个没发生的事实。一次离散测量本来就该是柱。
 */
function area(vals: number[], yMax: number): string {
  if (!vals.length) return "";
  if (vals.length === 1) {
    const y = (VH - (vals[0] / yMax) * VH).toFixed(1);
    const x0 = ((VW - COL_W) / 2).toFixed(1), x1 = ((VW + COL_W) / 2).toFixed(1);
    return `M${x0} ${VH} L${x0} ${y} L${x1} ${y} L${x1} ${VH} Z`;
  }
  const pts = vals.map((v, i) => [
    (i / (vals.length - 1)) * VW,
    VH - (v / yMax) * VH,
  ] as [number, number]);
  return `${smooth(pts)} L ${VW} ${VH} L 0 ${VH} Z`;
}

const hourLabel = (h: string): string => `${h.slice(11)}:00`;

const IconRefresh = ({ spin }: { spin?: boolean }) => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       style={{ animation: spin ? "cbSpin .8s linear infinite" : "none", transformOrigin: "center" }}>
    <path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4" />
  </svg>
);

/** 菜单栏「今日」Tab · 交接稿 `菜单栏v3-交接说明.md` §2(1b 迷你仪表盘)。 */
export default function MenuBarToday({ t, view, colors, cacheMode, refreshedAt, busy,
                                      onRefresh, onOpenPlatform, onOpenOverview }: {
  t: Theme;
  view: TodayView | null;
  /**
   * 缓存计入口径。数字已经在 `useTraffic` 出口按它重塑过,这里**只负责把口径标出来** ——
   * 不标的话,弹窗会把 34.2B 静默显示成 0.46B。
   * 标在「峰值」那一行而不是摘要行:摘要行实测只剩 ~44px 余量,徽标要 ~68px,会挤到溢出。
   */
  cacheMode: CacheMode;
  /** 平台色,由 scan.py 的注册表下发(见 traffic.ts 的 colorOf) */
  colors: Record<string, string>;
  /** 数据的生成时刻(快照时间),不是"现在" */
  refreshedAt: number | null;
  busy: boolean;
  onRefresh: () => void;
  onOpenPlatform: (key: string) => void;
  /** 点图表任意处 → 主窗流量总览(用户 2026-08-09 要求) */
  onOpenOverview: () => void;
}): React.ReactElement {
  const [hvRaw, setHv] = useState<number | null>(null);
  if (!view) {
    return (
      <div className="mb-today" style={{ padding: "26px 16px", textAlign: "center",
                                         fontSize: 11.5, color: t.muted }}>
        {busy ? "正在首次汇总本机 CLI 记录…" : "暂无数据"}
      </div>
    );
  }

  const { hours, series, per } = view;
  // 各层**累计**上沿,自下而上叠画;`series` 已是占比降序 = 大的贴基线(与主窗口同规则)。
  const acc = new Array(hours.length).fill(0) as number[];
  const cum = series.map((s) => {
    s.values.forEach((v, i) => { acc[i] += v; });
    return { key: s.key, top: [...acc] };
  });
  const yMax = Math.max(1, ...acc) * 1.08;

  /**
   * ★ 横轴标签有两处**刻意偏离交接稿**,都是为了不让坐标轴说假话:
   *
   * 1. 稿子写死 `00:00 04:00 … 20:00` 六个标签。真实数据只覆盖**已过去的小时**(现在是上午就只有
   *    00:00–11:00),照抄会让坐标轴标出一个当天还没发生的时间范围。所以标签从真实小时里取。
   * 2. 稿子用 `justify-content:space-between` 平铺。那要求刻度在**索引上等距**;从 12 个小时里挑
   *    6 个必然挑出 0/2/4/7/9/11 这种不等距序列,平铺后标签落点(20%)和它代表的数据点(18%)对不上 ——
   *    坐标轴指错位置。这里改成**取规整的整点步长(2/3/4/6/8/12 里最小的够用者)+ 按真实 x 绝对定位**。
   *    满一天(n=24)时步长正好是 4,标签退化成稿子里那六个,像素一致。
   */
  const n = hours.length;
  const step = [1, 2, 3, 4, 6, 8, 12].find((s) => Math.ceil(n / s) <= X_LABELS) ?? 12;
  const tickIdx = hours.map((_, i) => i).filter((i) => i % step === 0);

  const d = view.deltaPct;
  // 索引一旦越界就作废(小时桶会随时间增长)。与主图同一条纪律:clamp 只防越界,
  // 真正换数据集靠调用方的 key —— 这里数据集不换(恒是"今日"),所以 clamp 足够。
  const hv = hvRaw != null && hvRaw < hours.length ? hvRaw : null;

  return (
    <div className="mb-today">
      {/* ★ 摘要行:悬浮图表时**就地替换**成那一小时的读数,不弹浮层。
          412px 的弹窗里,主窗那个 130px 浮层要占掉图表 34% 宽、还会盖住相邻的小时格;
          而整块图现在又是"点了跳主窗"的按钮,再叠一个悬浮读数会让同一块区域既像可读区
          又像按钮。就地替换零遮挡、鼠标移开自动复原、且完全不影响点击跳转。 */}
      <div className="mb-today-sum">
        <span className="mb-today-tot">
          {fmtTok(hv != null ? view.hourTok[hv] : view.totalTok)}
        </span>
        <span className="mb-today-cost" style={{ color: AMBER }}>
          {compactUSD(hv != null ? view.hourCost[hv] : view.totalCost)}
        </span>
        {hv != null ? (
          <span className="mb-today-delta" style={{ color: t.accentText, background: t.accent }}>
            {hourLabel(hours[hv])}
          </span>
        ) : d != null ? (
          <span className="mb-today-delta" style={{
            color: d >= 0 ? UP : DOWN,
            background: d >= 0 ? "rgba(39,178,107,.12)" : "rgba(224,82,77,.12)",
          }}>{d >= 0 ? "↑" : "↓"}{Math.abs(d).toFixed(1)}%</span>
        ) : null}
        {/* ★ 刷新时刻做成按钮:快照是"上次扫描的成品",不点就一直是那一份。用户 2026-08-09 要求
            能自主刷新 —— 把时间戳本身变成入口,比再塞一个图标省一格宽度,而且"这个数是几点的"
            和"重取"本来就是同一件事。 */}
        {hv != null ? (
          <span className="mb-today-when hover" style={{ color: t.text2, cursor: "default" }}>
            {breakdown(series, colors, hv)}
          </span>
        ) : (
          <span className="mb-today-when" onClick={busy ? undefined : onRefresh}
                title={busy ? "扫描中…" : "重新扫描本机 CLI 记录(只读本地文件,不消耗额度)"}
                style={{ color: busy ? t.accent : t.muted, cursor: busy ? "default" : "pointer" }}>
            <IconRefresh spin={busy} />
            {hours[0].slice(5, 10)}
            {refreshedAt ? ` · 刷新 ${new Date(refreshedAt * 1000).toTimeString().slice(0, 5)}` : ""}
          </span>
        )}
      </div>

      {/* 小时堆叠图 —— 无 tooltip(§5:要明细走底栏「打开流量总览 ↗」)。
          ★ 整块可点 → 直接开主窗总览:弹窗里既然不给 tooltip,"想看细节"这个意图最自然的落点
          就是图本身,而不是逼用户去找底栏那个按钮(用户 2026-08-09 指定)。 */}
      <div className="mb-today-chart mb-today-chart-click" onClick={onOpenOverview}
           onMouseLeave={() => setHv(null)}
           title="打开主窗口的 AI用量信息">
        <div className="mb-today-peak" style={{ color: t.muted }}>
          {cacheMode !== "full" && (
            <span style={{ color: AMBER, fontWeight: 700 }}>{cacheModeLabel(cacheMode)} · </span>
          )}
          {view.peak ? `峰值 ${fmtTok(view.peak.v)} · ${hourLabel(view.peak.hour)}` : "今日暂无用量"}
        </div>
        <svg viewBox={`0 0 ${VW} ${VH}`} style={{ width: "100%", height: "auto", display: "block" }}>
          {/* 自上而下画(最后一层在最下面),靠遮挡形成带 —— 与稿子的 a3/a2/a1 同序 */}
          {[...cum].reverse().map((c) => (
            <path key={c.key} d={area(c.top, yMax)} fill={colors[c.key]} />
          ))}
          <line x1={0} x2={VW} y1={VH - 0.5} y2={VH - 0.5}
                stroke="rgba(255,255,255,.16)" strokeWidth={1} />
          {hv != null && (
            <line x1={xAt(hv, n)} x2={xAt(hv, n)} y1={0} y2={VH}
                  stroke="rgba(255,255,255,.34)" strokeWidth={1}
                  vectorEffect="non-scaling-stroke" pointerEvents="none" />
          )}
          {/* 命中带铺满绘图区。**不吃 click** —— 点击照旧冒泡到外层的"打开流量总览"。 */}
          <rect x={0} y={0} width={VW} height={VH} fill="transparent"
                onMouseMove={(e) => {
                  const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
                  const i = Math.round(((e.clientX - r.left) / r.width) * (n - 1));
                  setHv(Math.max(0, Math.min(n - 1, i)));
                }} />
        </svg>
        <div className="mb-today-xaxis" style={{ color: t.muted }}>
          {tickIdx.map((i) => (
            // 首个左对齐、末个右对齐,其余居中 —— 否则两端各有一半标签溢出被裁(主图同款处理)
            <span key={i} style={{
              position: "absolute", left: `${n === 1 ? 50 : (i / (n - 1)) * 100}%`,
              transform: i === 0 ? "translateX(0)"
                       : i === n - 1 ? "translateX(-100%)" : "translateX(-50%)",
            }}>{hourLabel(hours[i])}</span>
          ))}
        </div>
      </div>

      {/* 平台图例 —— 点一行进主窗对应平台详情 */}
      <div className="mb-today-legend">
        {per.map((p) => (
          <div key={p.key} className="mb-today-row" onClick={() => onOpenPlatform(p.key)}>
            <span className="mb-today-swatch" style={{ background: colors[p.key] }} />
            <span className="mb-today-name">{p.name}</span>
            <span className="mb-today-pct" style={{ color: t.muted }}>{p.pct.toFixed(1)}%</span>
            <span className="mb-today-tok">{fmtTok(p.tok)}</span>
            <span className="mb-today-cost-cell" style={{ color: AMBER }}>{fmtUSD(p.cost)}</span>
            <span className="mb-today-delta-cell" style={{
              color: p.deltaPct == null ? t.muted : p.deltaPct >= 0 ? UP : DOWN,
            }}>
              {p.deltaPct == null ? "—"
                : `${p.deltaPct >= 0 ? "↑" : "↓"}${Math.abs(p.deltaPct).toFixed(1)}%`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 数据点在 viewBox 里的 x。与 `area()` 的取点公式必须一致,否则参考线和曲线对不上。 */
function xAt(i: number, n: number): number {
  return n <= 1 ? VW / 2 : (i / (n - 1)) * VW;
}

/**
 * 某一小时的分平台明细,如 `●82M ●36M ●3M`。
 *
 * ★ **用色块代替平台名**。带全称的版本(`Codex 82M · Claude 36M · Kimi 3M +1`)在 412px 的面板里
 * 放不下 —— 左侧大数+金额+小时胶囊已占掉约 200px,剩给这里的只有 ~176px,而三家全称约 210px,
 * 于是在"名字"和"数值"之间折行,排版断成两截(用户 2026-08-09 实测截图)。
 *
 * 色块不是省略,是**换一种同样明确的标识**:图表正下方的平台图例用的就是这套颜色,一一对应。
 * 换掉之后四家全能列出,不再需要 `+N` —— 那个才是真的在藏数据。
 */
function breakdown(
  series: { key: string; name: string; values: number[] }[],
  colors: Record<string, string>,
  i: number,
): React.ReactElement {
  const rows = series
    .map((s) => ({ name: s.name, key: s.key, v: s.values[i] ?? 0 }))
    .filter((r) => r.v > 0)
    .sort((a, b) => b.v - a.v);
  if (!rows.length) return <span style={{ opacity: 0.6 }}>该小时无用量</span>;
  return (
    <>
      {rows.map((r) => (
        // 每项自身 nowrap:即使整组被挤,也只会在**项与项之间**断,不会把色块和数值拆散
        <span key={r.key} title={`${r.name} ${fmtTok(r.v)}`}
              style={{ display: "inline-flex", alignItems: "center", gap: 3.5,
                       whiteSpace: "nowrap" }}>
          <span style={{ width: 7, height: 7, borderRadius: 2,
                         background: colors[r.key], flexShrink: 0 }} />
          {fmtTok(r.v)}
        </span>
      ))}
    </>
  );
}
