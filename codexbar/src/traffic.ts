import { costOf, cacheSavingOf } from "./rates";
import { platformColor } from "./theme";

/** traffic/scan.py 的输出契约。四个 token 类**互不相交**,相加才是 total(见 scan.py 头部)。 */
export interface ModelBucket {
  uncached_in: number; cache_read: number; cache_write: number;
  output: number; total: number; rounds: number;
}
export interface Bucket extends ModelBucket {
  models: Record<string, ModelBucket>;
}
/**
 * 采集完整度。**只有采集不完整的平台才有这个字段** —— 其余平台的数据是各家 CLI
 * 自己落的盘,本来就是全量,平白挂一句免责声明只会稀释真正需要注意的那一条。
 *
 * 目前只有 Antigravity(agy):它自己不落用量,只有经 `bin/agy` wrapper 的 print 模式
 * 会被记账,交互式会话一个字都进不来。
 */
export interface Coverage {
  covered: number;
  total: number;
  unit: string;           // 目前恒为 "turn"
  days: number;           // 算这个覆盖率用的窗口天数(= scan 的 --days，app 恒 90)
  since: number | null;   // 账本最早一条的 epoch 秒
}
export interface Platform {
  name: string;
  /** 由 scan.py 的注册表下发。加平台只改 scan.py,前端自动跟上 */
  color?: string;
  days: Record<string, Bucket>;   // 已按自然日窗口补零
  hours: Record<string, Bucket>;  // 今日 00 点到当前小时,已补零
  available: boolean;
  coverage?: Coverage;
}

/** 覆盖率百分比(0~100)。分母为 0 时返回 null 而不是 0 —— 「没有分母」不是「覆盖 0%」。 */
export function coveragePct(c: Coverage | undefined): number | null {
  if (!c || !c.total) return null;
  return (c.covered / c.total) * 100;
}

/**
 * 覆盖率的完整说明。**单一真源** —— 卡片徽章与详情页都读它,不许各写一份:
 * 这段话要解释的是「数字为什么偏小」,两处说法不一致比不说更糟。
 */
export function coverageNote(c: Coverage | undefined): string {
  const pct = coveragePct(c);
  if (pct == null || !c) return "";
  const since = c.since
    ? new Date(c.since * 1000).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })
    : null;
  // ★ 窗口用 `c.days`（后端算这个比值时用的那个），**不是**用户当前选的日期档。
  //   两者不是一回事：档位只改图表窗口，分母始终是扫描窗口。
  // ★ 这里是纯文本，不经 Markdown 渲染 —— 写 `**下界**` 会原样显示出星号（实测截到过）。
  return `Antigravity 自己不记录用量，只有经 wrapper 的 print 模式（omc ask / omc team）会被记账，`
    + `交互式会话拿不到。近 ${c.days} 天覆盖 ${c.covered}/${c.total} 轮（${pct.toFixed(1)}%）`
    + (since ? `，采集自 ${since} 起。` : "。")
    + `所以这个数字是下界，不是 Antigravity 的全部消耗。`;
}
/**
 * agy 的**额度消耗**序列（`scan.py` 的 `_agy_quota_series`）。
 *
 * ★★ **这是与 `platforms` 完全不同的一本账,所以它是独立顶层键、独立类型。**
 *   · `platforms[*]` 的单位是 token,可求和、可乘单价得出费用;
 *   · 这里的单位是 `quota_pct`（额度百分比），**不可与 token 相加、不可换算成钱**。
 *
 * 存在的理由：token 账本只覆盖 print 模式（近 90 天 15.9%），交互式会话一个字都进不来；
 * 而额度是服务端真值，交互态照样会掉。所以这条**覆盖 100%，代价是换了量纲**。
 */
export interface AgyQuotaSeries {
  unit: "quota_pct";
  days: number;
  buckets: Record<string, {
    group: string | null;
    window: string | null;
    consumed_pct: number;
    /** 额度**恢复**量（滚动窗口把旧消耗老化掉）。★ 与 `consumed_pct` **不相抵**：
     *  两者是不同的量，相减会让"用了多少"凭空变小。 */
    recovered_pct: number;
    /** ★ 采样间隔相对窗口太长 ⇒ 中间的消耗可能已经完全老化、永远看不到了。
     *  这个数是**下界**，UI 必须如实标注（用「≥」，不是脚注）。 */
    lower_bound: boolean;
    /** 解释不了的现象计数。滚动窗口模型下正常应为 0。 */
    anomalies: number;
  }>;
  daily: Record<string, Record<string, number>>;
  /** 观测窗口。★ 与 token 那条「采集自 08/19 起」同理：不给起始时间，
   *  一个偏小的数会被读成"用得少"而不是"还没看到那么早"。 */
  coverage: { first: number; last: number; n: number } | null;
}

