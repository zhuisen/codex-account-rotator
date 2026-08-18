import { useMemo, useState } from "react";
import { type Theme, modelColor } from "../theme";
import { costOf, fmtUSD, priceOf, isPriced } from "../rates";
import StackedArea, { type Layer } from "../components/StackedArea";
import Seg from "../components/Seg";
import type { TrafficData, Range, CacheMode, Bucket, Coverage } from "../traffic";
import { RANGES, rangeLabel, bucketsFor, sumBuckets, costOfBucket, savingOfBucket, fmtTok,
         countsCacheRead, countsCacheWrite, countedClasses, mixParts, colorOf, coveragePct, coverageNote } from "../traffic";
import KpiStrip, { type Kpi, UP, DOWN } from "../components/KpiStrip";
import { useIntro, introEnabled } from "../hooks/useIntro";
import CacheChip from "../components/CacheChip";

const AMBER = "#E0A21C";
const SRC: Record<string, string> = {
  claude: "~/.claude/projects/**/*.jsonl",
  codex: "~/.codex/sessions/**/rollout-*.jsonl",
  grok: "~/.grok/sessions/*/*/updates.jsonl",
  // ★ 唯一一个**不是**该 CLI 自己落的盘的源:agy 什么都不记,这份账本是 `bin/agy` wrapper
  //   从 `--output-format json` 抄下来的。所以它旁边永远有一枚覆盖率徽章。
  agy: "traffic/agy-ledger/usage.jsonl（wrapper 记账）",
};

/** 采集不完整的平台的横幅。`coverage` 缺席 = 全量采集,**不渲染任何东西**。 */
function CoverageBanner({ t, coverage }: {
  t: Theme; coverage?: Coverage;
}): React.ReactElement | null {
  const pct = coveragePct(coverage);
  if (pct == null || !coverage) return null;
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start",
                  border: `1px solid rgba(224,144,28,.35)`,
                  background: t.isDark ? "rgba(224,144,28,.09)" : "rgba(224,144,28,.10)",
                  borderRadius: 9, padding: "7px 10px", marginBottom: 10 }}>
      <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 9.5, fontWeight: 700, color: AMBER,
                     whiteSpace: "nowrap", paddingTop: 1, letterSpacing: ".03em" }}>
        覆盖 {coverage.covered}/{coverage.total}
      </span>
      <span style={{ fontSize: 10.5, lineHeight: 1.55, color: t.text2 }}>
        {coverageNote(coverage)}
      </span>
    </div>
  );
}

/** 平台详情(交接稿 §5–§8)。 */
/**
 * 「总量」档的三类 token（用户 2026-08-15 从 5 张整页 mock 里选的「绝对量堆叠」）。
 *
 * ⚠️ **已知取舍,不是缺陷**:本机真实比例是 缓存读 ~95% / 未命中输入 ~4.5% / 输出 ~0.5%,
 * 所以后两条带在 216px 高的图里只有 ~10px 和 ~1px —— 构成基本读不出来。用户看过
 * 100% 堆叠与双轨两个替代版后仍选了这个(要的是真实量级),所以**别再"修"成另外两种**。
 * 补偿手段是图例里直接写占比数字,让读不出来的部分有数兜底。
 *
 * 自下而上 = 占比降序,与总览同规则(大的贴基线)。
 */
const TOTAL_CLASSES = [
  // ★ 名字必须短。浮层只有 **130px** 宽，`输入（命中缓存）` 在 10px 等宽下会被省略号截掉 ——
  //   那正是这个浮层唯一要说的事。`缓存读` 与项目里其它地方(费率卡列名、缓存计入口径、构成行)
  //   用的是同一个词，不再造第二套说法；`新输入` 覆盖 uncached_in + cache_write 的语义：
  //   首次发送的内容，不管有没有顺带写进缓存。全称放 `full`，给图例的 title 用。
  { key: "cache_read",  name: "缓存读", full: "输入 · 命中缓存（按输入价 10% 上下计费）",
    pick: (b: Bucket) => b.cache_read,
    shade: (c: string) => mixHex(c, "#000000", 0.62) },
  { key: "uncached_in", name: "新输入", full: "输入 · 未命中缓存（含首次写入缓存的部分，按全价计费）",
    pick: (b: Bucket) => b.uncached_in + b.cache_write,
    shade: (c: string) => c },
  { key: "output",      name: "输出",   full: "模型生成的 token，单价最高",
    pick: (b: Bucket) => b.output,
    shade: (c: string) => mixHex(c, "#ffffff", 0.68) },
] as const;

