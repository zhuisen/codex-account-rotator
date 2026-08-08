export interface Series {
  key: string;
  color: string;
  /** 与 labels 等长 */
  values: number[];
}

/**
 * 单调三次插值(Fritsch–Carlson)生成的平滑路径。
 *
 * ★ 为什么不用普通 Catmull-Rom / 基数样条:它们在数值陡降时会**过冲**，把曲线拉到基线以下。
 * token 量不可能是负的，画出低于 0 的填充区就是在画一个不存在的事实（而且堆叠模式下相邻两条带
 * 会互相穿插）。单调插值的性质保证：区间内曲线不会超出两端点的值域，所以既圆润又不说谎。
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
  for (let i = 1; i < n - 1; i++) {
    // 极值点处切线归零 —— 否则曲线会在波峰/波谷冲出数据范围
    m.push(d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2);
  }
  m.push(d[n - 2]);

  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / d[i], b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const tau = 3 / Math.sqrt(s);
      m[i] = tau * a * d[i];
      m[i + 1] = tau * b * d[i];
    }
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

/** 把一条折线路径闭合成填充区(落到基线)。 */
function closeToBaseline(path: string, x0: number, x1: number, base: number): string {
  return `${path} L ${x1.toFixed(2)} ${base.toFixed(2)} L ${x0.toFixed(2)} ${base.toFixed(2)} Z`;
}

export default function AreaChart({ labels, series, stacked, height = 200, fmt, muted, grid, onHover }: {
  labels: string[];
  series: Series[];
  /** true=按 series 堆叠(分模型)，false=各自独立(单条总量) */
  stacked: boolean;
  height?: number;
  fmt: (n: number) => string;
  muted: string;
  grid: string;
  onHover?: (i: number | null) => void;
}) {
  const W = 1000, PL = 46, PR = 12, PT = 12, PB = 22;
  const n = labels.length;
  if (!n) return null;
  const x = (i: number) => PL + (n === 1 ? (W - PL - PR) / 2 : i * (W - PL - PR) / (n - 1));
  const base = height - PB;

  // 堆叠:逐点累加；非堆叠:各自独立。峰值决定 y 轴。
  const stacks: number[][] = [];
  if (stacked) {
    const acc = new Array(n).fill(0);
    for (const s of series) {
      const top = s.values.map((v, i) => (acc[i] += v));
      stacks.push([...top]);
    }
  }
  const peak = Math.max(1, stacked
    ? Math.max(...(stacks[stacks.length - 1] ?? [0]))
    : Math.max(...series.flatMap(s => s.values)));
  const y = (v: number) => PT + (1 - v / peak) * (base - PT);

  const gridY = [0, 0.25, 0.5, 0.75, 1];
  const tick = Math.max(1, Math.ceil(n / 8));

  return (
    <svg viewBox={`0 0 ${W} ${height}`} style={{ width: "100%", height, display: "block" }}
      onMouseLeave={() => onHover?.(null)}>
      {gridY.map(f => (
        <g key={f}>
          <line x1={PL} x2={W - PR} y1={y(peak * f)} y2={y(peak * f)} stroke={grid} strokeWidth={1} />
          <text x={PL - 6} y={y(peak * f) + 3} textAnchor="end" fill={muted} fontSize={9} fontFamily="'JetBrains Mono'">{fmt(peak * f)}</text>
        </g>
      ))}

      {/* 堆叠时从最上层往下画，这样下层的填充不会被上层盖住边界 */}
      {(stacked ? [...series].map((s, si) => ({ s, si })).reverse() : series.map((s, si) => ({ s, si }))).map(({ s, si }) => {
        const vals = stacked ? stacks[si] : s.values;
        const pts = vals.map((v, i) => [x(i), y(v)] as [number, number]);
        const line = monotonePath(pts);
        return (
          <g key={s.key}>
            {/* ★ 堆叠带必须**不透明**。每条带都是填到基线的完整面积、自上而下叠画,靠上层被下层覆盖
                来形成band。半透明会让相邻两层混色 —— 实测 0.55 时青压蓝糊成第三种颜色,根本读不出
                哪段属于哪个模型。单条总量图反而要半透明,那是"线下淡填充"的观感,不存在遮挡问题。 */}
            <path d={closeToBaseline(line, x(0), x(n - 1), base)} fill={s.color} opacity={stacked ? 1 : 0.15} />
            <path d={line} fill="none"
              stroke={stacked ? "rgba(0,0,0,.28)" : s.color}
              strokeWidth={stacked ? 1 : 2} strokeLinecap="round" strokeLinejoin="round" />
          </g>
        );
      })}

      {labels.map((d, i) => i % tick === 0 && (
        <text key={d} x={x(i)} y={height - 6} textAnchor="middle" fill={muted} fontSize={9} fontFamily="'JetBrains Mono'">{d.slice(5)}</text>
      ))}

      {/* 透明命中带:悬停读数，不影响观感 */}
      {onHover && labels.map((d, i) => (
        <rect key={`h${d}`} x={x(i) - (W - PL - PR) / (n * 2)} y={PT} width={(W - PL - PR) / n} height={base - PT}
          fill="transparent" onMouseEnter={() => onHover(i)} />
      ))}
    </svg>
  );
}
