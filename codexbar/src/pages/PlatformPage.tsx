import { useMemo, useState } from "react";
import { type Theme, platformColor, modelColor } from "../theme";
import { costOf, fmtUSD, priceOf, isPriced } from "../rates";
import StackedArea, { type Layer } from "../components/StackedArea";
import Seg from "../components/Seg";
import type { TrafficData, Range, CacheMode } from "../traffic";
import { RANGES, rangeLabel, bucketsFor, sumBuckets, costOfBucket, savingOfBucket, fmtTok,
         countsCacheRead, countsCacheWrite, countedClasses, mixParts } from "../traffic";
import KpiStrip, { type Kpi, UP, DOWN } from "../components/KpiStrip";
import CacheChip from "../components/CacheChip";

const AMBER = "#E0A21C";
const SRC: Record<string, string> = {
  claude: "~/.claude/projects/**/*.jsonl",
  codex: "~/.codex/sessions/**/rollout-*.jsonl",
  grok: "~/.grok/sessions/*/*/updates.jsonl",
};

/** 平台详情(交接稿 §5–§8)。 */
export default function PlatformPage({ t, data, raw, cacheMode, pk, range, setRange, onBack, busy }: {
  t: Theme;
  /** 已按缓存口径重塑 —— 合计/图表/费用都用它 */
  data: TrafficData | null;
  /** 未重塑。**只给费率卡的「构成」行用**(它描述数据本身由什么组成),别拿它算展示合计 */
  raw: TrafficData | null;
  cacheMode: CacheMode;
  pk: string;
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
    return { labels, buckets, agg, models, cost: costOfBucket(agg, pk),
             saving: savingOfBucket(agg, pk), grand };
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
  /**
   * 环比基准 = **本平台**在等长上一段的量与费用。与总览同一套口径,只是把范围收到单个平台。
   * App 恒取 `--days 90`,所以 7/14/30 档有完整上期;**90d 档没有上一个 90 天 → null → 显示「—」**,
   * 不拿不足 90 天的一段冒充。今日档比昨日整天。
   */
  const prev = useMemo(() => {
    if (!data) return null;
    const p = data.platforms[pk];
    if (!p) return null;
    const dayKeys = Object.keys(p.days).sort();
    let win: string[];
    if (isToday) {
      const yd = dayKeys[dayKeys.length - 2];
      win = yd ? [yd] : [];
    } else {
      const n = range as number;
      win = dayKeys.slice(-2 * n, -n);
      if (win.length !== n) win = [];
    }
    if (!win.length) return null;
    const agg = sumBuckets(win.map((d) => p.days[d]).filter(Boolean));
    return { tok: agg.total, cost: costOfBucket(agg, pk) };
  }, [data, pk, range, isToday]);

  const delta = (now: number, base: number) =>
    base > 0 ? { up: now >= base, txt: `${now >= base ? "↑" : "↓"}${(Math.abs(now - base) / base * 100).toFixed(1)}%` } : null;
  const dTok = prev ? delta(v?.agg.total ?? 0, prev.tok) : null;
  const dCost = prev ? delta(v?.cost ?? 0, prev.cost) : null;

  const kpis: Kpi[] = [
    { k: "总 token", v: fmtTok(v?.agg.total ?? 0),
      sub: dTok ? `环比 ${dTok.txt}` : "环比 —",
      subC: dTok ? (dTok.up ? UP : DOWN) : t.faint },
    { k: "请求轮数", v: (v?.agg.rounds ?? 0).toLocaleString() },
    { k: isToday ? "小时均" : "日均", v: fmtTok((v?.agg.total ?? 0) / days) },
    // 与总览同名。「等效 API」这个限定词不放在标签里 —— 页面底部费率卡最后一行有完整说明
    // (「费用 = 四类 token 分别乘单价求和,是等效 API 成本;订阅制下并非实付」),标签只留短名。
    { k: "总费用", v: fmtUSD(v?.cost ?? 0), c: AMBER,
      sub: v?.saving ? `缓存已省 ${fmtUSD(v.saving)}` : undefined },
    { k: isToday ? "小时均费用" : "日均费用", v: fmtUSD((v?.cost ?? 0) / days), c: AMBER,
      sub: dCost ? `环比 ${dCost.txt}` : undefined,
      subC: dCost ? (dCost.up ? UP : DOWN) : undefined },
    { k: "占全池", v: v?.grand ? `${((v.agg.total / v.grand) * 100).toFixed(1)}%` : "—", c },
  ];

  // 费率卡的折算说明:该平台各类 token 的**真实**构成。
  //
  // ★ 走 `raw`:它的职责是说明"这份数据由什么组成",而 `data` 已按口径把缓存清零,拿它算会输出
  //   「缓存读 0.0%」—— 那是在描述筛掉之后的残骸,不是数据的构成。
  // ★ 但**只列当前口径计入的类**(用户 2026-08-11 定稿),而且**分母也要换成这几类之和** ——
  //   否则百分比加起来不到 100(不含缓存时只有 4%),比不显示更糟。
  const mix = useMemo(() => {
    if (!raw?.platforms[pk]) return null;
    const parts = mixParts(sumBuckets(bucketsFor(raw, pk, range).buckets), cacheMode);
    return parts.length ? parts.map((p) => `${p.name} ${p.pct.toFixed(1)}%`).join(" · ") : null;
  }, [raw, pk, range, cacheMode]);


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
        <CacheChip mode={cacheMode} />
        <span style={{ fontSize: 11, color: t.faint, fontFamily: "'JetBrains Mono'", overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{SRC[pk] ?? ""}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <Seg opts={["models", "total"] as const} cur={mode} on={setMode}
               label={(x) => (x === "models" ? "分模型" : "总量")} t={t} />
          <Seg opts={RANGES} cur={range} on={setRange} label={rangeLabel} t={t} />
        </div>
      </div>

      <KpiStrip t={t} items={kpis} />

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
              {/* 同总览:轮数是要读的数字,`t.faint` 实算 2.21:1 不够 */}
              <span style={{ width: 62, textAlign: "right", fontFamily: "'JetBrains Mono'", color: t.muted }}>
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
          {/* ★ 不计入缓存读时**整列删掉**(用户 2026-08-11 定稿):那一列的单价在当前口径下
              一次都不会被乘到,留着只会让人以为费用里含了它。列宽也跟着收,不留空槽。 */}
          <div style={{ display: "grid",
                        gridTemplateColumns: countsCacheRead(cacheMode)
                          ? "1fr 74px 74px 74px 84px" : "1fr 74px 74px 84px",
                        gap: "3px 8px", fontSize: 10, fontFamily: "'JetBrains Mono'" }}>
            {(countsCacheRead(cacheMode)
              ? ["模型", "输入", "缓存读", "输出", "折算费用"]
              : ["模型", "输入", "输出", "折算费用"]).map((h, i) => (
              <span key={h} style={{ fontSize: 9.5, color: t.muted, letterSpacing: ".08em",
                                     textAlign: i ? "right" : "left" }}>{h.toUpperCase()}</span>
            ))}
            {v.models.map((m) => {
              const p = priceOf(m.m, pk);
              return (
                <FragRow key={m.m} t={t} name={m.m} known={isPriced(m.m)}
                         cells={[
                           { v: `$${p.in.toFixed(2)}` },
                           ...(countsCacheRead(cacheMode)
                             ? [{ v: `$${p.cacheRead.toFixed(3)}`, c: "#10E0E0" }] : []),
                           { v: `$${p.out.toFixed(2)}` },
                           { v: fmtUSD(m.cost), c: AMBER, bold: true },
                         ]} />
              );
            })}
          </div>
          <div style={{ fontSize: 9.5, color: t.faint, marginTop: 8, lineHeight: 1.5 }}>
            {/* 脚注只解释当前口径真正用到的价:讲一个没参与计算的折扣率,读者会以为费用里含了它 */}
            {countsCacheRead(cacheMode)
              ? "缓存读 = 输入价 10%(Grok 为 85 折上下) · "
              : "当前口径不计入缓存读,该列已隐去 · "}
            {countsCacheWrite(cacheMode)
              ? "Anthropic 缓存写 1.25x · "
              : "缓存写同样不计入 · "}
            数据源 2026-08 牌价。
            <br />
            <span style={{ color: "#E0901C" }}>⚠️ 标 * 的型号不在交接稿费率表里</span>
            （稿子列的是 gpt-5.3-codex / grok-4.5-code，本机实际在跑 gpt-5.6-sol / gpt-5.5 / grok-4.5-build），
            按同平台最接近档位估算，**不是准数**。费率表在 <code>src/rates.ts</code>，价签变了改那里。
            <br />
            费用 = {countedClasses(cacheMode)} 类 token 分别乘单价求和，是<b>等效 API 成本</b>；订阅制下并非实付。
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * ★ 单元格自带颜色,**不再按下标判断**(`i === 1 ? 青 : i === 3 ? 琥珀`)。
 * 缓存读那一列会随口径整列消失,下标一移位,原来的"青色=缓存读、琥珀=费用"就会染到「输出」头上 ——
 * 这种位置耦合正是删掉一列时会静默出错的地方。
 */
function FragRow({ t, name, known, cells }: {
  t: Theme; name: string; known: boolean;
  cells: { v: string; c?: string; bold?: boolean }[];
}) {
  return (
    <>
      <span style={{ color: t.text2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {name}{known ? "" : <span style={{ color: "#E0901C" }}> *</span>}
      </span>
      {cells.map((c, i) => (
        <span key={i} style={{ textAlign: "right", fontVariantNumeric: "tabular-nums",
                               color: c.c ?? t.text2, fontWeight: c.bold ? 700 : 400 }}>{c.v}</span>
      ))}
    </>
  );
}