/**
 * 单价显示。**不能一律 `toFixed(2)`** —— MiMo 输入价 $0.435 会显示成 $0.43（少 1.1%），
 * DeepSeek 缓存读 $0.044 会变 $0.04。亚元价按三位显示。
 */
function money(x: number): string {
  return x >= 1 ? x.toFixed(2) : x.toFixed(3);
}

/**
 * D1 表格的列。**表头与数据行必须用同一个常量** —— 两处各写一份 `gridTemplateColumns`，
 * 是「改了一处忘另一处」的经典位置，而症状是表头和数据错位一列，看着像数据错了。
 * 中间那 26px 是分区竖线所在的空列。
 */
const GAP = 26;
const RATE_W = 58 + 58 + 74 + 16;   // 输入 + 输出 + 费用/百万 + 间隙
const ROW: React.CSSProperties = {
  display: "grid", alignItems: "center",
  gridTemplateColumns: `14px 180px 1fr 62px 44px 60px 68px ${GAP}px 58px 58px 74px`,
};
/** 数字列一律右对齐 + 等宽数位（`tabular-nums`），否则每次刷新数字会左右跳。 */
const R: React.CSSProperties = { textAlign: "right", fontVariantNumeric: "tabular-nums" };

/** 平台色的明暗阶。三类是**同一个量的三部分**,用顺序色阶(便宜→贵)比三个无关色相更好读。 */
function mixHex(hex: string, to: string, amt: number): string {
  const h = (x: string) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
  const [r1, g1, b1] = h(hex), [r2, g2, b2] = h(to);
  const m = (a: number, b: number) => Math.round(a + (b - a) * amt).toString(16).padStart(2, "0");
  return `#${m(r1, r2)}${m(g1, g2)}${m(b1, b2)}`;
}

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
  /**
   * 「总量」档里被隔离的 token 类。**这一档的老问题**:缓存读占 95~99%(Claude 实测 97.24%),
   * 另两类各自只有 ~2% 和 ~0.3%,在 190px 高的图里是顶边上的一条线,构成根本读不出来。
   * 用户 2026-08-15 在三个画法里选了「绝对量堆叠」(要真实量级),代价就是这个。
   *
   * 点图例摘掉缓存读 ⇒ 剩下两类按自己的量级重新铺满,构成立刻可读 —— **而且不动任何口径、
   * 不改费用、不改总量**,只是这张图少画一层。与下面模型行的点击隔离是同一个交互,不是新发明。
   */
  const [isoCls, setIsoCls] = useState<Set<string>>(new Set());
  // ★ 走 `colorOf` 而不是 `platformColor` —— 后者只查 theme.ts 的静态兜底表，**绕过了
  //   scan.py 下发的注册色和用户在设置页改的色**。MiMo/DeepSeek 不在静态表里，会拿到兜底灰
  //   `#5b6472`，而「总量」档整张图就是这个色 ⇒ 一整块灰色数据，违反设计规范「数据不用灰色」
  //   （实测：MiMo 的 90d 总量图整片是灰的）。分模型档因为用 modelColor 散列，一直没暴露。
  const c = colorOf(data, pk);

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

  /**
   * ★ 「总量」的三类**必须过缓存口径门**。不过门的话，切到「不含缓存」时图例会显示
   * 「缓存读 0 · 0.00%」+ 一条零高的带 —— 而项目定稿是「**不计入的类，其指标要从页面上整个删掉**，
   * 不是显示 0%、也不是改说『已排除 X』」（用户 2026-08-11）。显示 0% 会被读成「没用到缓存」，
   * 与事实相反。2026-08-16 实测截到过这个形态，是本批引入的。
   */
  const totalClasses = TOTAL_CLASSES.filter(
    (cl) => (cl.key !== "cache_read" || countsCacheRead(cacheMode)) && !isoCls.has(cl.key));

  const shown = (v?.models ?? []).filter((m) => !iso.has(m.m));
  // 与总览一致:图层自下而上 = 占比**降序**(大的贴基线,小的压在上面)。`shown` 已是降序。
  const layers: Layer[] = mode === "models"
    ? shown.map((m) => ({
        key: m.m, name: m.m, color: modelColor(m.m),
        values: (v?.buckets ?? []).map((b) => b.models?.[m.m]?.total ?? 0),
      }))
    : totalClasses.map((cl) => ({
        key: cl.key, name: cl.name, color: cl.shade(c),
        // ★ `cache_write` 并进「未命中的输入」:它是**首次发送、同时写进缓存的新内容**,
        //   本质就是没命中缓存的输入(没有缓存机制这些 token 照样要发)。用户 2026-08-15 定的三类。
        //   Codex/Grok/Kimi 该字段恒 0,但 Claude 有 2.75% —— 单列会多一条看不见的带,并进去零丢失。
        values: (v?.buckets ?? []).map((b) => cl.pick(b)),
      }));

  const isToday = range === "today";
  // 浮层标题原本写死「分模型」,总量档下会说错
  const modeWord = mode === "models" ? "分模型" : "总量";

  // 身份含平台与档位:换平台、换时间档、换分模型/总量都该重播;**自动刷新不该**。
  const intro = useIntro(`${pk}:${range}:${mode}`);

  /**
   * 费率卡脚注里的「缓存读 = 输入价 X%」。**必须实算**：新费率表下这个比值按平台差一个数量级
   * —— Claude/Codex/Kimi 是 10%，Grok 15~25%，DeepSeek 3.3%，MiMo **0.8%**。
   * 原来写死的「10%(Grok 为 85 折上下)」现在对三家是错的。
   */
  const cacheRatioText = useMemo(() => {
    const rs = (v?.models ?? []).map((m) => { const q = priceOf(m.m, pk); return q.in > 0 ? q.cacheRead / q.in : null; })
      .filter((x): x is number => x != null);
    if (!rs.length) return "—";
    const f = (x: number) => `${(x * 100).toFixed(x < 0.02 ? 1 : 0)}%`;
    // ★ 比**格式化后的字符串**,不比浮点:0.02/0.2 = 0.09999999999999999，直接比会输出「10%~10%」。
    const lo = f(Math.min(...rs)), hi = f(Math.max(...rs));
    return lo === hi ? lo : `${lo}~${hi}`;
  }, [v, pk]);
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
    { k: "总 token", v: fmtTok(v?.agg.total ?? 0), n: v?.agg.total ?? 0, fmt: fmtTok,
      sub: dTok ? `环比 ${dTok.txt}` : "环比 —",
      subC: dTok ? (dTok.up ? UP : DOWN) : t.faint },
    { k: "请求轮数", v: (v?.agg.rounds ?? 0).toLocaleString(),
      n: v?.agg.rounds ?? 0, fmt: (x) => Math.round(x).toLocaleString() },
    { k: isToday ? "小时均" : "日均", v: fmtTok((v?.agg.total ?? 0) / days),
      n: (v?.agg.total ?? 0) / days, fmt: fmtTok },
    // 与总览同名。「等效 API」这个限定词不放在标签里 —— 页面底部费率卡最后一行有完整说明
    // (「费用 = 四类 token 分别乘单价求和,是等效 API 成本;订阅制下并非实付」),标签只留短名。
    { k: "总费用", v: fmtUSD(v?.cost ?? 0), n: v?.cost ?? 0, fmt: fmtUSD, c: AMBER,
      sub: v?.saving ? `缓存已省 ${fmtUSD(v.saving)}` : undefined },
    { k: isToday ? "小时均费用" : "日均费用", v: fmtUSD((v?.cost ?? 0) / days),
      n: (v?.cost ?? 0) / days, fmt: fmtUSD, c: AMBER,
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

      {/* ★ 覆盖率提示放在 KPI **之前** —— 读者先看数字再看脚注，把「这个数不全」写进脚注
          等于没写（前车之鉴：两条「利润被高估」的警告在 tooltip 里躺了几个月没人看见）。
          只有带 coverage 字段的平台才渲染，其余平台一个像素都不多。 */}
      <CoverageBanner t={t} coverage={data?.platforms[pk]?.coverage} />

      <KpiStrip t={t} items={kpis} intro={intro} />

      {busy && !data && <div style={{ fontSize: 12, color: t.muted }}>扫描中…</div>}

      {!!v?.labels.length && (
        // ★ key 同时带 `mode`:切「分模型 ↔ 总量」也是换了一整个数据集。不带 `iso` —— 隔离模型只改
        //    图层不改日期,hover 索引仍然指同一天,重建反而会把用户停着的浮层弄没。
        <div className={introEnabled() ? "cb-wipe" : undefined} key={`w:${range}:${mode}:${v.labels[0]}`}>
        <StackedArea key={`${range}:${mode}:${v.labels[0]}`}
                     labels={v.labels} layers={layers} height={190} fmt={fmtTok} t={t}
                     tipTitle={(i) => (isToday ? `今日 ${v.labels[i].slice(11)}:00 · ${modeWord}`
                                               : `${v.labels[i]} · ${modeWord}`)} />
        </div>
      )}

      {/* ★ 总量档的图例 —— **必须带占比数字**。这个档位的已知代价就是「缓存读占 ~95%，
          另两类各自只有 ~10px 和 ~1px，构成看不出来」(用户 2026-08-15 知情选择)。
          图例里把三个数写出来，读不出来的部分至少有数兜底；没有它，页面就只剩一条纯色带。 */}
      {mode === "total" && v && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 8,
                      fontSize: 10.5, fontFamily: "'JetBrains Mono'", color: t.text2 }}>
          {TOTAL_CLASSES.filter((cl) => cl.key !== "cache_read" || countsCacheRead(cacheMode)).map((cl) => {
            const sum = v.buckets.reduce((n, b) => n + cl.pick(b), 0);
            // 占比恒按**全量**算,不随隔离变 —— 隔离只是"这张图先不画它",不是"它不存在了"
            const pct = v.agg.total ? (sum / v.agg.total) * 100 : 0;
            const off = isoCls.has(cl.key);
            return (
              <span key={cl.key} title={`${cl.full}\n点击可把它从图里摘掉（只影响这张图，不改口径/费用/总量）`}
                    onClick={() => setIsoCls((z) => {
                      const nx = new Set(z);
                      nx.has(cl.key) ? nx.delete(cl.key) : nx.add(cl.key);
                      // 全摘光就什么都不剩了,最后一类不许摘
                      // 口径已经删掉一类时，可隔离的总数也跟着少 —— 否则会允许把仅剩的一类也摘光
                      const avail = TOTAL_CLASSES.filter((x) => x.key !== "cache_read" || countsCacheRead(cacheMode)).length;
                      return nx.size >= avail ? z : nx;
                    })}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer",
                             opacity: off ? 0.38 : 1, transition: "opacity .15s",
                             textDecoration: off ? "line-through" : "none" }}>
                <span style={{ width: 9, height: 9, borderRadius: 2, background: cl.shade(c),
                               boxShadow: `0 0 0 1px ${t.cardBorder}`, flexShrink: 0,
                               opacity: off ? 0.35 : 1 }} />
                {cl.name}
                <span style={{ color: t.muted }}>{fmtTok(sum)} · {pct.toFixed(2)}%</span>
              </span>
            );
          })}
        </div>
      )}

      {/* ★ 左右分区（用户 2026-08-15 从 5 张整页 mock 里选的 L1）:模型消耗在左、费率卡在右。
          比例 1.32:1 —— 左边有「名称+条+token+占比+轮数+费用」六列,右边只有四列。
          窄窗时(<980px)退回上下堆叠,否则条形图会被压到看不出长短。 */}
      {/* ★★ D1 · 一张表，中间一条发丝竖线把「模型消耗」和「API 牌价」分成两个工作区
          （用户 2026-08-15 从三个对齐方案里选的）。

          为什么不是两块卡片：左右两栏列的是**同一批模型**，分成两块后同一个模型不在同一行，
          眼睛得来回找才能把 `gpt-5.6-sol` 和它的价对上。同一张表里，逐行对齐是天然的。
          试过「两块卡片 + 行高钉死」也能对齐，但模型名要列两遍；再去掉重复名就只能写
          「同左第 N 行」——那说明一旦逐行对齐，卡片边界本身就是多余的。

          「费率卡 · API 牌价」这个标题去掉了，改成表头上方的分组名。 */}
      {!!v?.models.length && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: `1fr ${GAP}px ${RATE_W}px`,
                        fontFamily: "'JetBrains Mono'", fontSize: 10, color: t.muted,
                        letterSpacing: ".06em", marginBottom: 4 }}>
            <span style={{ color: t.text2, fontWeight: 700 }}>模型消耗</span>
            <span />
            <span style={{ color: t.text2, fontWeight: 700 }}>API 牌价</span>
          </div>

          <div style={{ fontFamily: "'JetBrains Mono'", fontSize: 10.5 }}>
            <div style={{ ...ROW, fontSize: 9, color: t.muted, letterSpacing: ".07em",
                          padding: "0 4px 6px", borderBottom: `1px solid ${t.cardBorder}` }}>
              <span /><span>模型</span><span />
              <span style={R}>TOKEN</span><span style={R}>占比</span><span style={R}>轮数</span>
              <span style={R}>折算费用</span>
              <span style={{ borderLeft: `1px solid ${t.cardBorder}`, justifySelf: "center",
                             width: 1, alignSelf: "stretch" }} />
              <span style={R}>输入</span><span style={R}>输出</span><span style={R}>费用/百万</span>
            </div>

            {v.models.map((m) => {
              const q = priceOf(m.m, pk);
              const off = iso.has(m.m);
              return (
                <div key={m.m} onClick={() => setIso((z) => {
                  const nx = new Set(z); nx.has(m.m) ? nx.delete(m.m) : nx.add(m.m); return nx;
                })}
                     title={isPriced(m.m) ? undefined : "该型号不在费率表里，按同平台最接近的档位估算"}
                     style={{ ...ROW, padding: "5px 4px", cursor: "pointer",
                              opacity: off ? 0.38 : 1, transition: "opacity .15s",
                              borderBottom: `1px solid ${t.isDark ? "rgba(255,255,255,.035)" : "rgba(0,0,0,.04)"}` }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, flexShrink: 0,
                                 background: modelColor(m.m), opacity: off ? 0.3 : 1 }} />
                  {/* 宿主源(Reasonix/dsh)按贡献者原样**不归一化**模型名，会带客户端前缀
                      (`deepseek-pro/deepseek-v4-pro`)，比 `gpt-5.6-terra` 长一倍，列宽放不下。
                      截断可以接受，**查不到全称不行** —— 所以名字自带 title。 */}
                  <span title={m.m}
                        style={{ color: t.text2, overflow: "hidden", textOverflow: "ellipsis",
                                 whiteSpace: "nowrap" }}>{m.m}</span>
                  <div style={{ height: 6, borderRadius: 3, background: t.barTrack,
                                overflow: "hidden", marginRight: 10, minWidth: 40 }}>
                    <div style={{ width: `${(m.total / Math.max(1, v.models[0].total)) * 100}%`,
                                  height: "100%", background: modelColor(m.m) }} />
                  </div>
                  <span style={{ ...R, fontWeight: 700 }}>{fmtTok(m.total)}</span>
                  <span style={{ ...R, color: t.muted }}>
                    {((m.total / Math.max(1, v.agg.total)) * 100).toFixed(1)}%
                  </span>
                  <span style={{ ...R, color: t.muted }}>{m.rounds.toLocaleString()}</span>
                  <span style={{ ...R, color: AMBER, fontWeight: 700 }}>{fmtUSD(m.cost)}</span>
                  <span style={{ borderLeft: `1px solid ${t.cardBorder}`, justifySelf: "center",
                                 width: 1, alignSelf: "stretch" }} />
                  <span style={R}>
                    ${money(q.in)}{!isPriced(m.m) && <span style={{ color: AMBER }}> *</span>}
                  </span>
                  <span style={R}>${money(q.out)}</span>
                  {/* ★ 第三列不是再抄一遍牌价，是**这个模型的实际单价**（费用÷token）。
                      同一张表里牌价已经在左边两列了；实际单价才回答「钱花在哪个型号上」——
                      本机实测 sol $0.840/M vs luna $0.038/M，差 22 倍。 */}
                  <span style={{ ...R, color: t.muted }} title="折算费用 ÷ 该模型 token 数">
                    {m.total > 0 ? `$${(m.cost / (m.total / 1e6)).toFixed(3)}` : "—"}
                  </span>
                </div>
              );
            })}
          </div>
          <div style={{ fontSize: 9.5, color: t.faint, marginTop: 8, lineHeight: 1.5 }}>
            {/* 脚注只解释当前口径真正用到的价:讲一个没参与计算的折扣率,读者会以为费用里含了它 */}
            {countsCacheRead(cacheMode)
              ? `缓存读 = 输入价 ${cacheRatioText} · `
              : "当前口径不计入缓存读 · "}
            {countsCacheWrite(cacheMode)
              ? "Anthropic 缓存写 1.25x · "
              : "缓存写同样不计入 · "}
            {/* 构成行原来挂在「费率卡」标题旁，标题删了就挪到这儿 —— 它把 cache_write 单列，
                与上面三类图例(把 cache_write 并进「新输入」)不重复。 */}
            {mix && <>本期构成 {mix}</>}
            <br />
            <span style={{ color: "#E0901C" }}>⚠️ 标 * 的是估算价</span>
            ，按同平台最接近的档位推的，不是准数。牌价 2026-08-15 取自各家官网，费率表在 <code>src/rates.ts</code>。
            <br />
            费用 = {countedClasses(cacheMode)} 类 token 分别乘单价求和，是<b>等效 API 成本</b>；订阅制下并非实付。
          </div>
        </div>
      )}
    </div>
  );
}

