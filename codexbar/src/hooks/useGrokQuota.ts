import type { GrokSnapshot } from "../grok";
import { useQuotaSidecar, type QuotaSidecar } from "./useQuotaSidecar";

/**
 * grok 周额度的取数 hook。循环体在 `useQuotaSidecar`（与 agy 共用），这里只定策略。
 *
 * ★★ 这条链路的关键事实：**它会联网。**
 * `useTraffic` 扫的是本机盘（零额度消耗、不联网、不碰凭证），这条要拿 grok 的 bearer 打 xAI。
 * 所以频次上有四道闸，任何一道都不能省：
 *   ① 只在钻进 grok 详情页时 `enabled`（总览页不联网）
 *   ② 快照新鲜度 `FRESH_MS = 10min`（下面这个常量）
 *   ③ `document.visibilityState` 门（没人看时零请求）
 *   ④ Rust 侧 `GROK_COALESCE_SECS = 300` 双检
 * 周窗口是 10080 分钟，每 1% ≈ 100 分钟 —— 10 分钟粒度已经远超需要。
 */
const FRESH_MS = 10 * 60 * 1000;

export function useGrokQuota(opts: { enabled?: boolean } = {}): QuotaSidecar<GrokSnapshot> {
  return useQuotaSidecar<GrokSnapshot>({
    readCmd: "read_grok_quota",
    runCmd: "run_grok_quota",
    freshMs: FRESH_MS,
    enabled: opts.enabled,
  });
}
