import type { RelaySnapshot } from "../relay";
import { useQuotaSidecar, type QuotaSidecar } from "./useQuotaSidecar";

/**
 * 中转站用量的取数 hook。循环体在 `useQuotaSidecar`（与 grok / agy 共用），这里只定策略。
 *
 * ★★ **节流按成本结构定，不是随手抄一个数**（三条链路成本完全不同）：
 *   grok  → 联网打 xAI，用别人的配额             → 10min
 *   agy   → 本机 loopback RPC，零联网零配额        → 2min
 *   relay → **联网**打中转站 `/usage`，实测 2.34s   → **5min**
 *
 * 5 分钟的理由：这个接口本身**不计费**（只读账单），但它是外网往返，且它的数字
 * 是**按天聚合**的 —— 分钟级刷新不会让任何一个数字变得更准，只是多几次往返。
 * 真正需要立刻看到变化的时刻（刚跑完一次请求）由手动 ↻（`force`）覆盖。
 *
 * ★ 时间戳键必须是 `fetched_at`。Rust 侧 `fresh_sidecar(RELAY_SNAPSHOT, "fetched_at", …)`
 *   与 `HasFetchedAt` 都认这个名字；曾经 Python 那边发的是 `generated_at`，
 *   结果前端**永远判过期、每次进页都联网** —— 不报错，只是白费流量。**只留一个键。**
 */
const FRESH_MS = 5 * 60 * 1000;

export function useRelayUsage(opts: { enabled?: boolean } = {}): QuotaSidecar<RelaySnapshot> {
  return useQuotaSidecar<RelaySnapshot>({
    readCmd: "read_relay_snapshot",
    runCmd: "run_relay_usage",
    freshMs: FRESH_MS,
    enabled: opts.enabled,
  });
}
