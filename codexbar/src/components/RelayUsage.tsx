import React, { useMemo, useState } from "react";
import type { Theme } from "../theme";
import { modelColor } from "../theme";
import Seg from "./Seg";
import { UP, DOWN } from "./KpiStrip";
import ModelSparkCard, { type ModelCardData } from "./relay/ModelSparkCard";
import { MONEY, MONO } from "./relay/RelayBits";
import { useRelayUsage } from "../hooks/useRelayUsage";
import { fmtTok } from "../traffic";
import { currencyOf, money, runwayText, type RelayEntry, type RelayUsage as RU } from "../relay";

/**
 * 中转站 · **用量** —— 1:1 复刻 `design_handoff_codexbar/中转站-交接说明.md` §4/§5。
 *
 * 版面：工具行（口径牌 + 刷新 + 按站筛选 + 时间段）→ KPI 条 → **模型小图阵**。
 *
 * ## ★ 与上一版（堆叠面积图 + 模型表）的差别
 *
 * 上一版按用户 2026-09-09 的要求与「AI用量信息」页 1:1 同构。2026-09-10 的设计稿
 * **改了这个决定**：用量改为「每模型一张小图卡」（2c 方案），理由写在稿里 ——
 * 堆叠图回答"这段时间的构成"，而这一页被问的是"**哪个模型在烧钱**"；
 * 堆叠图里占比 0.1% 的模型是一条看不见的细线。
 * 随之去掉的：分模型/总量两档、四类 token 图例、模型表、「全部」档、点行摘除。
 * 换来的：按站筛选、聚焦（点卡片其余变暗）、每卡独立 y 轴的走势线。
 *
 * ## ★★ 我曾断言"按模型上色做不到"，那是错的 —— 留档防再犯
 *
 * 第一版只看了 `/usage` 的**默认响应**（`daily_usage` 无模型、`model_stats` 无日期），
 * 就断定不存在「每天 × 每模型」的交叉，并据此把整张按模型上色的图否掉了。**没试参数。**
 * 实测 `?start_date=D&end_date=D` 生效，逐日查一次就拿得到，且与当天 `total_tokens`
 * **逐 token 相等**（8/8 天核对过，唯一不等的是今天 —— 两次 HTTP 之间用量还在涨）。
 * 用一个看不见目标的探针得出"目标不存在" —— 与本仓记过两次的 grep 假阴性同族、同方向。
 *
 * ## ★★ 三个不同的钱，永不合并
 *
 * ①「AI用量信息」页的「总费用」= 本机所有 CLI 的 token 按 OpenAI 牌价折算的**等效**成本
 *   （订阅制下并没有真付）；② 中转站的 `cost`（对方按上游牌价记的账）；
 * ③ 中转站的 `actual_cost`（**真实扣款**）。实测 ②③ 差 3.85 倍。
 * 这一页的主口径恒为 ③，而且**只出 ③** —— 设计稿把牌价那一列去掉了，
 * 所以现在页面上不存在第二个金额可被误读。口径牌「实扣口径」是它的凭证。
 */

/**
 * 档位（设计稿 §4）：今日 / 7d / 14d / 30d。**没有「全部」** —— 稿里去掉了。
 *
 * ★★ **「今日」有数据，但没有小时曲线。** 2026-09-09 实测：中转站 `/usage`
 *   **不提供小时粒度** —— `period` / `granularity` / `group_by` / `hourly` /
 *   `interval` / `unit` / `type` / `default_time` 共 10 种参数形式全部原样返回按天数据，
 *   响应里也没有任何 hour 字段。（而 `start_date`/`end_date` 是**认的**，见 `day_models`。）
 *
 *   所以这一档的每张卡只有一个点（走势线画成水平线），并在卡阵上方**明说原因** ——
 *   不说的话，用户会以为是我们没做（他 2026-09-09 就是这么问的）。
 */