export interface TrafficData {
  platforms: Record<string, Platform>;
  scan: { scanned: number; reused: number; files: number; elapsed_ms?: number };
  /** ★ 只有 agy 有；`null` = 样本还不足两个，推不出任何消耗。
   *  **`null` 必须显示成「观测还不够」，不能画成 0** —— 0 会被读成"没用过"。 */
  agy_quota?: AgyQuotaSeries | null;
  generated_at: number;
}

/** agy 额度序列的披露文案（**唯一出处**，同 `coverageNote` 的纪律）。 */
export function agyQuotaNote(q: AgyQuotaSeries | null | undefined): string {
  if (!q) {
    return `额度消耗序列还没有足够观测（至少要两个采样点才能差分）。`
      + `这不是「没有消耗」——跑一次 agy 就会开始累积。`;
  }
  const anom = Object.values(q.buckets).reduce((n, b) => n + b.anomalies, 0);
  const lb = Object.values(q.buckets).some(b => b.lower_bound);
  const since = q.coverage
    ? new Date(q.coverage.first * 1000).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })
    : null;
  const rec = Object.values(q.buckets).reduce((n, b) => n + b.recovered_pct, 0);
  return `按额度水位差分得出，覆盖**全部** agy 用量（含交互式会话），`
    + `与上面的 token 统计是两本账：单位是额度百分比，不可相加、不可折算成钱。`
    + (since ? `采样自 ${since} 起，${q.coverage!.n} 个点。` : "")
    // ★ agy 是**滚动窗口**（实测：resetTime 不变时 remaining 会上涨），旧消耗会老化退出，
    //   所以"恢复"是常态而不是异常，要说明它、且说明它没有和消耗相抵。
    + (rec > 0.01 ? `期间额度恢复了 ${rec.toFixed(2)}%（滚动窗口把旧消耗老化掉了），`
                  + `已单独计数、未与消耗相抵。` : "")
    + (lb ? `标「≥」的是下界——采样间隔相对窗口偏长时，中间的消耗可能已经老化掉、看不到了。` : "")
    + (anom ? `另有 ${anom} 处解释不了的水位变化，未计入消耗。` : "");
}

/** 取平台色:优先用 scan.py 下发的,拿不到才回落到 `theme.ts` 的兜底表。 */
export function colorOf(data: TrafficData | null, key: string): string {
  return data?.platforms[key]?.color || platformColor(key);
}

export const RANGES = ["today", 7, 14, 30, 90] as const;
export type Range = (typeof RANGES)[number];
export const rangeLabel = (r: Range): string => (r === "today" ? "今日" : `${r}d`);

/**
 * 缓存计入口径(用户 2026-08-11 加,三档一次到位)。**token 数与费用同时跟着变** ——
 * 两者都由那四个互不相交的类算出来,只改一个会让"总费用"和"总 token"说的不是同一批数据。
 *
 * 本机 90 天实测的量级(说明为什么这三档不是细微差别):
 *   full   34.20B / $24,712   cache_read 96.01% · cache_write 2.64% · uncached_in 0.93% · output 0.42%
 *   noRead  1.36B / $ 9,169
 *   none    0.46B / $ 3,250
 *
 * ★ `noRead` 与 `none` 差 3 倍,分界全在 `cache_write`:它是**首次发送并写入缓存的新内容**,
 *   没有缓存机制时这些 token 照样要发(只是按普通输入价计费)。所以
 *   - `noRead` 回答「不靠缓存的话我实际消耗多少」—— 保留 cache_write 才不低估真实工作量;
 *   - `none` 回答「完全不沾缓存的那部分有多少」—— 代价是丢掉 0.9B 真实新内容
 *     (它是 uncached_in + output 加起来的两倍)。
 */
export const CACHE_MODES = ["full", "noRead", "none"] as const;
export type CacheMode = (typeof CACHE_MODES)[number];

export const cacheModeLabel = (m: CacheMode): string =>
  m === "full" ? "含缓存" : m === "noRead" ? "不含缓存读" : "不含缓存";

