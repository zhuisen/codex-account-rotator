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
  // ── Claude · platform.claude.com/docs/en/about-claude/pricing（2026-08-15 取）
  //    缓存写取 **5m** 档(1.25×输入);1h 档是 2×,transcript 区分不出来,取常用的 5m。
  "claude-fable-5":    { in: 10.0, cacheRead: 1.0,  out: 50.0, cacheWrite: 12.5 },
  "claude-mythos-5":   { in: 10.0, cacheRead: 1.0,  out: 50.0, cacheWrite: 12.5 },
  "claude-opus-5":     { in: 5.0,  cacheRead: 0.5,  out: 25.0, cacheWrite: 6.25 },
  "claude-opus-4-8":   { in: 5.0,  cacheRead: 0.5,  out: 25.0, cacheWrite: 6.25 },
  "claude-opus-4-7":   { in: 5.0,  cacheRead: 0.5,  out: 25.0, cacheWrite: 6.25 },
  "claude-opus-4-6":   { in: 5.0,  cacheRead: 0.5,  out: 25.0, cacheWrite: 6.25 },
  "claude-opus-4-5":   { in: 5.0,  cacheRead: 0.5,  out: 25.0, cacheWrite: 6.25 },
  // ★ $2/$10 原是介绍价,官方已明确**转为标准价**,9/1 涨到 $3/$15 的计划取消(2026-08-15 核)。
  //   旧注释「介绍价至 2026-08-31，之后 $3/$15」作废 —— 删掉而不是留着,留着会让人按 $3 心算。
  "claude-sonnet-5":   { in: 2.0,  cacheRead: 0.2,  out: 10.0, cacheWrite: 2.5 },
  "claude-sonnet-4-6": { in: 3.0,  cacheRead: 0.3,  out: 15.0, cacheWrite: 3.75 },
  "claude-haiku-4-5":  { in: 1.0,  cacheRead: 0.1,  out: 5.0,  cacheWrite: 1.25 },

  // ── Codex / OpenAI · developers.openai.com/api/docs/pricing（2026-08-15 取,Standard 档）
  //    ★ 本机跑的就是 gpt-5.6-sol 与 gpt-5.5,此前它们**不在表里**、全走 $1.75/$14 的兜底,
  //      把 Codex 30 天费用低估成真价的 1/2.55（$1,020 vs $2,595,实测)。
  "gpt-5.6-sol":   { in: 5.0,  cacheRead: 0.5,  out: 30.0 },
  "gpt-5.6-terra": { in: 2.0,  cacheRead: 0.2,  out: 12.0 },
  "gpt-5.6-luna":  { in: 0.2,  cacheRead: 0.02, out: 1.2 },
  "gpt-5.6-cyber": { in: 12.5, cacheRead: 1.25, out: 75.0 },
  "gpt-5.5":       { in: 5.0,  cacheRead: 0.5,  out: 30.0, note: "<272K 上下文档" },
  "gpt-5.5-cyber": { in: 12.5, cacheRead: 1.25, out: 75.0 },
  "gpt-5.5-pro":   { in: 30.0, cacheRead: 3.0,  out: 180.0, est: true,
                     note: "官方未列缓存价,按输入 10% 估" },

  // ── Grok / xAI · docs.x.ai/docs/models（2026-08-15 取,<200k 档）
  //    ⚠️ 官方只列 Grok 4.5 / 4.6 / Build 0.1,**没有 `-build` 后缀的条目**。本机跑的
  //      `grok-4.5-build` / `grok-4.6-build` 究竟是「Grok 4.x 走 Build 界面」还是独立的
  //      「Grok Build」产品,文档区分不出来 —— 按同版本号的 Grok 4.x 计并标 est。
  //      两种解释在输入价上差 2 倍($2 vs $1),别当准数用。
  "grok-4.6":       { in: 2.0, cacheRead: 0.5, out: 6.0 },
  "grok-4.5":       { in: 2.0, cacheRead: 0.3, out: 6.0 },
  "grok-4.6-build": { in: 2.0, cacheRead: 0.5, out: 6.0, est: true, note: "按 Grok 4.6 计,见上" },
  "grok-4.5-build": { in: 2.0, cacheRead: 0.3, out: 6.0, est: true, note: "按 Grok 4.5 计,见上" },
  "grok-build-0.1": { in: 1.0, cacheRead: 0.2, out: 2.0 },

  // ── Kimi / Moonshot · platform.kimi.ai/docs/pricing/chat-k3（2026-08-15 取）
  //    全上下文统一价、无长文本溢价。此前是占位数 $0.6/$2.5,现为官方价。
  "kimi-k3":      { in: 3.0, cacheRead: 0.3, out: 15.0 },
  "kimi-code/k3": { in: 3.0, cacheRead: 0.3, out: 15.0, note: "= kimi-k3 牌价" },

  // ── MiMo / 小米 · mimo.mi.com/docs/zh-CN/price/pay-as-you-go（国际站 USD,页面 2026-08-06 更新）
  //    ★ 此前 MiMo **连兜底都没有**,priceOf 返回全 0,102M token 一直显示成 $0.000。
  //    缓存写官方标「限时免费」⇒ 显式写 cacheWrite: 0,不能留空回落到输入价。
  "mimo-v2.5-pro": { in: 0.435, cacheRead: 0.0036, out: 0.87, cacheWrite: 0, note: "缓存写限时免费" },
  "mimo-v2.5":     { in: 0.14,  cacheRead: 0.0028, out: 0.28, cacheWrite: 0, note: "缓存写限时免费" },

  // ── DeepSeek · api-docs.deepseek.com/quick_start/pricing + 官方 2026-08-13 调价公告
  //    ★★ 新价 **2026-08-17 00:00 北京时间**(= 08-16 16:00 UTC)生效,且是**峰谷分时**:
  //       高峰(北京 9:00-12:00、14:00-18:00)为下列价,空闲时段**减半**。
  //       我们按天分桶,分不出请求落在哪个时段 ⇒ 一律记**高峰价 = 上界**,真实账单只会更低、
  //       最多低一半。费率卡脚注必须说明这点,否则读者会把上界当点估计。
  "deepseek-v4-pro":   { in: 1.32, cacheRead: 0.044, out: 3.96, est: true, note: "高峰价上界;空闲减半" },
  "deepseek-v4-flash": { in: 0.44, cacheRead: 0.014, out: 1.32, est: true, note: "高峰价上界;空闲减半" },
  // ★ 带客户端前缀的变体:Reasonix 落的模型名是 `deepseek-pro/deepseek-v4-pro`(通道名 + 模型名),
  //   解析器按贡献者原样**不做归一**,所以这里必须各收一条,否则 priceOf 落到兜底、费用列标 *。
  //   代价:再来一个客户端、再来一种前缀,就要在这里再加两行。
  "deepseek-pro/deepseek-v4-pro":     { in: 1.32, cacheRead: 0.044, out: 3.96, est: true, note: "高峰价上界;空闲减半" },
  "deepseek-flash/deepseek-v4-flash": { in: 0.44, cacheRead: 0.014, out: 1.32, est: true, note: "高峰价上界;空闲减半" },
};

/** 本机在跑但费率表里没有的型号，按同平台最接近的档位估算，**一律标 est**。 */
const FALLBACK: Record<string, Price> = {
  claude:   { in: 5.0,   cacheRead: 0.5,    out: 25.0, cacheWrite: 6.25, est: true },
  codex:    { in: 5.0,   cacheRead: 0.5,    out: 30.0, est: true, note: "按 gpt-5.6-sol 档" },
  grok:     { in: 2.0,   cacheRead: 0.3,    out: 6.0,  est: true },
  kimi:     { in: 3.0,   cacheRead: 0.3,    out: 15.0, est: true, note: "按 kimi-k3 档" },
  // ★ 这两个此前**没有兜底**,未登记的型号会拿到 {0,0,0} ⇒ 费用列显示 $0.000 ——
  //   「真的没花钱」和「我不知道多少钱」显示成同一个值,是本项目明令禁止的那类静默降级。
  mimo:     { in: 0.435, cacheRead: 0.0036, out: 0.87, cacheWrite: 0, est: true },
  deepseek: { in: 1.32,  cacheRead: 0.044,  out: 3.96, est: true, note: "高峰价上界" },
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
