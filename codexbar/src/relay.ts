/** 中转站（第三方 OpenAI 协议 relay）的前端类型与文案。**纯函数，无副作用。**
 *
 * ## 为什么文案单独一个模块
 *
 * 路由的每一个非正常态，背后都是一条**静默失败**：codex 对它们全都不报错，
 * 直接退回 base 配置（= 直连单号、不轮换、WS 全开），和正常运行长得一模一样。
 * 所以这些文案不是装饰，它们是那条失败**唯一**会出声的地方 ——
 * 每一条都必须说清楚「现在实际会发生什么」和「你该敲什么」。
 *
 * 状态集合与 `relay/store.py::route_status` 一一对应，
 * 由 `tests/test_relay_route_copy.py` 从源码解析后三方比对（TS 联合 / switch / Python），
 * **不许任何一方手抄一份**。
 */

export type RouteState =
  | "pool"
  | "relay"
  | "relay_disabled"
  | "profile_missing"
  | "orphan"
  | "route_corrupt";

export interface RouteStatus {
  state: RouteState;
  profile: string | null;
  path?: string;
  label?: string;
  key_fp?: string;
  detail?: string;
  drift?: Record<string, { actual: unknown; expected: unknown }>;
}

export interface RelayRow {
  id: string;
  label: string;
  base_url: string;
  enabled: boolean;
  usage_path: string | null;
  model: string | null;
  key_fp: string;
  added_at?: string;
}

/** `/usage` 归一化后的形状。**读不到的字段一律 `null`，绝不是 0。** */
export interface RelayUsage {
  balance: number | null;
  unit: string | null;
  plan: string | null;
  /** ★ 两个口径并列。`cost` 是牌价、`actual_cost` 是真实扣款，实测差 3.85 倍。 */
  today: { cost: number | null; actual_cost: number | null; requests: number | null; total_tokens: number | null };
  total: { cost: number | null; actual_cost: number | null; requests: number | null; total_tokens: number | null; cache_read_tokens?: number | null };
  /** 每天两个分解维度都有：
   *  - 四类 token（`input/output/cache_read/cache_write`）—— 上游 `daily_usage` 直接给；
   *  - **按模型**（`models`）—— 后端逐日查 `?start_date=D&end_date=D` 拿到，
   *    实测逐 token 与当天 `total_tokens` 相等（8/8 天）。
   *
   *  ★ `models` 为 `null` = **这天没取到明细**，不是"这天没用过模型"。
   *    前端必须把两者分开显示 —— 又一次「读不到」vs「确实没有」。 */
  daily: Array<{
    date: string; requests: number; total_tokens: number;
    input_tokens: number; output_tokens: number;
    cache_read_tokens: number; cache_write_tokens: number;
    cost: number; actual_cost: number;
    models?: Array<{
      model: string; requests: number; total_tokens: number;
      input_tokens: number; output_tokens: number;
      cache_read_tokens: number; cache_write_tokens: number;
      cost: number; actual_cost: number;
    }> | null;
  }>;
  models: Array<{
    model: string; requests: number; total_tokens: number;
    input_tokens: number; output_tokens: number;
    cache_read_tokens: number; cache_write_tokens: number;
    cost: number; actual_cost: number;
  }>;
  runway: { days: number | null; per_active_day: number | null; sample_days: number; reason: string | null };
  usage_path: string;
  fetched_at: number;
}

export interface RelayEntry {
  id: string;
  label: string | null;
  base_url?: string;
  key_fp?: string;
  state?: string;
  ok?: boolean;
  detail?: string;
  http?: number;
  data?: RelayUsage;
  /** ★ 这次没取到，显示的是**上一次**的数据。「取不到」与「确实没有」必须可区分 ——
   *  折叠成一个值就是用户看到的"用量丢失了"。 */
  stale?: boolean;
  stale_since?: number;
}

export interface RelaySnapshot {
  ok: boolean;
  relays: RelayEntry[];
  route: RouteStatus;
  fetched_at: number;
}

/** 路由卡的文案。**每一条非正常态都必须含一个可执行的下一步动作** ——
 *  本仓铁律：告警要说「做什么」，不是只说「坏了」。 */
export function relayRouteNote(r: RouteStatus): { tone: "ok" | "warn" | "bad"; title: string; body: string } {
  switch (r.state) {
    case "pool":
      return {
        tone: "ok",
        title: "走账号池",
        body: "codex 经本地代理逐请求轮换，订阅制、不额外花钱；撞额度要等重置。",
      };
    case "relay":
      return {
        tone: "ok",
        title: `走中转站 · ${r.label ?? r.profile}`,
        body: "按量付费，随时可用。每次请求都在消耗余额 —— 注意下面的实扣与剩余天数。",
      };
    case "profile_missing":
      return {
        tone: "bad",
        title: "rotateproxy.config.toml 不存在",
        body:
          `找不到 ${r.path ?? ""}。codex 对此**不报错**，会静默退回 base 配置` +
          "（直连单号、不轮换、WS 全开）—— 表面上和正常运行一模一样。" +
          "终端里跑 `./codex-rotate health` 会打印修复命令。",
      };
    case "orphan":
      return {
        tone: "bad",
        title: "路由指向一个已删除的中转站",
        body:
          (r.detail ?? "") +
          " 代理会退回账号池 —— 你以为在按量付费，实际扣的是订阅额度。" +
          "重新选一次路由即可。",
      };
    case "relay_disabled":
      return {
        tone: "bad",
        title: `${r.label ?? r.profile} 已停用，但路由还指着它`,
        body:
          (r.detail ?? "") +
          " 代理会退回账号池 —— 你以为在按量付费，实际扣的是订阅额度。" +
          "要么启用它，要么明确切回账号池。",
      };
    case "route_corrupt":
      return {
        tone: "bad",
        title: "路由文件损坏",
        body:
          (r.detail ?? "") +
          " 在下面重新选一次路由即可重写它。",
      };
  }
}

/** 金额显示。★ `null` 显 `—` 而不是 `$0.00` —— 「读不到」和「真的是 0」是两件事。 */
export function money(v: number | null | undefined, unit: string | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const n = v.toFixed(v < 1 ? 4 : 2);
  if (unit === "USD") return `$${n}`;
  // ★★ **币种读不到时绝不默认 `$`**（2026-09-10 修）。`monitor.py` 明写着
  //    「读不到就 None，不许默认 USD —— 国内中转站不少按 CNY 或"额度"计，
  //    编一个 `$` 比留空糟得多」，而这里正是那条规则的另一半实现，一直在编。
  //    同一条规则的两份实现分叉，而分叉的后果是用户按错误的币种判断余额。
  //    没有币种就**只给数字**：少一个符号是"我不知道"，给错符号是一句假话。
  if (!unit) return n;
  return `${n} ${unit}`;
}

/** 一组中转站的币种是否可加。`null`（读不到）自成一类 —— 它和 USD 也不可加。 */
export function currencyOf(units: (string | null | undefined)[]):
    { unit: string | null; mixed: boolean } {
  const set = new Set(units.map((u) => u || ""));
  if (set.size > 1) return { unit: null, mixed: true };
  const only = [...set][0] ?? "";
  return { unit: only || null, mixed: false };
}

/** runway 文案。样本不足 / 余额读不到时**说出原因**，不给一个看着精确的假数。 */
export function runwayText(rw: RelayUsage["runway"] | undefined): string {
  if (!rw) return "—";
  if (rw.days === null) return `— · ${rw.reason ?? "无法估算"}`;
  return `≈ ${Math.round(rw.days)} 个活跃日`;
}