export const cacheModeDesc = (m: CacheMode): string =>
  m === "full"
    ? "四类 token 全计入(uncached_in + 缓存读 + 缓存写 + output)。这是原始口径。"
    : m === "noRead"
    ? "排除缓存读,保留缓存写 —— 缓存写是首次发送的新内容,没有缓存也要发。"
    : "缓存读和缓存写都排除,只留 uncached_in + output。";

const shapeBucket = (b: Bucket, mode: CacheMode): Bucket => {
  const cache_write = mode === "none" ? 0 : b.cache_write;
  const models: Record<string, ModelBucket> = {};
  for (const [k, v] of Object.entries(b.models ?? {})) {
    const cw = mode === "none" ? 0 : v.cache_write;
    models[k] = { ...v, cache_read: 0, cache_write: cw,
                  total: v.uncached_in + cw + v.output };
  }
  return { ...b, cache_read: 0, cache_write,
           total: b.uncached_in + cache_write + b.output, models };
};

/**
 * 按口径重塑数据。**只在 `useTraffic` 的出口调用一次**,下游 30 多处读 `b.total` / `costOfBucket`
 * 的地方全部自动跟上 —— 逐处去改必然漏,而漏掉的那处会显示另一个口径的数字。
 * 费用也一起对了:`costOf` 就是拿这四个类分别乘单价的,类被清零费用自然不含它。
 *
 * `full` 直接返回原对象(引用不变),所以默认口径下这层是零开销、零行为变化。
 */
export function applyCacheMode(data: TrafficData | null, mode: CacheMode): TrafficData | null {
  if (!data || mode === "full") return data;
  const platforms: Record<string, Platform> = {};
  for (const [k, p] of Object.entries(data.platforms)) {
    const days: Record<string, Bucket> = {};
    const hours: Record<string, Bucket> = {};
    for (const [d, b] of Object.entries(p.days)) days[d] = shapeBucket(b, mode);
    for (const [h, b] of Object.entries(p.hours)) hours[h] = shapeBucket(b, mode);
    platforms[k] = { ...p, days, hours };
  }
  return { ...data, platforms };
}

/**
 * 平台的**本机呈现偏好**(用户 2026-08-12)。`scan.py` 的注册表仍是唯一决定"有没有数据"的地方;
 * 这一层只管"怎么显示"——改名、改色、停用、排序。**新增一家平台不在这里**,那等于写一个解析器
 * (`scan.py` 顶部那条:四家四种形状,猜字段名会静默算错数)。
 */
export interface PlatformPrefs {
  /** 用户排的列表顺序。不在里面的键排在后面(按占比降序)。**只影响列表/图例,不影响堆叠图层**。 */
  order: string[];
  by: Record<string, { name?: string; color?: string; off?: boolean }>;
}

export const EMPTY_PREFS: PlatformPrefs = { order: [], by: {} };

/**
 * 应用平台偏好。**停用 = 整家从数据里移除**(用户 2026-08-12 定稿:总 token / 总费用跟着扣),
 * 所以必须和 `applyCacheMode` 一样放在 `useTraffic` 出口做一次 —— 下游读 `data.platforms` 的
 * 30+ 处(总计、环比、最大占比、图表、菜单栏)全部自动跟上。逐处过滤必然漏，
 * 而漏掉的那处会把已停用的平台算回总数里。
 *
 * 改名/改色是就地覆盖:`scan.py` 下发的值仍是默认,用户没设就用它。
 */
export function applyPlatformPrefs(data: TrafficData | null, prefs: PlatformPrefs): TrafficData | null {
  if (!data) return null;
  const entries = Object.entries(data.platforms).filter(([k]) => !prefs.by[k]?.off);
  if (entries.length === Object.keys(data.platforms).length
      && !entries.some(([k]) => prefs.by[k]?.name || prefs.by[k]?.color)) {
    return data;                     // 无任何覆盖 ⇒ 原引用,零开销
  }
  const platforms: Record<string, Platform> = {};
  for (const [k, p] of entries) {
    const o = prefs.by[k];
    platforms[k] = { ...p, name: o?.name || p.name, color: o?.color || p.color };
  }
  return { ...data, platforms };
}

/**
 * 按用户顺序排列平台键。**只给列表/图例用** —— 堆叠图层仍按占比降序
 * (「占大头的铺满基线比悬在半空清楚」是 2026-08-09 看了两版实物定下的，这次没动它)。
 * 没排过的键跟在后面，按传入的 `volume` 降序，保证新出现的一家不会莫名跑到最前。
 */
