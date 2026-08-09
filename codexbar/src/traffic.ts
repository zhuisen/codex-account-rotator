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
export interface Platform {
  name: string;
  /** 由 scan.py 的注册表下发。加平台只改 scan.py,前端自动跟上 */
  color?: string;
  days: Record<string, Bucket>;   // 已按自然日窗口补零
  hours: Record<string, Bucket>;  // 今日 00 点到当前小时,已补零
  available: boolean;
}
export interface TrafficData {
  platforms: Record<string, Platform>;
  scan: { scanned: number; reused: number; files: number; elapsed_ms?: number };
  generated_at: number;
}

/** 取平台色:优先用 scan.py 下发的,拿不到才回落到 `theme.ts` 的兜底表。 */
export function colorOf(data: TrafficData | null, key: string): string {
  return data?.platforms[key]?.color || platformColor(key);
}

export const RANGES = ["today", 7, 14, 30, 90] as const;
export type Range = (typeof RANGES)[number];
export const rangeLabel = (r: Range): string => (r === "today" ? "今日" : `${r}d`);

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
  let pi = -1;
  stacked.forEach((v, i) => { if (pi < 0 || v > stacked[pi]) pi = i; });

  return {
    hours, totalTok, totalCost,
    deltaPct: pctDelta(totalTok, yTok),
    peak: pi >= 0 && stacked[pi] > 0 ? { v: stacked[pi], hour: hours[pi] } : null,
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
