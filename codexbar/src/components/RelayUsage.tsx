import React, { useMemo, useState } from "react";
import type { Theme } from "../theme";
import { modelColor } from "../theme";
import StackedArea, { type Layer } from "./StackedArea";
import KpiStrip, { type Kpi, UP, DOWN } from "./KpiStrip";
import Seg from "./Seg";
import { MONEY, MONO, NUM } from "./relay/RelayBits";
import { useRelayUsage } from "../hooks/useRelayUsage";
import { fmtTok } from "../traffic";
import { money, runwayText, type RelayEntry, type RelayUsage as RU } from "../relay";

/**
 * 中转站 · **用量** —— 与「AI用量信息 / 平台详情」页同结构（用户 2026-09-09：「1:1 复刻」）。
 *
 * ## ★★ 我曾断言"按模型上色做不到"，那是错的 —— 留档防再犯
 *
 * 第一版只看了 `/usage` 的**默认响应**（`daily_usage` 无模型、`model_stats` 无日期），
 * 就断定不存在「每天 × 每模型」的交叉，并据此把整张按模型上色的图否掉了。**没试参数。**
 * 实测 `?start_date=D&end_date=D` 生效，逐日查一次就拿得到，且与当天 `total_tokens`
 * **逐 token 相等**（8/8 天核对过，唯一不等的是今天 —— 两次 HTTP 之间用量还在涨）。
 * 用一个看不见目标的探针得出"目标不存在" —— 与本仓记过两次的 grep 假阴性同族、同方向。
 *
 * ## 两个分层档（与「平台详情」页同名同义）
 *
 * - **分模型**（默认）：每个模型一层，颜色取 `modelColor()` —— 与 AI用量页同一个函数，
 *   所以同一个模型在两页颜色一致。**点模型行 = 把它从图里摘掉**（最后一个不许摘）。
 * - **总量**：四类 token（缓存读 / 输入 / 输出 / 缓存写）。
 *
 * 模型表与图**同窗口**，一起跟着档位走 —— 同一页上两个数不同口径正是本仓在 scan 侧
 * 栽过的错（119M vs 9,004M）。
 *
 * ## ★ 一张图，钱在 hover 里
 *
 * 用户定稿：「实扣款公用一张图，只是鼠标悬浮显示对应的金额」。所以不画第二张钱的图 ——
 * 金额进 tooltip 标题与 KPI 条。token 与钱是两个量纲，本来就不该共用一个 y 轴。
 *
 * ## ★★ 三个不同的钱，永不合并
 *
 * ①「AI用量信息」页的「总费用」= 本机所有 CLI 的 token 按 OpenAI 牌价折算的**等效**成本
 *   （订阅制下并没有真付）；② 中转站的 `cost`（对方按上游牌价记的账）；
 * ③ 中转站的 `actual_cost`（**真实扣款**）。实测 ②③ 差 3.85 倍。
 * 这一页的主口径恒为 ③；② 只在模型表末列作参考并压成 muted，**绝不进 KPI**。
 */

/**
 * 档位。与「AI用量信息」页同序：今日 → 7d → 14d → 30d → 全部。
 *
 * ★★ **「今日」有数据，但没有小时曲线。** 2026-09-09 实测：中转站 `/usage`
 *   **不提供小时粒度** —— `period` / `granularity` / `group_by` / `hourly` /
 *   `interval` / `unit` / `type` / `default_time` 共 10 种参数形式全部原样返回按天数据，
 *   响应里也没有任何 hour 字段。（而 `start_date`/`end_date` 是**认的**，见 `day_models`。）
 *
 *   所以这一档**不画面积图** —— 一个点的面积图没有意义。改画「今日构成条」：
 *   一条横向堆叠条 + 模型表，都是真数据。少画一条假曲线，不少给一个真数字。
 */
const RANGES = ["today", 7, 14, 30, 0] as const;
type RelayRange = (typeof RANGES)[number];
const rangeLabel = (r: RelayRange): string =>
  (r === "today" ? "今日" : r === 0 ? "全部" : `${r}d`);

/** 分层维度。与「平台详情」页的「分模型 / 总量」同名同义 —— 别发明第二套说法。 */
const MODES = ["model", "total"] as const;
type Mode = (typeof MODES)[number];
const modeLabel = (m: Mode): string => (m === "model" ? "分模型" : "总量");