export function orderedKeys(keys: string[], prefs: PlatformPrefs,
                            volume: (k: string) => number): string[] {
  const rank = new Map(prefs.order.map((k, i) => [k, i]));
  return [...keys].sort((a, b) => {
    const ra = rank.get(a), rb = rank.get(b);
    if (ra != null && rb != null) return ra - rb;
    if (ra != null) return -1;
    if (rb != null) return 1;
    return volume(b) - volume(a);
  });
}

/**
 * 该口径**计入**哪些类。UI 靠这两个函数决定**展示哪些指标** —— 用户 2026-08-11 定稿:
 * 不计入缓存时,缓存相关指标要**从页面上消失**,而不是显示成 0%/「已排除 X」。
 * 理由:一个恒为 0 的缓存占比会被读成「没用到缓存」,与事实相反;而一个当前口径根本不参与
 * 计算的指标继续占着版面,只会让人怀疑这两个数是不是同一批数据。
 *
 * 判定只写这一份 —— 页面各写一份 `mode === "full"` 迟早在某个边界上互相矛盾。
 */
export const countsCacheRead = (m: CacheMode): boolean => m === "full";
export const countsCacheWrite = (m: CacheMode): boolean => m !== "none";
/** 当前口径下参与合计的 token 类数量(费率卡脚注要说"几类分别乘单价")。 */
export const countedClasses = (m: CacheMode): number =>
  2 + (countsCacheRead(m) ? 1 : 0) + (countsCacheWrite(m) ? 1 : 0);

/**
 * 平台详情页「构成」行要列的项。**只列当前口径计入的类,且分母就是这几类之和** ——
 * 所以百分比恒加到 100。若沿用 `a.total` 当分母,不含缓存时四项加起来只有 4%,
 * 比不显示更糟(看的人会以为剩下 96% 去向不明)。
 *
 * 做成纯函数放在这里,是为了让这条展示规则**能被断言**(scratch/verify_cache_mode_*.ts),
 * 而不是埋在 JSX 里只能靠眼睛看。传入的 `a` 必须是**未重塑**的聚合,重塑后缓存类已归零。
 */
export function mixParts(a: Bucket, mode: CacheMode): { name: string; pct: number }[] {
  const parts: [string, number][] = [];
  if (countsCacheRead(mode)) parts.push(["缓存读", a.cache_read]);
  parts.push(["输入", a.uncached_in]);
  if (countsCacheWrite(mode)) parts.push(["缓存写", a.cache_write]);
  parts.push(["输出", a.output]);
  const tot = parts.reduce((s, [, x]) => s + x, 0);
  return tot ? parts.map(([name, x]) => ({ name, pct: (x / tot) * 100 })) : [];
}

const EMPTY: Bucket = {
  uncached_in: 0, cache_read: 0, cache_write: 0, output: 0, total: 0, rounds: 0, models: {},
};

/** 取某平台在某时间段的 (labels, buckets)。scan.py 已补零,这里只做切片。 */
export function bucketsFor(data: TrafficData, key: string, range: Range):
  { labels: string[]; buckets: Bucket[] } {
  const p = data.platforms[key];
  if (!p) return { labels: [], buckets: [] };
  if (range === "today") {
    const labels = Object.keys(p.hours).sort();
    return { labels, buckets: labels.map((k) => p.hours[k] ?? EMPTY) };
  }
  const all = Object.keys(p.days).sort();
  const labels = all.slice(-range);
  return { labels, buckets: labels.map((k) => p.days[k] ?? EMPTY) };
}

export function sumBuckets(bs: Bucket[]): Bucket {
  const out: Bucket = { ...EMPTY, models: {} };
  for (const b of bs) {
    out.uncached_in += b.uncached_in; out.cache_read += b.cache_read;
    out.cache_write += b.cache_write; out.output += b.output;
    out.total += b.total; out.rounds += b.rounds;
    for (const [m, mv] of Object.entries(b.models ?? {})) {
      const t = out.models[m] ?? (out.models[m] = {
        uncached_in: 0, cache_read: 0, cache_write: 0, output: 0, total: 0, rounds: 0,
      });
      t.uncached_in += mv.uncached_in; t.cache_read += mv.cache_read;
      t.cache_write += mv.cache_write; t.output += mv.output;
      t.total += mv.total; t.rounds += mv.rounds;
    }
  }
  return out;
}