const RANGES = ["today", 7, 14, 30] as const;
type RelayRange = (typeof RANGES)[number];
const rangeLabel = (r: RelayRange): string => (r === "today" ? "今日" : `${r}d`);

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
  /** 按站筛选（设计稿 §4）。`"all"` = 全部站。 */
  const [station, setStation] = useState<string>("all");
  /**
   * 聚焦的模型（设计稿 §5：点卡片 = 聚焦，其余变暗；再点取消）。
   *
   * ★★ **它索引进一个会变的数据集，所以不能活得比数据集久**（本仓 UI 规范）。
   *    切档位 / 换站之后模型集合会变，一个指向已不存在模型的 `focus` 会让整屏都变暗
   *    而没有任何一张卡是亮的 —— 越界检查发现不了这种"值还在、含义没了"。
   *    所以渲染时按**当前**模型集合校验一次，不在 `setState` 里补丁。
   */
  const [focus, setFocus] = useState<string | null>(null);

  const allRows: Row[] = useMemo(
    () => (snap?.relays ?? []).map((u) => ({ id: u.id, name: u.label ?? u.id, u })),
    [snap],
  );
  const rows: Row[] = useMemo(
    () => (station === "all" ? allRows : allRows.filter((r) => r.id === station)),
    [allRows, station],
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
    const present = [...dates].sort();
    // ★★★ **窗口按自然日切，不是"最近 N 个有数据的日期"**（2026-09-10 修）。
    //
    //   中转站的 `daily` 只含**有请求**的日子。原来 `present.slice(-range)` 取的是
    //   最近 N 个**有数据**的日子 —— 实测 7d 档跨了 **23 个自然日**，页面却标「7d」；
    //   `days = labels.length = 7` 让「日均」虚高 **3.3×**。中转站是"撞额度才切过来的
    //   备胎"，用得越稀疏偏得越多。
    //   这与本仓 CLAUDE.md 对 `scan.py` 判过死刑的是**同一类错**，而这一页自称
    //   与「AI用量信息」1:1 —— 那边一直是自然日口径，两页同名 KPI 本来不可比。
    //
    //   补零之后空档会如实画成 0（本仓 UI 规范：空档是真的没用），
    //   `days` 也就等于真正的自然日数。
    const labels: string[] = [];
    if (present.length) {
      if (range === "today") {
        // ★ 取**轴上最后一天**而不是本机日历的今天：中转站按它自己的时区结算，
        //   两者跨午夜时会差一天，而"今天没有数据"和"时区对不上"长得一模一样。
        labels.push(present[present.length - 1]);
      } else {
        // ★ 设计稿 §4 的档位是「今日 / 7d / 14d / 30d」，没有「全部」——
        //   所以这里不再有"按观测跨度自适应"的分支（TS 也已判它是死代码）。
        const end = new Date(present[present.length - 1] + "T00:00:00Z");
        for (let k = range - 1; k >= 0; k--) {
          labels.push(new Date(end.getTime() - k * 86400000).toISOString().slice(0, 10));
        }
      }
    }
    const idx = new Map(labels.map((d, i) => [d, i]));

    const zero = () => new Array(labels.length).fill(0) as number[];
    const cls: Record<string, number[]> = {};
    for (const c of CLASSES) cls[c.key] = zero();
    const cost = zero(), req = zero(), tok = zero();
    /** 模型 → 每天的 token / 实扣 / 轮数。**窗口内**，所以模型表跟着档位走。 */
    const mtok = new Map<string, number[]>();
    const mcost = new Map<string, number[]>();
    // ★ 牌价（`m.cost`）**不再收集**。设计稿去掉了牌价那一列之后它没有任何消费者 ——
    //   而"算了但没人用"的字段正是本仓栽过的孤儿字段：它会让下一个人以为页面上
    //   某个数就是它，也会让"牌价没有出现在页面上"这条闸永远被一句注释绊住。
    const mreq = new Map<string, number[]>();
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
            mreq.set(m.model, zero());
          }
          mtok.get(m.model)![i] += m.total_tokens || 0;
          mcost.get(m.model)![i] += m.actual_cost || 0;
          mreq.get(m.model)![i] += m.requests || 0;
        }
      }
    }
    const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
    // ★ 占比大的排前面 → 贴基线更稳定（细带夹在中间会来回跳）。本仓 UI 规范。
    const models = [...mtok.keys()]
      .map((k) => ({
        model: k, tok: mtok.get(k)!, cost: mcost.get(k)!, req: mreq.get(k)!,
        totalTok: sum(mtok.get(k)!), totalCost: sum(mcost.get(k)!),
        totalReq: sum(mreq.get(k)!),
      }))
      .sort((a, b) => b.totalTok - a.totalTok);

    return { labels, cls, cost, req, tok, models, missing,
             grandTok: sum(tok), grandCost: sum(cost), grandReq: sum(req) };
  }, [rows, range]);

  /** 环比：本窗口 vs 紧邻的上一个等长窗口。**样本不够就说「—」，不给一个假的 0%。** */
  const delta = useMemo(() => {
    if (range === "today" || view.labels.length === 0) return null;
    const all = new Set<string>();
    for (const r of rows) for (const d of r.u.data?.daily ?? []) all.add(d.date);
    const n = range as number;
    // ★★★ **上一窗口必须等长且与当前窗口零交集**（2026-09-10 修）。
    //
    //   原来是 `sorted.slice(Math.max(0, len - 2n), len - n)` + 只判 `size === 0`。
    //   两个洞：`len - n` 为负时 JS `slice` 把负数 end 当**从尾部倒数** ⇒ 取到的
    //   "上一窗口"落在当前窗口**内部**（拿总量和自己的子集比）；以及没有等长校验 ⇒
    //   1 天可以冒充 7 天的上期。实测本机真快照：7d 档显示「环比 ↑148757.6%」，
    //   14d 档「↑87.7%」，而注释一直承诺"样本不够就说 —"。
    //   参考实现 `TrafficPage.tsx` / `PlatformPage.tsx` 都有 `win.length === n` 守卫，
    //   这一页抄了口径没抄守卫。
    //
    //   现在按**自然日**回退一个等长窗口，并要求它与当前窗口不相交。
    if (!view.labels.length) return null;
    const endPrev = new Date(view.labels[0] + "T00:00:00Z").getTime() - 86400000;
    const prev = new Set<string>();
    for (let k = 0; k < n; k++) {
      prev.add(new Date(endPrev - k * 86400000).toISOString().slice(0, 10));
    }
    // ★ 只有当上一窗口**真的有观测**时才比 —— 否则那是"我们还没看过"，不是"降到 0"。
    const cur = new Set(view.labels);
    if ([...prev].some((d) => cur.has(d))) return null;      // 与当前窗口重叠 ⇒ 不比
    // ★★ 上一窗口必须**整段落在观测范围内**。
    //    补零之后"某天没有行"有两种含义：**观测过、当天为 0**，与**根本没观测过**。
    //    前者可以入分母，后者不行 —— 拿没观测过的日子当 0 去比，得到的涨幅是凭空的。
    //    只挡"整段早于观测"不够：部分重叠时（本机夹具 14d 档实测 6/14 天有观测）
    //    仍会算出 ↑522.2%。判据是 `prev` 的**最早一天** ≥ 我们最早的观测。
    const sorted = [...all].sort();
    const prevFirst = [...prev].sort()[0];
    if (!sorted.length || prevFirst < sorted[0]) return null;
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
  // ★★ **币种不一致时这些数不可相加**（2026-09-10 修）。原来是「取第一个非空的
  //    unit」然后把所有中转站的钱直接加起来 —— 一家 USD、一家 CNY 的话，
  //    KPI 条上那个数**不属于任何一种货币**，而它长得和一个正常金额一模一样。
  //    `null`（读不到币种）自成一类:它和 USD 也不可加。
  const { unit, mixed } = currencyOf(rows.map((r) => r.u.data?.unit));
  /** 可加时给数，不可加时给 `null` —— 让 `money()` 去渲染 `—`。 */
  const addable = (x: number | null) => (mixed ? null : x);
  const mixNote = mixed ? "多币种，不可相加" : undefined;
  const days = Math.max(1, view.labels.length);

  /**
   * ★★★ 页头这行说的必须是**数据有多新**，不是**我们什么时候试过**（2026-09-10 修）。
   *
   * `collect()` 每轮结尾都写 `fetched_at = now`，**取失败也写** —— 因为它确实
   * "跑过一轮"。于是所有中转站都取不到、页面上全是上一次的数字时，
   * 页头照样显示当前时刻的「↻ 上次刷新 14:32」。
   * 而正下方的 stale 横幅同时说着「下面显示的是上一次的数据」—— 同一屏两句话互相矛盾，
   * 用户信哪一句取决于他先看哪里。
   *
   * 三态：全新 / 部分旧 / 全旧。**全旧时时间戳换成上一次成功的那个**。
   */
  const freshness = useMemo(() => {
    const hhmm = (sec: number) => new Date(sec * 1000).toTimeString().slice(0, 5);
    const live = rows.filter((r) => r.u.state !== "disabled");
    const staleRows = live.filter((r) => r.u.stale);
    const at = hhmm(snap?.fetched_at ?? 0);
    if (!live.length || !staleRows.length) {
      return { kind: "fresh" as const, text: `↻ 上次刷新 ${at}` };
    }
    if (staleRows.length < live.length) {
      return { kind: "partial" as const,
               text: `↻ 上次刷新 ${at} · ${staleRows.length} 家是旧数据` };
    }
    // 全旧：`stale_since` 是上一次**成功**的时刻。取最早的那个，别乐观。
    const since = staleRows
      .map((r) => r.u.stale_since)
      .filter((x): x is number => typeof x === "number");
    return { kind: "stale" as const,
             text: since.length
               ? `↻ 数据停在 ${hhmm(Math.min(...since))} · ${at} 那次没取到`
               : `↻ ${at} 那次没取到` };
  }, [rows, snap?.fetched_at]);

  const models = view.models;
  const grandTok = Math.max(1, view.grandTok);
  const topTok = Math.max(1, models[0]?.totalTok ?? 1);
  // ★ 见 `focus` 的声明：按**当前**模型集合校验，值还在但已不在集合里就当没聚焦。
  const activeFocus = focus && models.some((m) => m.model === focus) ? focus : null;

  const cards: ModelCardData[] = models.map((m) => ({
    model: m.model,
    color: modelColor(m.model),
    series: m.tok,
    labels: view.labels,
    totalTok: m.totalTok,
    totalReq: m.totalReq,
    costText: money(addable(m.totalCost), unit),
    pct: m.totalTok / grandTok,
    bar: m.totalTok / topTok,
  }));

  const STATIONS = ["all", ...allRows.map((r) => r.id)];
  const stationLabel = (v: string): string =>
    (v === "all" ? "全部站" : allRows.find((r) => r.id === v)?.name ?? v);

  /** KPI 条一格。设计稿 §4：token 组 20px 白，钱组 15px 琥珀（明显降级）。 */
  const Cell = ({ k, v, sub, subC, money: isMoney, delta }: {
    k: string; v: string; sub?: string; subC?: string; money?: boolean;
    /** ★ 环比的**机器可读状态**。设计稿的环比是裸的 `↑4.4%`（没有"环比"两个字），
     *  而未知时只能写「环比 —」—— 两种措辞下没有一个稳定的文字锚点，
     *  而 `↑` 这个字符页面别处也会出现。状态放进属性，闸就不必去猜文案。 */
    delta?: "up" | "down" | "none";
  }): React.ReactElement => (
    <div data-kpi={k} data-delta={delta} style={{ minWidth: 0 }}>
      <div style={{ fontSize: 10, color: "#6b7480", marginBottom: 3 }}>{k}</div>
      <div style={{ fontSize: isMoney ? 15 : 20, fontWeight: 700,
                    color: isMoney ? MONEY : t.text, whiteSpace: "nowrap",
                    fontVariantNumeric: "tabular-nums" }}>
        {v}
        {sub && <span style={{ fontSize: 10, marginLeft: 6, fontWeight: 400,
                               color: subC ?? "#8a93a0" }}>{sub}</span>}
      </div>
    </div>
  );

  return (
    <div data-section="relay-usage" style={{ display: "flex", flexDirection: "column",
                                             minHeight: 0 }}>
      {/* ── 工具行（设计稿 §4）────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12,
                    flexWrap: "wrap", rowGap: 7 }}>
        <span style={{ fontSize: 13, fontWeight: 700, whiteSpace: "nowrap" }}>用量</span>
        {/* ★ 口径牌照 `CacheChip` 的先例：被它改变的数字就在下面，不挂牌子页面就会静默说谎。 */}
        <span data-scope-chip style={{ fontSize: 9.5, fontWeight: 700, padding: "2px 8px",
                       borderRadius: 6, whiteSpace: "nowrap", fontFamily: MONO,
                       border: "1px solid rgba(224,162,28,.5)", color: MONEY }}>
          实扣口径
        </span>
        <span style={{ fontSize: 11, color: "#6b7480", minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          每张卡独立 y 轴 · 按 token 排序 · 实扣为从余额真扣的钱
        </span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10,
                      flexWrap: "wrap", rowGap: 7 }}>
          {snap?.fetched_at && (
            <span data-act="relay-refresh" data-relay-freshness={freshness.kind}
                  onClick={busy ? undefined : () => refresh()}
                  title={busy ? "取用量中…" : "重新向中转站取一次账单（免费，不消耗余额）"}
                  style={{ fontSize: 10.5,
                           color: busy ? t.accent
                                : freshness.kind === "stale" ? "#E0901C" : "#6b7480",
                           whiteSpace: "nowrap", fontFamily: MONO,
                           cursor: busy ? "default" : "pointer", userSelect: "none",
                           transition: "color .15s" }}>
              {freshness.text}
            </span>
          )}
          {/* ★ 只有一家中转站时不画「按站筛选」—— 一个只有"全部"可选的控件是噪音。 */}
          {allRows.length > 1 && (
            <div data-station-filter>
              <Seg opts={STATIONS} cur={station} on={setStation} label={stationLabel} t={t} />
            </div>
          )}
          <Seg opts={RANGES} cur={range} on={setRange} label={rangeLabel} t={t} />
        </div>
      </div>

      {/* ── KPI 条（设计稿 §4）────────────────────────────────────────────── */}
      <div data-kpi-bar style={{ display: "flex", alignItems: "center", gap: 30,
                    padding: "11px 18px", background: "#0e1319",
                    border: "1px solid rgba(255,255,255,.08)", borderRadius: 12,
                    marginBottom: 12, fontFamily: MONO, flexWrap: "wrap", rowGap: 10 }}>
        <Cell k="总 token" v={fmtTok(view.grandTok)}
              sub={delta?.tok ? delta.tok.txt : "环比 —"}
              delta={delta?.tok ? (delta.tok.up ? "up" : "down") : "none"}
              subC={delta?.tok ? (delta.tok.up ? UP : DOWN) : "#6b7480"} />
        <Cell k="请求数" v={view.grandReq.toLocaleString()} />
        <Cell k="日均" v={fmtTok(view.grandTok / days)} />
        <Cell k="模型数" v={String(models.length)}
              sub={models.length ? `Top1 占 ${(models[0].totalTok / grandTok * 100).toFixed(0)}%` : undefined} />
        <div style={{ width: 1, height: 30, background: "rgba(255,255,255,.08)" }} />
        <Cell k="总实扣" v={money(addable(view.grandCost), unit)} money
              sub={mixNote} subC="#E0901C" />
        <Cell k="余额 · 还能撑" v={money(addable(balance), unit)} money
              sub={runwayText(tightest?.runway)} />
      </div>

      {err && (
        <div data-card="relay-ioerr" style={{ fontSize: 11, color: "#E0901C", marginBottom: 8 }}>
          读快照失败（IO 层）：{err}。这与「用量读不到」是两回事 —— 后者标在下面每家自己那一行。
        </div>
      )}
      {/* ★ `disabled` 是**用户的选择**不是故障，与真故障分开说。 */}
      {allRows.filter((r) => r.u.state === "disabled").map((r) => (
        <div key={r.id} data-relay-off style={{ fontSize: 11.5, color: t.muted, marginBottom: 6 }}>
          {r.name} 已停用 —— 不取用量、也不参与路由。
        </div>
      ))}
      {allRows.filter((r) => !r.u.ok && r.u.state !== "disabled").map((r) => (
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
      {/* ★ 「有几天没取到按模型明细」必须出声：`null` ≠ 空。
          不说的话那几天会被当成"没用过任何模型"，而卡上的数就少了一块。 */}
      {view.missing > 0 && (
        <div data-models-missing style={{ fontSize: 11, color: "#E0901C", marginBottom: 8 }}>
          有 {view.missing} 天没取到按模型明细 —— 下面的卡少算了这些天，
          <b>不是这些天没用过模型</b>。
        </div>
      )}

      {/* ★★ 「今日」档**没有小时曲线**，必须说出为什么 —— 用户 2026-09-09 问过
          「中转站是无法看今天用量吗？」。今天的数据是有的（在 `daily_usage` 最后一行），
          缺的只是**小时粒度**：2026-09-09 实测 10 种参数形式
          （`period`/`granularity`/`group_by`/`hourly`/`interval`/`unit`/`type`/`default_time`
          及组合）全部原样返回按天数据，响应里也没有任何 hour 字段。
          不写这一句，用户会以为是我们没做。 */}
      {range === "today" && (
        <div data-today-note style={{ fontSize: 10.5, color: "#6b7480", marginBottom: 8,
                                      fontFamily: MONO }}>
          今日只有一个点 —— 中转站<b>不提供小时曲线</b>（实测 10 种参数形式都只回按天数据）。
          下面每张卡是这一天的合计。
        </div>
      )}

      {/* ── 模型小图阵（设计稿 §4 的 2c 方案）──────────────────────────── */}
      {cards.length === 0 ? (
        <div data-usage-empty style={{ fontSize: 12, color: t.muted, padding: "18px 0" }}>
          这个窗口内没有按模型明细。换个档位，或点右上角 ↻ 重新取一次。
        </div>
      ) : (
        // 固定 3 列（设计稿 §4）。`minmax(0,1fr)` 而不是 `1fr`：后者的最小宽度是
        // `auto`，模型名一长就把列撑开、整行溢出，而 `overflow:hidden` 只管文字、救不了列宽。
        <div data-model-grid data-model-window={String(range)} style={{ display: "grid",
                      gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12 }}>
          {cards.map((c) => (
            <ModelSparkCard key={c.model} d={c}
                            focused={activeFocus === c.model}
                            dimmed={!!activeFocus && activeFocus !== c.model}
                            onPick={() => setFocus((f) => (f === c.model ? null : c.model))} />
          ))}
        </div>
      )}

      <div style={{ marginTop: 8, fontSize: 10, color: "#454d57", fontFamily: MONO }}>
        悬浮走势线 = 当日 token · 点卡片 = 聚焦该模型（其余变暗）· 按站筛选 / 时间段联动全部数字
      </div>
    </div>
  );
}