/**
 * 四类 token 的分层。**顺序 = 画图顺序**，占比最大的贴基线（本仓 UI 规范：
 * 细带夹在中间会来回跳）。实测中转站的构成里 `cache_read` 占 ~95%，所以它在最下。
 *
 * ★ 颜色沿用本仓语义：缓存读=品牌青、输入=蓝、输出=紫、缓存写=金额琥珀。
 *   **不用灰** —— 本仓 UI 规范：灰是"其余"专用，几条灰带会糊成一片。
 */
const CLASSES = [
  { key: "cache_read_tokens", name: "缓存读", color: "#2dd4bf" },
  { key: "input_tokens", name: "输入", color: "#2BA0C0" },
  { key: "output_tokens", name: "输出", color: "#7C5CFF" },
  { key: "cache_write_tokens", name: "缓存写", color: "#E0A21C" },
] as const;

type Row = { id: string; name: string; u: RelayEntry };

export default function RelayUsage({ t }: { t: Theme }): React.ReactElement {
  const { snap, busy, err, refresh } = useRelayUsage();
  const [range, setRange] = useState<RelayRange>(14);
  const [mode, setMode] = useState<Mode>("model");
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  /** 被摘掉的模型（点一下从图里拿走）。★ 与「平台详情」页 `iso` 同义。
   *  **占比恒按全量算，不随隔离变** —— 隔离只是"这张图先不画它"，不是"它不存在了"。 */
  const [iso, setIso] = useState<Set<string>>(() => new Set());

  const rows: Row[] = useMemo(
    () => (snap?.relays ?? []).map((u) => ({ id: u.id, name: u.label ?? u.id, u })),
    [snap],
  );

  /**
   * 对齐到一条**公共日期轴**，各家按天相加。
   *
   * ★ 轴取所有中转站日期的并集后截最近 N 天，各家自己缺的日子补 0。
   *   不对齐的话堆叠图的第 i 个点在不同层上代表不同的日子 —— 图是错的而且看不出来。
   */
  const view = useMemo(() => {
    const dates = new Set<string>();
    for (const r of rows) for (const d of r.u.data?.daily ?? []) dates.add(d.date);
    let labels = [...dates].sort();
    if (range === "today") {
      // ★ 取**轴上最后一天**而不是本机日历的今天：中转站按它自己的时区结算，
      //   两者跨午夜时会差一天，而"今天没有数据"和"时区对不上"长得一模一样。
      labels = labels.slice(-1);
    } else if (range !== 0) {
      labels = labels.slice(-range);
    }
    const idx = new Map(labels.map((d, i) => [d, i]));

    const zero = () => new Array(labels.length).fill(0) as number[];
    const cls: Record<string, number[]> = {};
    for (const c of CLASSES) cls[c.key] = zero();
    const cost = zero(), req = zero(), tok = zero();
    /** 模型 → 每天的 token / 实扣 / 轮数。**窗口内**，所以模型表跟着档位走。 */
    const mtok = new Map<string, number[]>();
    const mcost = new Map<string, number[]>();
    const mreq = new Map<string, number[]>();
    const mlist = new Map<string, number[]>();   // 牌价（参考口径）
    /** ★ 有几天**没取到**按模型明细。`null` ≠ 空 —— 必须能说出来，
     *  否则"这天没数据"会被画成"这天没用过"。 */
    let missing = 0;

    for (const r of rows) {
      for (const d of r.u.data?.daily ?? []) {
        const i = idx.get(d.date);
        if (i === undefined) continue;
        for (const c of CLASSES) cls[c.key][i] += (d[c.key] as number) || 0;
        cost[i] += d.actual_cost || 0;
        req[i] += d.requests || 0;
        tok[i] += d.total_tokens || 0;
        const ms = d.models;
        if (ms == null) { missing++; continue; }
        for (const m of ms) {
          if (!mtok.has(m.model)) {
            mtok.set(m.model, zero()); mcost.set(m.model, zero());
            mreq.set(m.model, zero()); mlist.set(m.model, zero());
          }
          mtok.get(m.model)![i] += m.total_tokens || 0;
          mcost.get(m.model)![i] += m.actual_cost || 0;
          mreq.get(m.model)![i] += m.requests || 0;
          mlist.get(m.model)![i] += m.cost || 0;
        }
      }
    }
    const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
    // ★ 占比大的排前面 → 贴基线更稳定（细带夹在中间会来回跳）。本仓 UI 规范。
    const models = [...mtok.keys()]
      .map((k) => ({
        model: k, tok: mtok.get(k)!, cost: mcost.get(k)!, req: mreq.get(k)!,
        totalTok: sum(mtok.get(k)!), totalCost: sum(mcost.get(k)!),
        totalReq: sum(mreq.get(k)!), totalList: sum(mlist.get(k)!),
      }))
      .sort((a, b) => b.totalTok - a.totalTok);

    return { labels, cls, cost, req, tok, models, missing,
             grandTok: sum(tok), grandCost: sum(cost), grandReq: sum(req) };
  }, [rows, range]);

  /** 环比：本窗口 vs 紧邻的上一个等长窗口。**样本不够就说「—」，不给一个假的 0%。** */
  const delta = useMemo(() => {
    if (range === 0 || range === "today" || view.labels.length === 0) return null;
    const all = new Set<string>();
    for (const r of rows) for (const d of r.u.data?.daily ?? []) all.add(d.date);
    const sorted = [...all].sort();
    const n = range as number;
    const prev = new Set(sorted.slice(Math.max(0, sorted.length - n * 2), sorted.length - n));
    if (prev.size === 0) return null;
    let ptok = 0, pcost = 0;
    for (const r of rows) {
      for (const d of r.u.data?.daily ?? []) {
        if (!prev.has(d.date)) continue;
        ptok += d.total_tokens || 0; pcost += d.actual_cost || 0;
      }
    }
    const mk = (now: number, before: number) => {
      if (!before) return null;
      const pct = ((now - before) / before) * 100;
      return { up: pct >= 0, txt: `${pct >= 0 ? "↑" : "↓"}${Math.abs(pct).toFixed(1)}%` };
    };
    return { tok: mk(view.grandTok, ptok), cost: mk(view.grandCost, pcost) };
  }, [rows, range, view]);

  const balance = rows.reduce<number | null>((a, r) => {
    const b = r.u.data?.balance;
    return typeof b === "number" ? (a ?? 0) + b : a;
  }, null);
  const tightest = rows.reduce<RU | undefined>((a, r) => {
    const d = r.u.data;
    if (!d?.runway || d.runway.days === null) return a;
    if (!a?.runway || a.runway.days === null) return d;
    return d.runway.days < a.runway.days ? d : a;
  }, undefined);
  const unit = rows.find((r) => r.u.data?.unit)?.u.data?.unit ?? null;
  const days = Math.max(1, view.labels.length);

  const kpis: Kpi[] = [
    { k: "总 token", v: fmtTok(view.grandTok), n: view.grandTok, fmt: fmtTok,
      sub: delta?.tok ? `环比 ${delta.tok.txt}` : "环比 —",
      subC: delta?.tok ? (delta.tok.up ? UP : DOWN) : t.muted },
    { k: "请求数", v: view.grandReq.toLocaleString(), n: view.grandReq,
      fmt: (x) => Math.round(x).toLocaleString() },
    { k: "日均", v: fmtTok(view.grandTok / days), n: view.grandTok / days, fmt: fmtTok },
    // ★★ 主口径恒为**实扣**。牌价绝不进 KPI —— KPI 是一眼看的地方，
    //    放一个"其实没付这么多"的数就是骗人。
    { k: "总实扣", v: money(view.grandCost, unit), n: view.grandCost,
      fmt: (x) => money(x, unit), c: MONEY,
      sub: delta?.cost ? `环比 ${delta.cost.txt}` : "真实扣款",
      subC: delta?.cost ? (delta.cost.up ? UP : DOWN) : t.muted },
    { k: "日均实扣", v: money(view.grandCost / days, unit), n: view.grandCost / days,
      fmt: (x) => money(x, unit), c: MONEY },
    // ★ 余额与 runway 是中转站独有的（订阅制的 AI用量页没有对应物）。
    //   读不到显 `—` 不显 0 —— 两者的下一步动作完全相反。
    { k: "余额", v: money(balance, unit), c: MONEY },
    { k: "还能撑", v: runwayText(tightest?.runway) },
  ];

  const layers: Layer[] = mode === "total"
    ? CLASSES
        .map((c) => ({ key: c.key, name: c.name, color: c.color, values: view.cls[c.key] ?? [] }))
        .filter((l) => l.values.some((v) => v > 0))
    : view.models
        // ★ 被摘掉的模型**不进图层**，但仍留在表里（划掉+变淡），且占比照全量算。
        .filter((m) => !iso.has(m.model))
        .map((m) => ({ key: m.model, name: m.model, color: modelColor(m.model), values: m.tok }));

  /** 模型表 = **窗口内**的逐日明细求和，所以它跟着上面的档位走
   *  （用户 2026-09-09：「模型消耗没有按照我的日期来变化口径」）。 */
  const models = view.models;
  const modelGrand = Math.max(1, models.reduce((a, m) => a + m.totalTok, 0));
  /** ★ **每个单元格用同一份纵向 padding。** 只给第一格加 padding 会把行撑高，
   *  其余格子被拉满 ⇒ harness 的折行探针（比"内容盒高 vs 行高"）把它们全判成折行。
   *  实测 10 处假阳性 —— 而真折行淹没在假阳性里，正是这个探针要防的事。 */
  const CELL: React.CSSProperties = { padding: "4px 0" };
  const modelMax = Math.max(1, models[0]?.totalTok ?? 1);

  return (
    <div data-section="relay-usage" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* ── 顶栏（与 AI用量信息页同构：标题 + 口径牌 + 刷新时间戳 + 档位）── */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 9,
                    flexWrap: "wrap", rowGap: 7 }}>
        <span style={{ fontSize: 15, fontWeight: 700, whiteSpace: "nowrap" }}>用量</span>
        {/* ★ 口径牌照 `CacheChip` 的先例：被它改变的数字就在下面，不挂牌子页面就会静默说谎。 */}
        <span data-scope-chip style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".03em",
                       padding: "2px 7px", borderRadius: 6, whiteSpace: "nowrap",
                       border: `1px solid ${MONEY}`, color: MONEY }}>
          实扣口径
        </span>
        <span style={{ fontSize: 10.5, color: t.muted }}>
          与「AI用量信息」的「总费用」<b>不同口径</b>：那是按 OpenAI 牌价折算的<b>等效</b>成本
          （订阅制下并没有真付），这里是从余额<b>真扣掉</b>的钱。
        </span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          {snap?.fetched_at && (
            <span data-act="relay-refresh" onClick={busy ? undefined : () => refresh()}
                  title={busy ? "取用量中…" : "重新向中转站取一次账单（免费，不消耗余额）"}
                  style={{ fontSize: 10.5, color: busy ? t.accent : t.muted, whiteSpace: "nowrap",
                           fontFamily: MONO, cursor: busy ? "default" : "pointer",
                           userSelect: "none", transition: "color .15s" }}>
              ↻ 上次刷新 {new Date(snap.fetched_at * 1000).toTimeString().slice(0, 5)}
            </span>
          )}
          {/* ★ 与「平台详情」页同名同义的两档，用同一个 `Seg` —— 别发明第二种切换器。 */}
          <Seg opts={MODES} cur={mode} on={setMode} label={modeLabel} t={t} />
          <Seg opts={RANGES} cur={range} on={setRange} label={rangeLabel} t={t} />
        </div>
      </div>

      <KpiStrip t={t} items={kpis} />

      {err && (
        <div data-card="relay-ioerr" style={{ fontSize: 11, color: "#E0901C", marginBottom: 8 }}>
          读快照失败（IO 层）：{err}。这与「用量读不到」是两回事 —— 后者标在下面每家自己那一行。
        </div>
      )}
      {/* ★ `disabled` 是**用户的选择**不是故障，与真故障分开说。 */}
      {rows.filter((r) => r.u.state === "disabled").map((r) => (
        <div key={r.id} data-relay-off style={{ fontSize: 11.5, color: t.muted, marginBottom: 6 }}>
          {r.name} 已停用 —— 不取用量、也不参与路由。
        </div>
      ))}
      {rows.filter((r) => !r.u.ok && r.u.state !== "disabled").map((r) => (
        <div key={r.id} data-relay-err style={{ fontSize: 11.5, color: "#E0901C", marginBottom: 6 }}>
          {/* ★★ 取不到时**页面上的数字仍然是上一次的**，必须说清楚这一点 ——
              否则用户会把旧数字当成刚取的。反过来把它清空更糟（他会以为用量丢了）。 */}
          {r.u.stale ? (
            <span data-relay-stale>
              {r.name} 这次没取到（{r.u.state}）：{r.u.detail ?? "（对方没给原因）"} ——
              <b>下面显示的是上一次的数据</b>
              {r.u.stale_since
                ? `（${new Date(r.u.stale_since * 1000).toTimeString().slice(0, 5)}）` : ""}
              ，不是丢失。
            </span>
          ) : (
            <>{r.name} 用量读不到（{r.u.state}）：{r.u.detail ?? "（对方没给原因）"}</>
          )}
        </div>
      ))}

      {view.labels.length === 0 ? (
        <div data-card="nodata" style={{ fontSize: 12.5, color: t.muted, padding: "14px 0" }}>
          这个档位里没有任何用量记录。<b>这不等于读取失败</b> —— 上面若没有红字，
          就是这段时间真的没走过中转站。
        </div>
      ) : (
        <>
          {range === "today" ? (
            /* ── 今日构成条 ────────────────────────────────────────
               ★★ 中转站**不提供小时粒度**（10 种参数形式实测全部原样返回按天）。
               一个点的面积图没有任何可读信息，所以这一档画横向堆叠条：
               同样的颜色、同样的分层、同样的 hover 数字，只是没有时间轴。
               **少画一条假曲线，不少给一个真数字。** */
            <div data-today-bar style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10.5, color: t.muted, marginBottom: 6 }}>
                {view.labels[0] ?? "今日"} 的构成 · 共 {fmtTok(view.grandTok)} token ·
                实扣 <b style={{ color: MONEY }}>{money(view.grandCost, unit)}</b>
                {` · ${view.grandReq} 次请求`}
                <span style={{ marginLeft: 8 }}>
                  ⓘ 中转站只提供<b>按天</b>结算，没有小时曲线 —— 所以这一档画构成，不画走势。
                </span>
              </div>
              <div style={{ display: "flex", height: 26, borderRadius: 7, overflow: "hidden",
                            border: `1px solid ${t.cardBorder}` }}>
                {layers.map((l) => {
                  const tot = l.values.reduce((a, b) => a + b, 0);
                  const pct = (tot / Math.max(1, view.grandTok)) * 100;
                  if (pct <= 0) return null;
                  return (
                    <span key={l.key} data-layer={l.key}
                          title={`${l.name} · ${fmtTok(tot)} · ${pct.toFixed(1)}%`}
                          onMouseEnter={() => setHoverKey(l.key)}
                          onMouseLeave={() => setHoverKey(null)}
                          style={{ width: `${pct}%`, background: l.color,
                                   opacity: hoverKey && hoverKey !== l.key ? 0.35 : 1,
                                   transition: "opacity .15s" }} />
                  );
                })}
              </div>
            </div>
          ) : (
          <div style={{ marginTop: 10 }}>
            <StackedArea key={`${mode}:${range}:${view.labels[0]}:${view.labels.length}`}
                         labels={view.labels} layers={layers} height={156} fmt={fmtTok} t={t}
                         dimmed={hoverKey}
                         tipTitle={(i) =>
                           `${view.labels[i]} · ${view.req[i]} 次请求 · 实扣 ${money(view.cost[i], unit)}`} />
          </div>
          )}

          {/* ★ 四类图例只属于「总量」档。分模型档的图例就是下面那张模型表 ——
              同一个东西画两遍只会让人以为它们是两组数。 */}
          {mode === "total" && (
          <div data-legend style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 8 }}>
            {layers.map((l) => {
              const tot = l.values.reduce((a, b) => a + b, 0);
              return (
                <span key={l.key} data-legend-row={l.key}
                      onMouseEnter={() => setHoverKey(l.key)} onMouseLeave={() => setHoverKey(null)}
                      style={{ display: "inline-flex", alignItems: "center", gap: 6,
                               fontSize: 11, color: t.muted, cursor: "default" }}>
                  <span style={{ width: 9, height: 9, borderRadius: 3, background: l.color }} />
                  <span style={{ color: t.text }}>{l.name}</span>
                  <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums" }}>
                    {fmtTok(tot)} · {((tot / Math.max(1, view.grandTok)) * 100).toFixed(1)}%
                  </span>
                </span>
              );
            })}
          </div>
          )}

          {/* ── 模型消耗（★ 不同模型不同颜色 —— 用户要的那一处）── */}
          {models.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6,
                            flexWrap: "wrap", rowGap: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>模型消耗</span>
                {/* ★ 与上面的图**同窗口**（用户 2026-09-09 要求）：两个数放在同一页上
                    必须同口径 —— 这正是本仓在 scan 侧栽过的错（119M vs 9,004M）。 */}
                <span style={{ fontSize: 10.5, color: t.muted }}>
                  与上图同窗口（{rangeLabel(range)}）· 点一行可把它从图里摘掉
                </span>
                {/* ★★ 「这几天没取到明细」必须说出来，不能让它长得像"这几天没用过"。 */}
                {view.missing > 0 && (
                  <span data-models-missing style={{ fontSize: 10.5, color: "#E0901C" }}>
                    ⚠️ 有 {view.missing} 天没取到按模型明细，未计入本表（总量图不受影响）。
                  </span>
                )}
              </div>
              <table data-models style={{ width: "100%", fontSize: 11.5, borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ color: t.muted, textAlign: "left" }}>
                    <th style={{ fontWeight: 600, paddingBottom: 5 }}>模型</th>
                    <th />
                    <th style={{ fontWeight: 600, textAlign: "right" }}>TOKEN</th>
                    <th style={{ fontWeight: 600, textAlign: "right" }}>占比</th>
                    <th style={{ fontWeight: 600, textAlign: "right" }}>轮数</th>
                    <th style={{ fontWeight: 600, textAlign: "right" }}>实扣</th>
                    <th style={{ fontWeight: 600, textAlign: "right", opacity: 0.7 }}>牌价</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => {
                    const c = modelColor(m.model);
                    const off = iso.has(m.model);
                    return (
                      <tr key={m.model} data-model-row={m.model}
                          title="点一下把它从图里摘掉（只影响这张图，不改总量/费用/占比）"
                          onClick={() => setIso((z) => {
                            const nx = new Set(z);
                            nx.has(m.model) ? nx.delete(m.model) : nx.add(m.model);
                            // ★ 全摘光就什么都不剩了，最后一个不许摘（与「平台详情」页同规矩）。
                            return nx.size >= models.length ? z : nx;
                          })}
                          onMouseEnter={() => setHoverKey(m.model)}
                          onMouseLeave={() => setHoverKey(null)}
                          style={{ color: t.text, cursor: "pointer",
                                   opacity: off ? 0.38 : 1, transition: "opacity .15s",
                                   background: hoverKey === m.model && !off ? t.cardBg : "transparent" }}>
                        <td style={{ ...CELL, whiteSpace: "nowrap" }}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                            <span style={{ width: 9, height: 9, borderRadius: 3, background: c,
                                           flexShrink: 0, opacity: off ? 0.35 : 1 }} />
                            {/* ★ 模型名走等宽 —— 它是标识符不是散文（本仓 UI 规范）。 */}
                            <span style={{ fontFamily: MONO,
                                           textDecoration: off ? "line-through" : "none" }}>
                              {m.model}
                            </span>
                          </span>
                        </td>
                        <td style={{ ...CELL, width: "38%", paddingLeft: 12, paddingRight: 12 }}>
                          {/* 条形是这一行里**唯一一眼可比**的东西，给它全宽。 */}
                          <span style={{ display: "block", height: 6, borderRadius: 3,
                                         background: t.ghostBorder }}>
                            <span style={{ display: "block", height: "100%", borderRadius: 3,
                                           background: c,
                                           width: `${(m.totalTok / modelMax) * 100}%` }} />
                          </span>
                        </td>
                        <td style={{ ...NUM, ...CELL, fontWeight: 700 }}>{fmtTok(m.totalTok)}</td>
                        {/* ★ 占比恒按**全量**算，不随隔离变 —— 隔离只是"这张图先不画它"，
                            不是"它不存在了"（与「平台详情」页同一条纪律）。 */}
                        <td style={{ ...NUM, ...CELL, color: t.muted }}>
                          {((m.totalTok / modelGrand) * 100).toFixed(1)}%
                        </td>
                        <td style={{ ...NUM, ...CELL, color: t.muted }}>{m.totalReq.toLocaleString()}</td>
                        <td style={{ ...NUM, ...CELL, color: MONEY, fontWeight: 700 }}>
                          {money(m.totalCost, unit)}
                        </td>
                        <td style={{ ...NUM, ...CELL, color: t.muted }}>{money(m.totalList, unit)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
