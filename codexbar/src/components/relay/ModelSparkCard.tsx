import React, { useState } from "react";
import { MONO } from "./RelayBits";
import { fmtTok } from "../../traffic";

/**
 * 单个模型的小图卡 —— 1:1 复刻 `中转站-交接说明.md` §4「模型小图阵（2c）」。
 *
 * ## 为什么从堆叠面积图换成每模型一张卡
 *
 * 堆叠图回答的是"这段时间的构成"，而这一页真正被问的是"**哪个模型在烧钱**"。
 * 堆叠图里占比 0.1% 的模型是一条看不见的细线；小图卡里它有自己的 y 轴、
 * 自己的峰值和实扣，一眼可读。代价是失去"总量随时间"的那条线 —— 由 KPI 条的
 * 「总 token + 环比」承担。
 *
 * ## ★ 每卡独立 y 轴，所以**卡与卡之间的曲线高度不可比**
 *
 * 这是设计稿明写的取舍（"每张卡独立 y 轴"），页头也照稿写了这句话。
 * 可比的量在数字上：token、占比、底部那条相对 Top1 的胶囊条。
 */

/** Catmull-Rom → 三次贝塞尔。设计稿 §4 指定的平滑方式，与原型 `smooth()` 逐字同式。 */
export function smoothPath(pts: Array<[number, number]>): string {
  if (!pts.length) return "";
  if (pts.length === 1) return `M0 ${pts[0][1].toFixed(1)} L220 ${pts[0][1].toFixed(1)}`;
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

export interface ModelCardData {
  model: string;
  color: string;
  /** 窗口内逐日 token，已与公共日期轴对齐。 */
  series: number[];
  labels: string[];
  totalTok: number;
  totalReq: number;
  /** 已格式化好的实扣（币种/可加性由调用方判定，这里只画）。 */
  costText: string;
  /** 占全部模型的比例，0..1。 */
  pct: number;
  /** 相对 Top1 的比例，0..1 —— 底部胶囊条。 */
  bar: number;
}

const W = 220, H = 40;

export default function ModelSparkCard({ d, focused, dimmed, onPick }: {
  d: ModelCardData;
  focused: boolean;
  dimmed: boolean;
  onPick: () => void;
}): React.ReactElement {
  const [hov, setHov] = useState<number | null>(null);
  const n = d.series.length;
  // ★ 每卡独立 y 轴：`max × 1.1`。全 0 时用一个正的分母，否则整条线贴顶或 NaN。
  const mx = Math.max(...d.series, 0.001) * 1.1;
  const pts: Array<[number, number]> = n > 1
    ? d.series.map((v, k) => [k / (n - 1) * W, H - (v / mx) * (H - 4) - 2])
    : [[0, H - (d.series[0] ?? 0) / mx * (H - 4) - 2],
       [W, H - (d.series[0] ?? 0) / mx * (H - 4) - 2]];
  const k = hov ?? 0;
  const hovLeft = n > 1 ? `${(k / (n - 1) * 100).toFixed(2)}%` : "50%";
  const hovTop = `${(pts[Math.min(k, pts.length - 1)][1] / H * 100).toFixed(1)}%`;
  // ★ 过 55% 翻边，浮层才不会掉出卡外（本仓 UI 规范，与流量总览一致）。
  const shift = k / Math.max(n - 1, 1) > 0.55
    ? "translateX(calc(-100% - 6px))" : "translateX(6px)";

  return (
    <div data-model-card={d.model} data-model-focused={focused ? "1" : undefined}
         onClick={onPick}
         style={{ background: "#10161d",
                  border: `1px solid ${focused ? d.color : "rgba(255,255,255,.07)"}`,
                  borderRadius: 13, padding: "13px 15px", cursor: "pointer",
                  transition: "border-color .15s, transform .15s, opacity .15s",
                  opacity: dimmed ? 0.35 : 1, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <span style={{ width: 9, height: 9, borderRadius: 3, background: d.color,
                       flex: "none" }} />
        <span style={{ fontSize: 12.5, fontWeight: 700, fontFamily: MONO, whiteSpace: "nowrap",
                       overflow: "hidden", textOverflow: "ellipsis" }}>{d.model}</span>
        <span style={{ marginLeft: "auto", fontSize: 10, color: "#8a93a0", fontFamily: MONO,
                       flex: "none" }}>{(d.pct * 100).toFixed(1)}%</span>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 8 }}>
        <span style={{ fontSize: 22, fontWeight: 700, fontFamily: MONO,
                       fontVariantNumeric: "tabular-nums" }}>{fmtTok(d.totalTok)}</span>
        <span style={{ fontSize: 10.5, color: "#8a93a0", fontFamily: MONO }}>
          {d.totalReq} 轮
        </span>
      </div>

      <div style={{ position: "relative", marginTop: 6 }}
           onMouseMove={(e) => {
             const r = e.currentTarget.getBoundingClientRect();
             const kk = Math.round((e.clientX - r.left) / r.width * (n - 1));
             setHov(Math.max(0, Math.min(n - 1, kk)));
           }}
           onMouseLeave={() => setHov(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: H, display: "block" }}
             preserveAspectRatio="none">
          {/* ★ `data-spark` 是这条线的**身份**。没有它时闸只能按 `<path d="M...">`
              匹配，而侧栏图标里全是 svg path —— 实测第一条命中的是个图标，
              于是"7 个点"被读成 1 个。断言必须打在被测元素上，不是"页面上第一个像它的东西"。 */}
          <path data-spark={d.model} d={smoothPath(pts)} fill="none" stroke={d.color} strokeWidth="2"
                strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {hov !== null && (
          <>
            <div style={{ position: "absolute", top: 0, bottom: 0, left: hovLeft, width: 1,
                          background: "rgba(255,255,255,.3)", pointerEvents: "none" }} />
            <div style={{ position: "absolute", left: hovLeft, top: hovTop, width: 7, height: 7,
                          borderRadius: "50%", background: d.color, border: "2px solid #10161d",
                          transform: "translate(-50%,-50%)", pointerEvents: "none" }} />
            <div data-model-tip style={{
              position: "absolute", top: -4, left: hovLeft, transform: shift,
              background: "rgba(10,13,16,.6)", backdropFilter: "blur(6px)",
              border: "1px solid rgba(255,255,255,.12)", borderRadius: 6, padding: "4px 7px",
              fontFamily: MONO, fontSize: 9.5, whiteSpace: "nowrap", pointerEvents: "none",
              zIndex: 3,
            }}>
              <span style={{ color: "#8a93a0" }}>{d.labels[k]?.slice(5) ?? ""}</span>{" "}
              <b>{fmtTok(d.series[k] ?? 0)}</b>
            </div>
          </>
        )}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 10,
                    color: "#6b7480", fontFamily: MONO }}>
        <span>峰 {fmtTok(Math.max(...d.series, 0))}/日</span>
        <span>实扣 <b style={{ color: "#E0A21C" }}>{d.costText}</b></span>
      </div>
      <div style={{ marginTop: 7, height: 3, borderRadius: 2, background: "rgba(255,255,255,.07)",
                    overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${(d.bar * 100).toFixed(1)}%`, background: d.color,
                      borderRadius: 2, transition: "width .4s" }} />
      </div>
    </div>
  );
}