/** 按四类 token 分别乘各模型单价求和 —— 不用交接稿 §8 的构成假设(我们有真实分类数据)。 */
export function costOfBucket(b: Bucket, platform: string): number {
  let usd = 0;
  for (const [m, mv] of Object.entries(b.models ?? {})) usd += costOf(mv, m, platform);
  return usd;
}

/** 缓存相对"全按输入价"省下的金额,用于在 KPI 上显式化「费用已按缓存折价」。 */
export function savingOfBucket(b: Bucket, platform: string): number {
  let usd = 0;
  for (const [m, mv] of Object.entries(b.models ?? {})) usd += cacheSavingOf(mv, m, platform);
  return usd;
}

export function topModels(bs: Bucket[], n: number): { model: string; share: number; total: number }[] {
  const agg = sumBuckets(bs);
  const tot = Math.max(1, agg.total);
  return Object.entries(agg.models)
    .map(([model, mv]) => ({ model, total: mv.total, share: mv.total / tot }))
    .sort((a, b) => b.total - a.total)
    .slice(0, n);
}

/** 菜单栏「今日」Tab 的取数(交接稿 §4 的 `TodayTab`)。与主窗口今日视图**同源同口径**。 */
export interface TodayView {
  hours: string[];                       // 已过去的整点标签,`2026-08-09T09` 形态
  totalTok: number;
  totalCost: number;
  /** vs 昨日**整天**;null = 昨天没数据,不能算 */
  deltaPct: number | null;
  peak: { v: number; hour: string } | null;
  /** 每个小时的合计 token 与等效费用,与 `hours` 等长。菜单栏悬浮读数用。 */
  hourTok: number[];
  hourCost: number[];
  /** 自下而上 = 占比降序(与主窗口同规则) */
  series: { key: string; name: string; values: number[] }[];
  per: { key: string; name: string; pct: number; tok: number; cost: number; deltaPct: number | null }[];
}

const pctDelta = (now: number, base: number): number | null =>
  base > 0 ? ((now - base) / base) * 100 : null;

export function todayView(data: TrafficData | null): TodayView | null {
  if (!data) return null;
  const keys = Object.keys(data.platforms);
  if (!keys.length) return null;
  const hours = Object.keys(data.platforms[keys[0]].hours).sort();
  if (!hours.length) return null;

  const rows = keys.map((k) => {
    const p = data.platforms[k];
    const values = hours.map((h) => p.hours[h]?.total ?? 0);
    const agg = sumBuckets(hours.map((h) => p.hours[h]).filter(Boolean));
    // 昨日基准取**整天**:今日是进行时,拿它比昨日同样的进行时需要昨日的小时明细,scan.py 只留今天的。
    const days = Object.keys(p.days).sort();
    const yd = days[days.length - 2];
    const yBucket = yd ? p.days[yd] : null;
    return {
      key: k, name: p.name, values,
      tok: agg.total, cost: costOfBucket(agg, k),
      deltaPct: pctDelta(agg.total, yBucket?.total ?? 0),
      yTok: yBucket?.total ?? 0, yCost: yBucket ? costOfBucket(yBucket, k) : 0,
    };
  });
  rows.sort((a, b) => b.tok - a.tok);

  const totalTok = rows.reduce((s, r) => s + r.tok, 0);
  const totalCost = rows.reduce((s, r) => s + r.cost, 0);
  const yTok = rows.reduce((s, r) => s + r.yTok, 0);

  const stacked = hours.map((_, i) => rows.reduce((s, r) => s + r.values[i], 0));
  const hourCost = hours.map((h) =>
    keys.reduce((s, k) => s + (data.platforms[k].hours[h] ? costOfBucket(data.platforms[k].hours[h], k) : 0), 0));
  let pi = -1;
  stacked.forEach((v, i) => { if (pi < 0 || v > stacked[pi]) pi = i; });

  return {
    hours, totalTok, totalCost,
    deltaPct: pctDelta(totalTok, yTok),
    peak: pi >= 0 && stacked[pi] > 0 ? { v: stacked[pi], hour: hours[pi] } : null,
    hourTok: stacked, hourCost,
    series: rows.map((r) => ({ key: r.key, name: r.name, values: r.values })),
    per: rows.map((r) => ({
      key: r.key, name: r.name, tok: r.tok, cost: r.cost, deltaPct: r.deltaPct,
      pct: totalTok > 0 ? (r.tok / totalTok) * 100 : 0,
    })),
  };
}

export const fmtTok = (n: number): string =>
  n >= 1e9 ? `${(n / 1e9).toFixed(2)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(0)}M`
  : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(Math.round(n));
