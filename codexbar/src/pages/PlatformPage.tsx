import { useMemo, useState } from "react";
import { type Theme, platformColor, modelColor } from "../theme";
import { costOf, fmtUSD, priceOf, isPriced } from "../rates";
import StackedArea, { type Layer } from "../components/StackedArea";
import Seg from "../components/Seg";
import type { TrafficData, Range } from "../traffic";
import { RANGES, rangeLabel, bucketsFor, sumBuckets, costOfBucket, fmtTok } from "../traffic";

const AMBER = "#E0A21C";
const SRC: Record<string, string> = {
  claude: "~/.claude/projects/**/*.jsonl",
  codex: "~/.codex/sessions/**/rollout-*.jsonl",
  grok: "~/.grok/sessions/*/*/updates.jsonl",
};

/** 平台详情(交接稿 §5–§8)。 */
export default function PlatformPage({ t, data, pk, range, setRange, onBack, busy }: {
  t: Theme; data: TrafficData | null; pk: string;
  range: Range; setRange: (r: Range) => void; onBack: () => void; busy: boolean;
}): React.ReactElement {
  const [mode, setMode] = useState<"models" | "total">("models");
  const [iso, setIso] = useState<Set<string>>(new Set());   // §7 被隔离的模型
  const c = platformColor(pk);

  const v = useMemo(() => {
    if (!data?.platforms[pk]) return null;
    const { labels, buckets } = bucketsFor(data, pk, range);
    const agg = sumBuckets(buckets);
    const models = Object.entries(agg.models)
      .map(([m, mv]) => ({ m, ...mv, cost: costOf(mv, m, pk) }))
      .sort((a, b) => b.total - a.total);
    // 全池占比
    let grand = 0;
    for (const k of Object.keys(data.platforms)) grand += sumBuckets(bucketsFor(data, k, range).buckets).total;
    return { labels, buckets, agg, models, cost: costOfBucket(agg, pk), grand };
  }, [data, pk, range]);

  const shown = (v?.models ?? []).filter((m) => !iso.has(m.m));
  // 与总览一致:图层自下而上 = 占比**降序**(大的贴基线,小的压在上面)。`shown` 已是降序。
  const layers: Layer[] = mode === "models"
    ? shown.map((m) => ({
        key: m.m, name: m.m, color: modelColor(m.m),
        values: (v?.buckets ?? []).map((b) => b.models?.[m.m]?.total ?? 0),
      }))
    : [{ key: "total", name: "总量", color: c, values: (v?.buckets ?? []).map((b) => b.total) }];

  const isToday = range === "today";
  const days = Math.max(1, v?.labels.length ?? 1);
  const kpis: [string, string, string?][] = [
    // 与总览同名(用户 2026-08-09 把总览的「合计 token」改成「总 token」),两页别叫两个名
    ["总 token", fmtTok(v?.agg.total ?? 0)],
    ["请求轮数", (v?.agg.rounds ?? 0).toLocaleString()],
    [isToday ? "小时均" : "日均", fmtTok((v?.agg.total ?? 0) / days)],
    ["总费用 · 等效API", fmtUSD(v?.cost ?? 0), AMBER],
    [isToday ? "小时均费用" : "日均费用", fmtUSD((v?.cost ?? 0) / days), AMBER],
    ["占全池", v?.grand ? `${((v.agg.total / v.grand) * 100).toFixed(1)}%` : "—", c],
  ];

  // 费率卡的折算说明:该平台四类 token 的真实构成
  const mix = useMemo(() => {
    const a = v?.agg;
    if (!a || !a.total) return null;
    const p = (x: number) => `${((x / a.total) * 100).toFixed(1)}%`;
    return `缓存读 ${p(a.cache_read)} · 输入 ${p(a.uncached_in)} · 缓存写 ${p(a.cache_write)} · 输出 ${p(a.output)}`;
  }, [v]);


  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%", overflow: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 11 }}>
        <span onClick={onBack} style={{ fontSize: 12, padding: "3px 10px", borderRadius: 8, cursor: "pointer",
                                        border: `1px solid ${t.ghostBorder}`, color: t.text2, whiteSpace: "nowrap" }}>
          ← 总览
        </span>
        <span style={{ width: 10, height: 10, borderRadius: "50%", background: c, flexShrink: 0 }} />
        <span style={{ fontSize: 22, fontWeight: 700, whiteSpace: "nowrap" }}>
          {data?.platforms[pk]?.name ?? pk} 消耗
        </span>
        <span style={{ fontSize: 11, color: t.faint, fontFamily: "'JetBrains Mono'", overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{SRC[pk] ?? ""}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <Seg opts={["models", "total"] as const} cur={mode} on={setMode}
               label={(x) => (x === "models" ? "分模型" : "总量")} t={t} />
          <Seg opts={RANGES} cur={range} on={setRange} label={rangeLabel} t={t} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 24, padding: "12px 18px", marginBottom: 11, borderRadius: 12,
                    background: t.isDark ? "#0e1319" : t.cardBg, border: `1px solid ${t.cardBorder}` }}>
        {kpis.map(([k, val, col]) => (
          <div key={k} style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10, color: "#10E0E0", fontFamily: "'JetBrains Mono'",
                          letterSpacing: ".04em", whiteSpace: "nowrap" }}>{k}</div>
            <div style={{ fontSize: 20, fontWeight: 700, marginTop: 3, whiteSpace: "nowrap",
                          fontVariantNumeric: "tabular-nums", color: col ?? t.text }}>{val}</div>
          </div>
        ))}
      </div>

      {busy && !data && <div style={{ fontSize: 12, color: t.muted }}>扫描中…</div>}

      {!!v?.labels.length && (
        // ★ key 同时带 `mode`:切「分模型 ↔ 总量」也是换了一整个数据集。不带 `iso` —— 隔离模型只改
        //    图层不改日期,hover 索引仍然指同一天,重建反而会把用户停着的浮层弄没。
        <StackedArea key={`${range}:${mode}`}
                     labels={v.labels} layers={layers} height={190} fmt={fmtTok} t={t}
                     tipTitle={(i) => (isToday ? `今日 ${v.labels[i].slice(11)}:00 · 分模型`
                                               : `${v.labels[i]} · 分模型`)} />
      )}

      {/* 模型行 —— 点击隔离(§7) */}
      <div style={{ marginTop: 12 }}>
        {v?.models.map((m) => {
          const off = iso.has(m.m);
          return (
            <div key={m.m} onClick={() => setIso((s) => {
              const n = new Set(s); n.has(m.m) ? n.delete(m.m) : n.add(m.m); return n;
            })}
                 style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10.5, padding: "3px 4px",
                          cursor: "pointer", opacity: off ? 0.38 : 1, transition: "opacity .15s" }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, flexShrink: 0,
                             background: modelColor(m.m), opacity: off ? 0.3 : 1 }} />
              <span style={{ width: 168, fontFamily: "'JetBrains Mono'", color: t.text2, overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.m}</span>
              <div style={{ flex: 1, height: 6, borderRadius: 3, background: t.barTrack, overflow: "hidden", minWidth: 30 }}>
                <div style={{ width: `${(m.total / Math.max(1, v.models[0].total)) * 100}%`,
                              height: "100%", background: modelColor(m.m) }} />
              </div>
              <span style={{ width: 62, textAlign: "right", fontFamily: "'JetBrains Mono'",
                             fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>{fmtTok(m.total)}</span>
              <span style={{ width: 48, textAlign: "right", fontFamily: "'JetBrains Mono'", color: t.muted }}>
                {((m.total / Math.max(1, v.agg.total)) * 100).toFixed(1)}%
              </span>
              <span style={{ width: 62, textAlign: "right", fontFamily: "'JetBrains Mono'", color: t.faint }}>
                {m.rounds.toLocaleString()}轮
              </span>
              <span style={{ width: 62, textAlign: "right", fontFamily: "'JetBrains Mono'", color: AMBER,
                             fontWeight: 700 }}>{fmtUSD(m.cost)}</span>
            </div>
          );
        })}
      </div>

      {/* §8 费率卡 */}
      {!!v?.models.length && (
        <div style={{ marginTop: 12, marginBottom: 6, borderRadius: 12, padding: "13px 16px",
                      background: t.isDark ? "#0e1319" : t.cardBg, border: `1px solid ${t.cardBorder}` }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
            <span style={{ fontSize: 12.5, fontWeight: 700 }}>费率卡 · API 牌价</span>
            <span style={{ fontSize: 10, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{mix}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 74px 74px 74px 84px", gap: "3px 8px",
                        fontSize: 10, fontFamily: "'JetBrains Mono'" }}>
            {["模型", "输入", "缓存读", "输出", "折算费用"].map((h, i) => (
              <span key={h} style={{ fontSize: 9.5, color: t.muted, letterSpacing: ".08em",
                                     textAlign: i ? "right" : "left" }}>{h.toUpperCase()}</span>
            ))}
            {v.models.map((m) => {
              const p = priceOf(m.m, pk);
              const known = isPriced(m.m);
              return (
                <FragRow key={m.m} t={t} name={m.m} known={known}
                         cells={[`$${p.in.toFixed(2)}`, `$${p.cacheRead.toFixed(3)}`,
                                 `$${p.out.toFixed(2)}`, fmtUSD(m.cost)]} />
              );
            })}
          </div>
          <div style={{ fontSize: 9.5, color: t.faint, marginTop: 8, lineHeight: 1.5 }}>
            缓存读 = 输入价 10%(Grok 为 85 折上下) · Anthropic 缓存写 1.25x · 数据源 2026-08 牌价。
            <br />
            <span style={{ color: "#E0901C" }}>⚠️ 标 * 的型号不在交接稿费率表里</span>
            （稿子列的是 gpt-5.3-codex / grok-4.5-code，本机实际在跑 gpt-5.6-sol / gpt-5.5 / grok-4.5-build），
            按同平台最接近档位估算，**不是准数**。费率表在 <code>src/rates.ts</code>，价签变了改那里。
            <br />
            费用 = 四类 token 分别乘单价求和，是<b>等效 API 成本</b>；订阅制下并非实付。
          </div>
        </div>
      )}
    </div>
  );
}

function FragRow({ t, name, known, cells }: { t: Theme; name: string; known: boolean; cells: string[] }) {
  return (
    <>
      <span style={{ color: t.text2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {name}{known ? "" : <span style={{ color: "#E0901C" }}> *</span>}
      </span>
      {cells.map((c, i) => (
        <span key={i} style={{ textAlign: "right", fontVariantNumeric: "tabular-nums",
                               color: i === 1 ? "#10E0E0" : i === 3 ? AMBER : t.text2,
                               fontWeight: i === 3 ? 700 : 400 }}>{c}</span>
      ))}
    </>
  );
}
