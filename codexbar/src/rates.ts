/**
 * 费率表（$ / M token）· 交接稿 §8 + §11.4「费率表配置化」
 *
 * ★ 费用一律是**按牌价 + 四类 token 折算的等效 API 成本**，不是实付。订阅制用户没有这笔账单，
 *   这个数字只回答「同样的量走 API 要多少钱」。UI 各处必须标注。
 *
 * ★ 计算不使用交接稿 §8 的「构成假设」(f/w/r/o)——那是原型没有真实数据时的近似。我们有 transcript
 *   里真实的四类 token，直接分别乘单价求和（§8 明确写了「接真实数据时…不再需要构成假设」）。
 *
 * ★ `est: true` = 估算价。**本机实际在跑的 codex / grok 模型不在交接稿的费率表里**
 *   （稿子列 gpt-5.3-codex / grok-4.5-code，实际是 gpt-5.6-sol / gpt-5.5 / grok-4.5-build），
 *   这些一律标 est 并在费率卡里显式标注，绝不拿旧型号的价悄悄顶上去当准数。
 */

export interface Price {
  in: number;          // 输入
  cacheRead: number;   // 缓存读
  out: number;         // 输出
  cacheWrite?: number; // 缓存写（Anthropic = 1.25×输入；OpenAI/Grok 该端点实测恒 0，不需要）
  est?: boolean;       // 估算价
  note?: string;
}

export const RATES: Record<string, Price> = {
  // ── Claude（价格取自 Anthropic 公开牌价；缓存读 = 输入 10%，缓存写 = 输入 1.25×）
  "claude-fable-5":    { in: 10.0, cacheRead: 1.0,   out: 50.0, cacheWrite: 12.5 },
  "claude-opus-5":     { in: 5.0,  cacheRead: 0.5,   out: 25.0, cacheWrite: 6.25 },
  "claude-opus-4-8":   { in: 5.0,  cacheRead: 0.5,   out: 25.0, cacheWrite: 6.25 },
  "claude-opus-4-7":   { in: 5.0,  cacheRead: 0.5,   out: 25.0, cacheWrite: 6.25 },
  "claude-opus-4-6":   { in: 5.0,  cacheRead: 0.5,   out: 25.0, cacheWrite: 6.25 },
  "claude-sonnet-5":   { in: 2.0,  cacheRead: 0.2,   out: 10.0, cacheWrite: 2.5,
                         note: "介绍价至 2026-08-31，之后 $3/$15" },
  "claude-sonnet-4-6": { in: 3.0,  cacheRead: 0.3,   out: 15.0, cacheWrite: 3.75 },
  "claude-haiku-4-5":  { in: 1.0,  cacheRead: 0.1,   out: 5.0,  cacheWrite: 1.25 },

  // ── Codex（交接稿 §8 列的型号）
  "gpt-5.3-codex":      { in: 1.75, cacheRead: 0.175, out: 14.0 },
  "gpt-5.3-codex-mini": { in: 1.5,  cacheRead: 0.15,  out: 6.0, est: true, note: "输出为估算价" },
  "gpt-5-codex":        { in: 1.25, cacheRead: 0.125, out: 10.0 },

  // ── Grok（交接稿 §8 列的型号）
  "grok-4.5-code": { in: 2.0,  cacheRead: 0.3, out: 6.0, note: "按 Grok 4.5 牌价" },
  "grok-4":        { in: 1.25, cacheRead: 0.2, out: 2.5, note: "按 Grok 4.3 牌价" },
  "grok-4-fast":   { in: 1.0,  cacheRead: 0.2, out: 2.0, note: "按 Grok Build 0.1 牌价" },
};

/** 本机在跑但费率表里没有的型号，按同平台最接近的档位估算，**一律标 est**。 */
const FALLBACK: Record<string, Price> = {
  claude: { in: 5.0,  cacheRead: 0.5,   out: 25.0, cacheWrite: 6.25, est: true },
  codex:  { in: 1.75, cacheRead: 0.175, out: 14.0, est: true },
  grok:   { in: 2.0,  cacheRead: 0.3,   out: 6.0,  est: true },
  // ⚠️ kimi k3 的官方牌价我没有可信来源,这里是**占位数**,只为让费用列不空着。
  //    拿到真价改这里(以及下面 RATES 里补一条 `kimi-code/k3`),UI 会一直标 * 提醒它是估算。
  kimi:   { in: 0.6,  cacheRead: 0.06,  out: 2.5,  est: true, note: "k3 牌价未核实,占位" },
};

export function priceOf(model: string, platform: string): Price {
  const hit = RATES[model];
  if (hit) return hit;
  return FALLBACK[platform] ?? { in: 0, cacheRead: 0, out: 0, est: true };
}

/** 该模型是否有明确牌价（false = 用了同平台兜底价，UI 必须标出来）。 */
export function isPriced(model: string): boolean {
  return model in RATES;
}

export interface TokenClasses {
  uncached_in: number;
  cache_read: number;
  cache_write: number;
  output: number;
}

/** 四类 token 分别乘单价 → 美元。不用构成假设。 */
export function costOf(t: TokenClasses, model: string, platform: string): number {
  const p = priceOf(model, platform);
  const cw = p.cacheWrite ?? p.in;   // 无缓存写价的平台按输入价（该端点实测恒 0，不影响结果）
  return (t.uncached_in * p.in + t.cache_read * p.cacheRead
          + t.cache_write * cw + t.output * p.out) / 1e6;
}

/**
 * 缓存省下多少钱 = 缓存读的量 × (输入价 − 缓存读价)。
 *
 * 存在的意义是**让"费用已按缓存折价"这件事在 UI 上可见**:`costOf` 一直是四类分别乘单价算的
 * (缓存读 = 输入价的 10%),但界面上只有一个总数,看不出折没折 —— 用户 2026-08-09 因此问
 * 「费用要计算上缓存价格,而不是全量价格」。把省下的钱摆出来,这个疑问就不用再问第二次。
 */
export function cacheSavingOf(t: TokenClasses, model: string, platform: string): number {
  const p = priceOf(model, platform);
  return (t.cache_read * (p.in - p.cacheRead)) / 1e6;
}

export const fmtUSD = (n: number): string =>
  n >= 1000 ? `$${(n / 1000).toFixed(2)}K` : n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(3)}`;
